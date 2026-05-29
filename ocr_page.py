"""OCR 识别页面 — 独立于 PDF 编辑"""

import os
import tempfile

from PySide6.QtCore import QPoint, QRect, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ocr_backend import get_ocr_backend, OcrWorker, status

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp"}


# ==================== 屏幕截图控件 ====================


class ScreenCapture(QWidget):
    """全屏遮罩 + 拖拽区域选择截图"""

    captured = Signal(QPixmap)

    def __init__(self):
        super().__init__()
        self._start = QPoint()
        self._end = QPoint()
        self._drawing = False

        screen_geo = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(screen_geo)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # 保存一份干净的截图作为背景
        self._clean_bg = QApplication.primaryScreen().grabWindow(0)

        self.showFullScreen()

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawPixmap(0, 0, self._clean_bg)

        if self._drawing:
            r = self._selection_rect()
            if r.width() > 0 and r.height() > 0:
                # 用 QPainterPath + OddEvenFill 在暗色遮罩上挖洞
                path = QPainterPath()
                path.addRect(self.rect())
                path.addRect(r)
                p.fillPath(path, QColor(0, 0, 0, 120))
                # 蓝色边框
                p.setPen(QPen(QColor("#409eff"), 2))
                p.drawRect(r)
        else:
            p.fillRect(self.rect(), QColor(0, 0, 0, 120))

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.globalPosition().toPoint()
            self._end = self._start
            self._drawing = True
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drawing:
            self._end = event.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._drawing:
            self._drawing = False
            r = self._selection_rect()
            if r.width() > 10 and r.height() > 10:
                pixmap = QApplication.primaryScreen().grabWindow(
                    0, r.x(), r.y(), r.width(), r.height()
                )
                self.captured.emit(pixmap)
            self.close()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def _selection_rect(self):
        return QRect(
            min(self._start.x(), self._end.x()),
            min(self._start.y(), self._end.y()),
            abs(self._end.x() - self._start.x()),
            abs(self._end.y() - self._start.y()),
        )


