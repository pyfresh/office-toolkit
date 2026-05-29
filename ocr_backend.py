"""OCR 后端：Windows OCR / RapidOCR / GLM-OCR 三引擎 + 工作线程"""

import asyncio

from PySide6.QtCore import QSettings, QThread, Signal

# ---- 全局状态栏回调（由 main_window 注入） ----

_status_fn = None


def init_status(fn):
    global _status_fn
    _status_fn = fn


def status(text):
    if _status_fn:
        _status_fn(text)


# ---- 引擎抽象 ----

class OcrBackend:
    """OCR 引擎抽象基类"""

    def recognize(self, image_path: str, mode: str = "") -> str:
        raise NotImplementedError

    @staticmethod
    def available() -> bool:
        raise NotImplementedError

    @staticmethod
    def name() -> str:
        raise NotImplementedError


class WindowsOcrBackend(OcrBackend):
    @staticmethod
    def name() -> str:
        return "Windows 系统 OCR"

    @staticmethod
    def available() -> bool:
        try:
            import winocr  # noqa: F401
            return True
        except ImportError:
            return False

    def recognize(self, image_path: str, mode: str = "") -> str:
        import winocr
        from PIL import Image

        lang = QSettings("办公工具箱", "办公工具箱").value("ocr/language", "zh-Hans")

        async def _run():
            img = Image.open(image_path)
            result = await winocr.recognize_pil(img, lang)
            return result.text

        return asyncio.run(_run())


class OllamaOcrBackend(OcrBackend):
    @staticmethod
    def name() -> str:
        return "GLM-OCR (Ollama 本地)"

    @staticmethod
    def available() -> bool:
        # 只检查 ollama.exe 是否存在，不用 SDK（SDK 可能挂死）
        import shutil
        import os
        paths = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Ollama", "ollama.exe"),
        ]
        for p in paths:
            if os.path.isfile(p):
                return True
        return shutil.which("ollama") is not None

    def recognize(self, image_path: str, mode: str = "Text Recognition:") -> str:
        import re
        import subprocess

        # 子进程调用 ollama CLI，避免 HTTP base64 传输开销和超时问题
        exe = self._find_exe()
        r = subprocess.run(
            [exe, "run", "glm-ocr", f"{mode} {image_path}"],
            capture_output=True, timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        output = r.stdout.decode("utf-8", errors="replace")
        # 清洗 ANSI 转义序列和进度动画字符
        output = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', output)
        output = re.sub(r'\x1b\[\d+[GK]', '', output)
        output = re.sub(r'[⠀-⣿]', '', output)  # Braille spinner
        text = output.strip()
        # 去除 "Added image '...'" 提示行
        if text.startswith("Added image"):
            lines = text.split("\n", 1)
            text = lines[1].strip() if len(lines) > 1 else ""
        return text

    @staticmethod
    def _find_exe():
        import os, shutil
        paths = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
            os.path.join(os.environ.get("ProgramFiles", ""), "Ollama", "ollama.exe"),
        ]
        for p in paths:
            if os.path.isfile(p):
                return p
        return shutil.which("ollama") or "ollama"


# RapidOCR 引擎模块级缓存（避免每次识别重新加载 ONNX 模型）
_rapid_engine = None
_rapid_engine_key = None


class RapidOCRBackend(OcrBackend):
    @staticmethod
    def name() -> str:
        return "RapidOCR (ONNX 本地)"

    @staticmethod
    def available() -> bool:
        try:
            import rapidocr  # noqa: F401
            return True
        except ImportError:
            return False

    def recognize(self, image_path: str, mode: str = "") -> str:
        global _rapid_engine, _rapid_engine_key
        from rapidocr import RapidOCR, LangRec, ModelType

        s = QSettings("办公工具箱", "办公工具箱")
        model_type = s.value("ocr/rapidocr_model", "mobile")
        lang = s.value("ocr/rapidocr_lang", "ch")
        cache_key = f"{model_type}|{lang}"

        if _rapid_engine is None or _rapid_engine_key != cache_key:
            lang_map = {
                "ch": LangRec.CH, "en": LangRec.EN,
                "latin": LangRec.LATIN, "korean": LangRec.KOREAN,
            }
            params = {
                "Det.model_type": ModelType.SERVER if model_type == "server" else ModelType.MOBILE,
                "Rec.model_type": ModelType.SERVER if model_type == "server" else ModelType.MOBILE,
                "Rec.lang_type": lang_map.get(lang, LangRec.CH),
            }
            _rapid_engine = RapidOCR(params=params)
            _rapid_engine_key = cache_key

        result = _rapid_engine(image_path, text_score=0.5)
        return "\n".join(result.txts) if result.txts else ""


def get_ocr_backend() -> OcrBackend | None:
    """根据 QSettings 选择 OCR 引擎"""
    settings = QSettings("办公工具箱", "办公工具箱")
    engine = settings.value("ocr/engine", "windows")
    if engine == "rapidocr":
        backend = RapidOCRBackend()
        if backend.available():
            return backend
    if engine == "ollama":
        backend = OllamaOcrBackend()
        if backend.available():
            return backend
    backend = WindowsOcrBackend()
    if backend.available():
        return backend
    return None


# ---- 工作线程 ----

class OcrWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, backend: OcrBackend, image_path: str, mode: str = ""):
        super().__init__()
        self.backend = backend
        self.image_path = image_path
        self.mode = mode

    def run(self):
        try:
            text = self.backend.recognize(self.image_path, self.mode)
            self.finished.emit(text)
        except Exception as e:
            self.error.emit(str(e))


