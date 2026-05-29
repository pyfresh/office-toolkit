"""办公工具箱 - 主窗口 + 入口"""

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from edit_page import EditPage
from ocr_backend import init_status
from ocr_page import OcrPage
from settings_page import SettingsPage

BASE_STYLE = """
QMainWindow { background-color: #f5f6fa; }
QFrame#dropZone {
    background-color: #ffffff;
    border: 2px dashed #c0c4cc;
    border-radius: 10px;
}
QFrame#dropZone:hover { border-color: #409eff; background-color: #ecf5ff; }
QLabel#dropLabel { color: #909399; font-size: 14px; }
QPushButton {
    background-color: #ffffff; border: 1px solid #dcdfe6;
    border-radius: 6px; padding: 8px 20px; font-size: 13px; color: #606266;
}
QPushButton:hover { color: #409eff; border-color: #c6e2ff; background-color: #ecf5ff; }
QPushButton:pressed { color: #3a8ee6; border-color: #3a8ee6; }
QPushButton#primaryBtn {
    background-color: #409eff; color: #ffffff; border: none; font-weight: bold; padding: 10px 32px;
}
QPushButton#primaryBtn:hover { background-color: #66b1ff; }
QPushButton#primaryBtn:pressed { background-color: #3a8ee6; }
QPushButton#primaryBtn:disabled { background-color: #a0cfff; }
QProgressBar {
    border: none; border-radius: 4px; background-color: #e4e7ed;
    height: 6px; text-align: center; font-size: 12px;
}
QProgressBar::chunk { background-color: #409eff; border-radius: 4px; }
QLabel#statusLabel { color: #909399; font-size: 12px; }
QScrollArea { background-color: transparent; border: none; }
QScrollArea > QWidget > QWidget { background-color: transparent; }
"""