class DropImageZone(QFrame):
    """虚线拖拽区域，接受图片拖入"""
    image_dropped = Signal(str)  # 发出图片文件路径

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(
            "将图片拖拽此处",
            objectName="dropLabel",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        layout.addWidget(label)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                ext = os.path.splitext(url.toLocalFile())[1].lower()
                if ext in SUPPORTED_IMAGE_EXTS:
                    event.acceptProposedAction()
                    self.setStyleSheet(
                        "#dropZone { background-color: #ecf5ff;"
                        " border: 2px dashed #409eff; border-radius: 10px; }"
                    )
                    return

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet("")
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                ext = os.path.splitext(path)[1].lower()
                if ext in SUPPORTED_IMAGE_EXTS and os.path.isfile(path):
                    self.image_dropped.emit(path)
                    event.acceptProposedAction()
                    return


class OcrPage(QWidget):
    """独立的 OCR 识别页面"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._main_window = main_window  # 用于截图时隐藏/显示
        self._image_path = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        # ---- 主区域：左右分栏 ----
        body = QHBoxLayout()
        body.setSpacing(16)

        # 左侧：图片区域 (QStackedWidget: drop zone / image preview)
        self.img_stack = QStackedWidget()
        self.img_stack.setMinimumWidth(350)

        self.drop_zone = DropImageZone()
        self.drop_zone.image_dropped.connect(self._on_image_loaded)
        self.img_stack.addWidget(self.drop_zone)  # index 0

        self.img_preview = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.img_preview.setStyleSheet(
            "background-color: #ffffff; border: 1px solid #ebeef5; border-radius: 8px;"
        )
        self.img_preview.setScaledContents(False)
        self.img_stack.addWidget(self.img_preview)  # index 1

        body.addWidget(self.img_stack, stretch=1)

        # 右侧：识别文字
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setPlaceholderText("识别结果将显示在此处...")
        self.text_edit.setStyleSheet(
            "QTextEdit { font-size: 13px; background: #ffffff;"
            " border: 1px solid #dcdfe6; border-radius: 6px; }"
        )
        body.addWidget(self.text_edit, stretch=1)

        layout.addLayout(body)

        # ---- 底部按钮 ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_screenshot = QPushButton("截图识别")
        self.btn_screenshot.clicked.connect(self._on_screenshot)
        btn_row.addWidget(self.btn_screenshot)

        self.btn_paste = QPushButton("从剪贴板粘贴")
        self.btn_paste.clicked.connect(self._on_paste)
        btn_row.addWidget(self.btn_paste)

        btn_row.addStretch()

        btn_row.addWidget(QLabel("模式:"))
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["Text", "Formula", "Table"])
        self.cb_mode.setToolTip(
            "识别模式 (仅 GLM-OCR 生效)\nText: 普通文字\nFormula: LaTeX 公式\nTable: Markdown 表格"
        )
        btn_row.addWidget(self.cb_mode)

        self.btn_copy = QPushButton("复制文字")
        self.btn_copy.clicked.connect(self._on_copy_text)
        self.btn_copy.setEnabled(False)
        btn_row.addWidget(self.btn_copy)

        layout.addLayout(btn_row)

    # === 图片加载 ===
    def _on_image_loaded(self, path):
        self._set_image(path)

    def _on_screenshot(self):
        """隐藏主窗口 → 区域截图 → 恢复"""
        self._main_window.hide()
        QApplication.processEvents()
        QTimer.singleShot(250, self._start_capture)

    def _start_capture(self):
        self._capture = ScreenCapture()
        self._capture.captured.connect(self._on_captured)
        self._capture.destroyed.connect(self._main_window.show)

    def _on_captured(self, pixmap):
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        pixmap.save(tmp.name, "PNG")
        self._main_window.show()
        self._set_image(tmp.name)

    def _on_paste(self):
        """从剪贴板读取图片"""
        clipboard = QApplication.clipboard()
        pixmap = clipboard.pixmap()
        if pixmap.isNull():
            QMessageBox.warning(self, "提示", "剪贴板中没有图片。")
            return
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        pixmap.save(tmp.name, "PNG")
        self._set_image(tmp.name)

    def _set_image(self, path):
        self._image_path = path
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        # 缩放到预览区域
        max_w = self.img_preview.width() - 20
        max_h = self.img_preview.height() - 20
        if max_w > 0 and max_h > 0:
            scaled = pixmap.scaled(
                max_w, max_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            scaled = pixmap
        self.img_preview.setPixmap(scaled)
        self.img_stack.setCurrentIndex(1)
        self._run_ocr(path)

    # === OCR ===
    def _run_ocr(self, path):
        backend = get_ocr_backend()
        if backend is None:
            status("没有可用的 OCR 引擎")
            return
        status("正在进行 OCR 识别...")
        self.text_edit.setPlainText("识别中...")
        self.btn_copy.setEnabled(False)

        # 模式仅 GLM-OCR 有效，其他引擎忽略
        is_ollama = type(backend).__name__ == "OllamaOcrBackend"
        self.cb_mode.setEnabled(is_ollama)
        mode_map = {"Text": "Text Recognition:", "Formula": "Formula Recognition:", "Table": "Table Recognition:"}
        mode = mode_map.get(self.cb_mode.currentText(), "Text Recognition:") if is_ollama else ""

        self.worker = OcrWorker(backend, path, mode)
        self.worker.finished.connect(self._on_ocr_done)
        self.worker.error.connect(self._on_ocr_error)
        self.worker.start()

    def _on_ocr_done(self, text):
        self.text_edit.setPlainText(text)
        self.btn_copy.setEnabled(True)
        status("OCR 识别完成")

        if QSettings("办公工具箱", "办公工具箱").value("ocr/auto_copy", "false") == "true":
            QApplication.clipboard().setText(text)
            status("OCR 识别完成 — 文字已自动复制")

    def _on_ocr_error(self, msg):
        self.text_edit.setPlainText(f"识别失败：{msg}")
        status("OCR 识别失败")

    def _on_copy_text(self):
        QApplication.clipboard().setText(self.text_edit.toPlainText())
        status("文字已复制到剪贴板")
