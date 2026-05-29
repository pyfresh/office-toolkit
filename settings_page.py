"""设置页面"""

import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

FONT_SIZES = {"小": 9, "中": 10, "大": 11}
LANGUAGES = {
    "简体中文": "zh-Hans",
    "繁體中文": "zh-Hant",
    "English": "en-US",
    "日本語": "ja-JP",
    "한국어": "ko-KR",
}


def _find_ollama():
    """查找 ollama 可执行文件, 返回路径或 None"""
    paths = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Ollama", "ollama.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Ollama", "ollama.exe"),
    ]
    for p in paths:
        if os.path.isfile(p):
            return p
    # 最后尝试 PATH
    return shutil.which("ollama")


class _OllamaCheckWorker(QThread):
    """后台检测 Ollama 状态"""
    result = Signal(str)  # "ok" / "no_ollama" / "no_service" / "no_model"

    def run(self):
        ollama_exe = _find_ollama()
        if not ollama_exe:
            self.result.emit("no_ollama")
            return
        # 快速端口探测
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        port_open = sock.connect_ex(("127.0.0.1", 11434)) == 0
        sock.close()
        if not port_open:
            self.result.emit("no_service")
            return
        # 用 CLI 查模型列表，不用 SDK（SDK 可能挂死）
        try:
            r = subprocess.run(
                [ollama_exe, "list"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if "glm-ocr" in r.stdout:
                self.result.emit("ok")
            else:
                self.result.emit("no_model")
        except Exception:
            self.result.emit("no_service")


OLLAMA_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"

class _InstallWorker(QThread):
    """后台下载 → 安装 → 拉取模型"""
    progress = Signal(int, str)   # 百分比, 状态文字
    finished = Signal()
    error = Signal(str)

    def __init__(self, skip_install=False):
        super().__init__()
        self._skip_install = skip_install  # 已有 Ollama 时跳过下载安装
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            if not self._skip_install:
                dest = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")

                # 删除可能损坏的旧文件，重新下载
                if os.path.isfile(dest):
                    os.remove(dest)

                # 阶段 1: 下载
                self.progress.emit(0, "正在下载 Ollama 安装程序...")
                self._download(OLLAMA_INSTALLER_URL, dest)
                if self._cancelled:
                    return

                # 校验下载完整性（安装包至少 100MB）
                size_mb = os.path.getsize(dest) / (1024 * 1024)
                if size_mb < 100:
                    os.remove(dest)
                    self.error.emit(f"安装程序下载不完整 ({size_mb:.0f} MB)，请检查网络后重试")
                    return

                # 阶段 2: 静默安装
                self.progress.emit(80, "正在安装 Ollama...")
                subprocess.run(
                    [dest, "/VERYSILENT"],
                    check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )

                # 轮询等待 ollama.exe 出现
                self.progress.emit(83, "等待 Ollama 就绪...")
                ready = False
                for _ in range(40):
                    if self._cancelled:
                        return
                    if _find_ollama():
                        ready = True
                        break
                    time.sleep(0.5)
                if not ready:
                    self.error.emit("Ollama 安装后未找到，请手动运行一次 Ollama 后重试")
                    return

                # 等待服务可响应
                time.sleep(1)

            if self._cancelled:
                return

            # 阶段 3: 拉取 glm-ocr 模型
            self.progress.emit(85, "正在拉取 glm-ocr 模型（约 2.2GB）...")
            ollama_exe = _find_ollama()
            if not ollama_exe:
                self.error.emit("未找到 ollama，请先安装")
                return
            proc = subprocess.Popen(
                [ollama_exe, "pull", "glm-ocr"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in proc.stdout:
                if self._cancelled:
                    proc.terminate()
                    return
                pct = self._parse_pull_progress(line)
                if pct is not None:
                    self.progress.emit(85 + int(pct * 0.15), f"正在拉取 glm-ocr 模型... {pct}%")
            proc.wait()

            self.progress.emit(100, "安装完成")
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def _download(self, url, dest):
        def _hook(count, block_size, total_size):
            if self._cancelled:
                raise InterruptedError()
            if total_size > 0:
                pct = min(int(count * block_size / total_size * 80), 80)
                mb = total_size / 1024 / 1024
                self.progress.emit(pct, f"正在下载安装程序... ({mb:.0f} MB)")

        urllib.request.urlretrieve(url, dest, reporthook=_hook)

    @staticmethod
    def _parse_pull_progress(line):
        m = re.search(r'(\d+)%', line)
        return int(m.group(1)) if m else None


class _RapidInstallWorker(QThread):
    """后台 pip install rapidocr"""
    progress = Signal(int, str)   # 百分比, 状态文字
    finished = Signal(bool)

    def run(self):
        import importlib, re, subprocess, sys
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "rapidocr", "onnxruntime",
                 "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "--progress-bar", "on"],
                stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                text=True, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            stages_pattern = re.compile(r"^\s*(Downloading|Installing|Building|Using).*$")
            pct_pattern = re.compile(r"(\d+)%")
            last_pct = 0
            for line in proc.stderr:
                m = pct_pattern.search(line)
                if m:
                    pct = int(m.group(1))
                    # 下载占 80%，安装占 20%
                    if "Installing" in line or "Building" in line:
                        pct = 80 + pct // 5
                    last_pct = max(last_pct, pct)
                    self.progress.emit(last_pct, "正在安装 RapidOCR...")
                elif stages_pattern.match(line.strip()):
                    self.progress.emit(last_pct, line.strip()[:60])
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"pip exit {proc.returncode}")
            self.progress.emit(100, "安装完成")
            importlib.invalidate_caches()
            import rapidocr  # noqa: F401
            self.finished.emit(True)
        except Exception:
            self.finished.emit(False)


class RapidInstallDialog(QDialog):
    """RapidOCR 安装进度对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self.setWindowTitle("安装 RapidOCR")
        self.setFixedSize(400, 130)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint
        )
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.label = QLabel("准备安装 RapidOCR（约 20MB）...")
        layout.addWidget(self.label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

    def start(self):
        self._worker = _RapidInstallWorker()
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, pct, msg):
        self.progress_bar.setValue(pct)
        self.label.setText(msg)

    def _on_done(self, ok):
        if ok:
            self.progress_bar.setValue(100)
            self.label.setText("安装完成")
            self.accept()
        else:
            self.label.setText("安装失败，请检查网络后重试")
            self.btn_cancel.setText("关闭")

    def _on_cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
        self.reject()


class InstallOllamaDialog(QDialog):
    """安装进度对话框"""

    def __init__(self, skip_install=False, parent=None):
        super().__init__(parent)
        self._worker = None
        self._skip_install = skip_install
        title = "拉取 glm-ocr 模型" if skip_install else "安装 Ollama"
        self.setWindowTitle(title)
        self.setFixedSize(420, 140)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint
        )
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.label = QLabel("准备中...")
        layout.addWidget(self.label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

    def start(self):
        self._worker = _InstallWorker(skip_install=self._skip_install)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self.accept)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, pct, msg):
        self.progress_bar.setValue(pct)
        self.label.setText(msg)

    def _on_error(self, msg):
        self.label.setText(f"错误：{msg}")
        self.btn_cancel.setText("关闭")

    def _on_cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        self.reject()


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._check_worker = None
        self._ollama_ready = False
        self._rapid_ready = False
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(20)

        # ---- OCR 分组 ----
        ocr_group = QGroupBox("OCR 文字识别")
        ocr_layout = QVBoxLayout(ocr_group)
        ocr_layout.setSpacing(10)

        ocr_layout.addWidget(QLabel("引擎"))

        # --- Windows OCR ---
        self.rb_windows = QRadioButton("Windows 系统 OCR（系统自带，无需下载）")
        self.rb_windows.toggled.connect(self._on_engine_changed)
        ocr_layout.addWidget(self.rb_windows)

        self.win_sub = QWidget()
        win_sub_layout = QVBoxLayout(self.win_sub)
        win_sub_layout.setContentsMargins(24, 0, 0, 0)
        win_sub_layout.addWidget(QLabel("语言"))
        self.cb_language = QComboBox()
        self.cb_language.addItems(list(LANGUAGES.keys()))
        self.cb_language.currentIndexChanged.connect(self._on_language_changed)
        win_sub_layout.addWidget(self.cb_language)
        ocr_layout.addWidget(self.win_sub)

        # --- RapidOCR ---
        rapid_row = QHBoxLayout()
        self.rb_rapidocr = QRadioButton("RapidOCR（ONNX 本地，快速高精度）")
        self.rb_rapidocr.setEnabled(False)
        self.rb_rapidocr.toggled.connect(self._on_engine_changed)
        rapid_row.addWidget(self.rb_rapidocr)
        self.btn_detect_rapid = QPushButton("检测")
        self.btn_detect_rapid.setFixedSize(48, 24)
        self.btn_detect_rapid.setStyleSheet("QPushButton { padding: 0px; font-size: 11px; }")
        self.btn_detect_rapid.clicked.connect(self._on_detect_rapidocr)
        rapid_row.addWidget(self.btn_detect_rapid)
        rapid_row.addStretch()
        ocr_layout.addLayout(rapid_row)

        # hint + install button（不受子面板控制，始终可见）
        self.rapid_hint = QLabel()
        self.rapid_hint.setStyleSheet("color: #909399; font-size: 11px; margin-left: 24px;")
        self.rapid_hint.setWordWrap(True)
        self.rapid_hint.setVisible(False)
        ocr_layout.addWidget(self.rapid_hint)

        btn_style = "QPushButton { padding: 2px 8px; font-size: 11px; }"
        self.btn_install_rapid = QPushButton("安装 RapidOCR")
        self.btn_install_rapid.setStyleSheet(btn_style + " margin-left: 24px;")
        self.btn_install_rapid.clicked.connect(self._on_install_rapidocr)
        self.btn_install_rapid.setVisible(False)
        ocr_layout.addWidget(self.btn_install_rapid)

        # 子设置面板（仅选中时显示）
        self.rapid_sub = QWidget()
        rapid_sub_layout = QVBoxLayout(self.rapid_sub)
        rapid_sub_layout.setContentsMargins(24, 0, 0, 0)
        rapid_sub_layout.addWidget(QLabel("模型精度"))
        self.cb_rapid_model = QComboBox()
        self.cb_rapid_model.addItems(["Mobile (快)", "Server (准)"])
        self.cb_rapid_model.currentIndexChanged.connect(self._on_rapidocr_changed)
        rapid_sub_layout.addWidget(self.cb_rapid_model)
        rapid_sub_layout.addWidget(QLabel("识别语言"))
        self.cb_rapid_lang = QComboBox()
        self.cb_rapid_lang.addItems(["CH (中英日)", "EN (English)", "Latin", "Korean"])
        self.cb_rapid_lang.currentIndexChanged.connect(self._on_rapidocr_changed)
        rapid_sub_layout.addWidget(self.cb_rapid_lang)
        ocr_layout.addWidget(self.rapid_sub)

        # --- GLM-OCR ---
        glm_row = QHBoxLayout()
        self.rb_ollama = QRadioButton("GLM-OCR via Ollama（本地 GPU 推理）")
        self.rb_ollama.setEnabled(False)
        glm_row.addWidget(self.rb_ollama)
        self.btn_detect = QPushButton("检测")
        self.btn_detect.setFixedSize(48, 24)
        self.btn_detect.setStyleSheet("QPushButton { padding: 0px; font-size: 11px; }")
        self.btn_detect.clicked.connect(self._on_detect)
        glm_row.addWidget(self.btn_detect)
        glm_row.addStretch()
        ocr_layout.addLayout(glm_row)

        self.ollama_sub = QWidget()
        ollama_sub_layout = QVBoxLayout(self.ollama_sub)
        ollama_sub_layout.setContentsMargins(24, 0, 0, 0)
        self.ollama_hint = QLabel()
        self.ollama_hint.setStyleSheet("color: #909399; font-size: 11px;")
        self.ollama_hint.setWordWrap(True)
        self.ollama_hint.setVisible(False)
        ollama_sub_layout.addWidget(self.ollama_hint)

        self.ollama_action_layout = QHBoxLayout()
        btn_style = "QPushButton { padding: 2px 8px; font-size: 11px; }"
        self.btn_install_ollama = QPushButton("安装 Ollama")
        self.btn_install_ollama.setStyleSheet(btn_style)
        self.btn_install_ollama.clicked.connect(self._on_install_ollama)
        self.btn_install_ollama.setVisible(False)
        self.ollama_action_layout.addWidget(self.btn_install_ollama)
        self.btn_pull_model = QPushButton("拉取 glm-ocr 模型")
        self.btn_pull_model.setStyleSheet(btn_style)
        self.btn_pull_model.clicked.connect(self._on_pull_model)
        self.btn_pull_model.setVisible(False)
        self.ollama_action_layout.addWidget(self.btn_pull_model)
        self.ollama_action_layout.addStretch()
        ollama_sub_layout.addLayout(self.ollama_action_layout)
        ocr_layout.addWidget(self.ollama_sub)

        # 自动复制
        self.chk_auto_copy = QCheckBox("识别后自动复制文字到剪贴板")
        self.chk_auto_copy.toggled.connect(self._on_auto_copy_changed)
        ocr_layout.addWidget(self.chk_auto_copy)

        layout.addWidget(ocr_group)

        # ---- 外观分组 ----
        appearance_group = QGroupBox("外观")
        appearance_layout = QVBoxLayout(appearance_group)
        appearance_layout.setSpacing(10)

        appearance_layout.addWidget(QLabel("界面风格"))
        self.cb_theme = QComboBox()
        self.cb_theme.addItems(["浅色", "深色"])
        self.cb_theme.currentIndexChanged.connect(self._on_theme_changed)
        appearance_layout.addWidget(self.cb_theme)

        appearance_layout.addWidget(QLabel("字体大小"))
        self.cb_font_size = QComboBox()
        self.cb_font_size.addItems(list(FONT_SIZES.keys()))
        self.cb_font_size.currentIndexChanged.connect(self._on_font_size_changed)
        appearance_layout.addWidget(self.cb_font_size)

        layout.addWidget(appearance_group)
        layout.addStretch()

    # ---- 加载 ----
    def _load(self):
        settings = QSettings("办公工具箱", "办公工具箱")
        engine = settings.value("ocr/engine", "windows")

        self.rb_windows.setChecked(engine == "windows")
        self.rb_rapidocr.setChecked(engine == "rapidocr")
        self.rb_ollama.setChecked(engine == "ollama")

        if engine == "ollama":
            self._on_detect()
        elif engine == "rapidocr":
            self._on_detect_rapidocr()

        lang_code = settings.value("ocr/language", "zh-Hans")
        lang_label = next(
            (k for k, v in LANGUAGES.items() if v == lang_code), "简体中文"
        )
        self.cb_language.setCurrentText(lang_label)

        # RapidOCR settings
        model = settings.value("ocr/rapidocr_model", "mobile")
        self.cb_rapid_model.setCurrentText(
            "Server (准)" if model == "server" else "Mobile (快)"
        )
        rapid_lang_map = {"ch": 0, "en": 1, "latin": 2, "korean": 3}
        rapid_lang = settings.value("ocr/rapidocr_lang", "ch")
        self.cb_rapid_lang.setCurrentIndex(rapid_lang_map.get(rapid_lang, 0))

        self._update_sub_panels()

        self.chk_auto_copy.setChecked(
            settings.value("ocr/auto_copy", "false") == "true"
        )

        theme = settings.value("app/theme", "light")
        self.cb_theme.setCurrentText("深色" if theme == "dark" else "浅色")

        font_size = settings.value("app/font_size", "中")
        self.cb_font_size.setCurrentText(font_size)

    def _update_sub_panels(self):
        """根据选中的引擎显示/隐藏子设置面板"""
        self.win_sub.setVisible(self.rb_windows.isChecked())
        # RapidOCR 子面板：选中时显示完整内容，未选中时仅显示 hint/按钮
        self.rapid_sub.setVisible(
            self.rb_rapidocr.isChecked() or self.rapid_hint.isVisible()
        )
        self.ollama_sub.setVisible(self.rb_ollama.isChecked())

    # ---- 检测 ----
    def _on_detect(self):
        self._stop_polling()
        self.btn_detect.setEnabled(False)
        self.btn_detect.setText("...")
        self.ollama_hint.setVisible(True)
        self.ollama_hint.setText("正在检测 Ollama 环境...")
        self.btn_install_ollama.setVisible(False)
        self.btn_pull_model.setVisible(False)

        self._check_worker = _OllamaCheckWorker()
        self._check_worker.result.connect(self._on_detect_result)
        self._check_worker.start()

    def _on_detect_result(self, status):
        self.btn_detect.setEnabled(True)
        self.btn_detect.setText("检测")
        self.btn_install_ollama.setVisible(False)
        self.btn_pull_model.setVisible(False)

        if status == "ok":
            self._ollama_ready = True
            self.rb_ollama.setEnabled(True)
            self.ollama_hint.setText("GLM-OCR 环境已就绪 ✓")
            self.ollama_hint.setStyleSheet("color: #67c23a; font-size: 11px;")
            settings = QSettings("办公工具箱", "办公工具箱")
            if settings.value("ocr/engine") == "ollama":
                self.rb_ollama.setChecked(True)
        elif status == "no_ollama":
            self._ollama_ready = False
            self.rb_ollama.setEnabled(False)
            self.ollama_hint.setText("未检测到 Ollama，请先安装")
            self.ollama_hint.setStyleSheet("color: #f56c6c; font-size: 11px;")
            self.btn_install_ollama.setVisible(True)
            self.btn_pull_model.setVisible(False)
        elif status == "no_service":
            self._ollama_ready = False
            self.rb_ollama.setEnabled(False)
            self.ollama_hint.setText("Ollama 已安装但后台服务未运行，正在自动启动...")
            self.ollama_hint.setStyleSheet("color: #e6a23c; font-size: 11px;")
            self.btn_install_ollama.setVisible(False)
            self.btn_pull_model.setVisible(False)
            self._auto_start_ollama()
        elif status == "no_model":
            self._ollama_ready = False
            self.rb_ollama.setEnabled(False)
            self.ollama_hint.setText("已检测到 Ollama，但未拉取 glm-ocr 模型")
            self.ollama_hint.setStyleSheet(
                "color: #e6a23c; font-size: 11px;"
            )
            self.btn_pull_model.setVisible(True)
    def _auto_start_ollama(self):
        exe = _find_ollama()
        if not exe:
            self.ollama_hint.setText("未找到 ollama.exe")
            self.ollama_hint.setStyleSheet("color: #f56c6c; font-size: 11px;")
            return
        subprocess.Popen(
            [exe, "serve"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.btn_detect.setEnabled(False)
        self.btn_detect.setText("...")
        self._poll_attempt = 0
        self._start_poll_timer()

    def _stop_polling(self):
        if hasattr(self, '_poll_timer') and self._poll_timer.isActive():
            self._poll_timer.stop()

    def _start_poll_timer(self):
        from PySide6.QtCore import QTimer
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(800)
        self._poll_timer.timeout.connect(self._poll_tick)
        self._poll_timer.start()

    def _poll_tick(self):
        self._poll_attempt += 1
        dots = "." * ((self._poll_attempt % 4) + 1)
        self.ollama_hint.setText(f"正在等待 Ollama 服务就绪{dots}")

        if self._poll_attempt > 19:  # ~15s
            self._poll_timer.stop()
            self.btn_detect.setEnabled(True)
            self.btn_detect.setText("检测")
            self.ollama_hint.setText("Ollama 服务启动超时，请尝试手动运行 Ollama")
            self.ollama_hint.setStyleSheet("color: #f56c6c; font-size: 11px;")
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        try:
            if sock.connect_ex(("127.0.0.1", 11434)) == 0:
                self._poll_timer.stop()
                sock.close()
                self._on_detect()
                return
        finally:
            sock.close()

    def _on_install_ollama(self):
        dlg = InstallOllamaDialog(skip_install=False, parent=self)
        dlg.start()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._on_detect()

    def _on_pull_model(self):
        dlg = InstallOllamaDialog(skip_install=True, parent=self)
        dlg.start()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._on_detect()

    # ---- 事件 ----
    def _on_engine_changed(self):
        settings = QSettings("办公工具箱", "办公工具箱")
        if self.rb_ollama.isChecked():
            if self._ollama_ready:
                settings.setValue("ocr/engine", "ollama")
            else:
                self.rb_ollama.setChecked(False)
                self.rb_windows.setChecked(True)
        elif self.rb_rapidocr.isChecked():
            if self._rapid_ready:
                settings.setValue("ocr/engine", "rapidocr")
            else:
                self.rb_rapidocr.setChecked(False)
                self.rb_windows.setChecked(True)
        else:
            settings.setValue("ocr/engine", "windows")
        self._update_sub_panels()

    def _on_rapidocr_changed(self):
        settings = QSettings("办公工具箱", "办公工具箱")
        model = "server" if "Server" in self.cb_rapid_model.currentText() else "mobile"
        settings.setValue("ocr/rapidocr_model", model)
        lang_map = {"CH": "ch", "EN": "en", "Latin": "latin", "Korean": "korean"}
        lang_key = self.cb_rapid_lang.currentText().split()[0]
        settings.setValue("ocr/rapidocr_lang", lang_map.get(lang_key, "ch"))
        # 清除模块级缓存，下次识别时用新参数重建引擎
        import ocr_backend
        ocr_backend._rapid_engine = None
        ocr_backend._rapid_engine_key = None

    def _on_detect_rapidocr(self):
        self.btn_detect_rapid.setEnabled(False)
        self.btn_detect_rapid.setText("...")
        self.rapid_hint.setVisible(True)
        self.rapid_hint.setText("正在检测 RapidOCR...")
        self.rapid_hint.setStyleSheet("color: #909399; font-size: 11px;")
        self.btn_install_rapid.setVisible(False)

        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self._do_rapid_check)

    def _do_rapid_check(self):
        ok = False
        try:
            import rapidocr  # noqa: F401
            ok = True
        except ImportError:
            ok = False
        self._on_rapid_detect_result(ok)

    def _on_rapid_detect_result(self, ok):
        self.btn_detect_rapid.setEnabled(True)
        self.btn_detect_rapid.setText("检测")
        self.btn_install_rapid.setVisible(not ok)
        if ok:
            self._rapid_ready = True
            self.rb_rapidocr.setEnabled(True)
            self.rapid_hint.setText("RapidOCR 已就绪 ✓（模型将在首次识别时自动下载）")
            self.rapid_hint.setStyleSheet("color: #67c23a; font-size: 11px;")
            settings = QSettings("办公工具箱", "办公工具箱")
            if settings.value("ocr/engine") == "rapidocr":
                self.rb_rapidocr.setChecked(True)
        else:
            self._rapid_ready = False
            self.rb_rapidocr.setEnabled(False)
            self.rapid_hint.setText("未检测到 RapidOCR，请点击下方按钮安装")
            self.rapid_hint.setStyleSheet("color: #f56c6c; font-size: 11px;")

    def _on_install_rapidocr(self):
        dlg = RapidInstallDialog(self)
        dlg.start()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._on_detect_rapidocr()
        else:
            self.btn_install_rapid.setEnabled(True)
            self.btn_install_rapid.setText("安装 RapidOCR")

    def _on_language_changed(self):
        settings = QSettings("办公工具箱", "办公工具箱")
        label = self.cb_language.currentText()
        settings.setValue("ocr/language", LANGUAGES.get(label, "zh-Hans"))

    def _on_auto_copy_changed(self):
        settings = QSettings("办公工具箱", "办公工具箱")
        settings.setValue(
            "ocr/auto_copy", "true" if self.chk_auto_copy.isChecked() else "false"
        )

    def _on_theme_changed(self):
        from PySide6.QtWidgets import QApplication
        settings = QSettings("办公工具箱", "办公工具箱")
        theme = "dark" if self.cb_theme.currentText() == "深色" else "light"
        settings.setValue("app/theme", theme)
        app = QApplication.instance()
        if app:
            from office_toolkit import BASE_STYLE, DARK_STYLE
            app.setStyleSheet(DARK_STYLE if theme == "dark" else BASE_STYLE)

    def _on_font_size_changed(self):
        from PySide6.QtWidgets import QApplication
        settings = QSettings("办公工具箱", "办公工具箱")
        label = self.cb_font_size.currentText()
        settings.setValue("app/font_size", label)
        app = QApplication.instance()
        if app:
            font = app.font()
            font.setPointSize(FONT_SIZES.get(label, 10))
            app.setFont(font)