DARK_STYLE = """
QMainWindow { background-color: #1e1e1e; }
QFrame#dropZone {
    background-color: #2d2d2d;
    border: 2px dashed #555;
    border-radius: 10px;
}
QFrame#dropZone:hover { border-color: #409eff; background-color: #333; }
QLabel#dropLabel { color: #888; font-size: 14px; }
QPushButton {
    background-color: #3c3c3c; border: 1px solid #555;
    border-radius: 6px; padding: 8px 20px; font-size: 13px; color: #ccc;
}
QPushButton:hover { color: #409eff; border-color: #409eff; background-color: #444; }
QPushButton:pressed { color: #66b1ff; border-color: #66b1ff; }
QPushButton#primaryBtn {
    background-color: #409eff; color: #ffffff; border: none; font-weight: bold; padding: 10px 32px;
}
QPushButton#primaryBtn:hover { background-color: #66b1ff; }
QPushButton#primaryBtn:pressed { background-color: #3a8ee6; }
QPushButton#primaryBtn:disabled { background-color: #555; color: #888; }
QProgressBar {
    border: none; border-radius: 4px; background-color: #444;
    height: 6px; text-align: center; font-size: 12px; color: #ccc;
}
QProgressBar::chunk { background-color: #409eff; border-radius: 4px; }
QLabel#statusLabel { color: #888; font-size: 12px; }
QScrollArea { background-color: transparent; border: none; }
QScrollArea > QWidget > QWidget { background-color: transparent; }
QGroupBox { color: #ccc; border: 1px solid #555; border-radius: 6px; margin-top: 10px; padding-top: 16px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QComboBox {
    background-color: #3c3c3c; border: 1px solid #555;
    border-radius: 4px; padding: 4px 8px; color: #ccc;
}
QComboBox:hover { border-color: #409eff; }
QComboBox QAbstractItemView {
    background-color: #3c3c3c; color: #ccc; selection-background-color: #409eff;
}
QCheckBox { color: #ccc; }
QRadioButton { color: #ccc; }
QTextEdit {
    background-color: #2d2d2d; color: #ccc;
    border: 1px solid #555; border-radius: 6px;
}
QMenu {
    background-color: #3c3c3c; color: #ccc; border: 1px solid #555;
}
QMenu::item:selected { background-color: #409eff; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("办公工具箱")
        self.setWindowIcon(QIcon(_get_icon_path()))
        self.resize(900, 650)
        self.setMinimumSize(700, 500)
        self._center()
        self._build_ui()
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

    def _center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        geo = self.frameGeometry()
        geo.moveCenter(screen.center())
        self.move(geo.topLeft())

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- 标题栏 ----
        title_bar = QWidget()
        title_bar.setStyleSheet(
            "background-color: #ffffff; border-bottom: 1px solid #e4e7ed;"
        )
        tb_layout = QHBoxLayout(title_bar)
        tb_layout.setContentsMargins(16, 8, 16, 8)

        title = QLabel("📄 办公工具箱")
        title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #303133; border: none;"
        )
        tb_layout.addWidget(title)

        # 导航按钮
        nav_style = (
            "QPushButton { background: transparent; border: 1px solid #dcdfe6;"
            " border-radius: 4px; font-size: 12px; color: #606266; padding: 2px 10px; }"
            "QPushButton:hover { color: #409eff; border-color: #c6e2ff;"
            " background-color: #ecf5ff; }"
            "QPushButton:checked { background: #409eff; color: #ffffff; border-color: #409eff; }"
        )
        self.btn_nav_edit = QPushButton("PDF 编辑")
        self.btn_nav_edit.setCheckable(True)
        self.btn_nav_edit.setChecked(True)
        self.btn_nav_edit.setStyleSheet(nav_style)
        self.btn_nav_edit.clicked.connect(lambda: self._switch_page(0))

        self.btn_nav_ocr = QPushButton("OCR 识别")
        self.btn_nav_ocr.setCheckable(True)
        self.btn_nav_ocr.setStyleSheet(nav_style)
        self.btn_nav_ocr.clicked.connect(lambda: self._switch_page(1))

        tb_layout.addWidget(self.btn_nav_edit)
        tb_layout.addWidget(self.btn_nav_ocr)
        tb_layout.addStretch()

        self.btn_settings = QPushButton("⚙")
        self.btn_settings.setFixedSize(32, 28)
        self.btn_settings.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #dcdfe6;"
            " border-radius: 4px; font-size: 16px; color: #606266; padding: 0px; }"
            "QPushButton:hover { color: #409eff; border-color: #c6e2ff;"
            " background-color: #ecf5ff; }"
        )
        self.btn_settings.clicked.connect(lambda: self._switch_page(2))
        tb_layout.addWidget(self.btn_settings)

        layout.addWidget(title_bar)

        # ---- 页面切换 ----
        self.stack = QStackedWidget()
        self.edit_page = EditPage()
        self.ocr_page = OcrPage(self)
        self.settings_page = SettingsPage()
        self.stack.addWidget(self.edit_page)     # index 0
        self.stack.addWidget(self.ocr_page)      # index 1
        self.stack.addWidget(self.settings_page)  # index 2
        layout.addWidget(self.stack, stretch=1)

        # ---- 底部状态栏 ----
        status_bar = QWidget()
        status_bar.setStyleSheet(
            "background-color: #ffffff; border-top: 1px solid #e4e7ed;"
        )
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(16, 6, 16, 6)
        self.status_label = QLabel("就绪", objectName="statusLabel")
        init_status(self.status_label.setText)
        sb_layout.addWidget(self.status_label)
        layout.addWidget(status_bar)

    def _switch_page(self, index):
        self.stack.setCurrentIndex(index)
        self.btn_nav_edit.setChecked(index == 0)
        self.btn_nav_ocr.setChecked(index == 1)


def _get_icon_path():
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent
    return str(base / "icon.ico")


if __name__ == "__main__":
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("办公工具箱")
    app = QApplication(sys.argv)
    app.setApplicationName("办公工具箱")

    settings = QSettings("办公工具箱", "办公工具箱")
    theme = settings.value("app/theme", "light")
    app.setStyleSheet(DARK_STYLE if theme == "dark" else BASE_STYLE)

    font_size_map = {"小": 9, "中": 10, "大": 11}
    font_size_label = settings.value("app/font_size", "中")
    font = app.font()
    font.setFamilies(["Microsoft YaHei", "Segoe UI", "PingFang SC", "sans-serif"])
    font.setPointSize(font_size_map.get(font_size_label, 10))
    app.setFont(font)

    app.setWindowIcon(QIcon(_get_icon_path()))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
