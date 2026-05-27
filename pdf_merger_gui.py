"""
PDF 合并工具 - PySide6 现代化界面
- 拖拽文件到窗口添加
- 列表中拖拽调整顺序
- 支持 PDF 和图片文件
"""
import os, sys
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QProgressBar,
    QFileDialog, QMessageBox, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, QMimeData, QUrl, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont, QColor, QPalette, QIcon

SUPPORTED_EXTS = {'.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}

STYLE = """
QMainWindow {
    background-color: #f5f6fa;
}
QFrame#dropZone {
    background-color: #ffffff;
    border: 2px dashed #c0c4cc;
    border-radius: 10px;
}
QFrame#dropZone:hover {
    border-color: #409eff;
    background-color: #ecf5ff;
}
QLabel#dropLabel {
    color: #909399;
    font-size: 14px;
}
QListWidget {
    background-color: #ffffff;
    border: 1px solid #e4e7ed;
    border-radius: 6px;
    padding: 4px;
    outline: none;
    font-size: 13px;
}
QListWidget::item {
    background-color: #ffffff;
    border: 1px solid #ebeef5;
    border-radius: 5px;
    padding: 8px 12px;
    margin: 2px 0px;
    color: #303133;
}
QListWidget::item:selected {
    background-color: #ecf5ff;
    border-color: #409eff;
    color: #409eff;
}
QPushButton {
    background-color: #ffffff;
    border: 1px solid #dcdfe6;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 13px;
    color: #606266;
}
QPushButton:hover {
    color: #409eff;
    border-color: #c6e2ff;
    background-color: #ecf5ff;
}
QPushButton:pressed {
    color: #3a8ee6;
    border-color: #3a8ee6;
}
QPushButton#mergeBtn {
    background-color: #409eff;
    color: #ffffff;
    border: none;
    font-weight: bold;
    padding: 10px 32px;
}
QPushButton#mergeBtn:hover {
    background-color: #66b1ff;
}
QPushButton#mergeBtn:pressed {
    background-color: #3a8ee6;
}
QPushButton#mergeBtn:disabled {
    background-color: #a0cfff;
}
QProgressBar {
    border: none;
    border-radius: 4px;
    background-color: #e4e7ed;
    height: 6px;
    text-align: center;
    font-size: 12px;
}
QProgressBar::chunk {
    background-color: #409eff;
    border-radius: 4px;
}
QLabel#statusLabel {
    color: #909399;
    font-size: 12px;
}
"""


class MergeWorker(QThread):
    """后台合并线程"""
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, files, output_path):
        super().__init__()
        self.files = files
        self.output_path = output_path

    def run(self):
        try:
            writer = PdfWriter()
            total = len(self.files)

            for i, (_, fpath) in enumerate(self.files):
                ext = os.path.splitext(fpath)[1].lower()

                if ext == '.pdf':
                    reader = PdfReader(fpath)
                    for page in reader.pages:
                        writer.add_page(page)
                else:
                    img = Image.open(fpath)
                    if img.mode == 'RGBA':
                        img = img.convert('RGB')
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    tmp = fpath + '.tmp.pdf'
                    img.save(tmp)
                    reader = PdfReader(tmp)
                    for page in reader.pages:
                        writer.add_page(page)
                    os.remove(tmp)

                self.progress.emit(int((i + 1) / total * 100))

            writer.write(self.output_path)
            writer.close()
            self.finished.emit(self.output_path)
        except Exception as e:
            self.error.emit(str(e))


class DropListWidget(QListWidget):
    """支持从外部拖入文件的列表控件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls()]
            # 通过父窗口添加文件
            main_win = self.window()
            if isinstance(main_win, MainWindow):
                main_win.add_files(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PDF 合并工具')
        self.resize(680, 560)
        self.setMinimumSize(500, 400)
        self._center()
        self.files = []  # [(name, full_path), ...]
        self._build_ui()

    def _center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        geo = self.frameGeometry()
        geo.moveCenter(screen.center())
        self.move(geo.topLeft())

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        # ---- 顶部标题 ----
        title = QLabel('📄 PDF 合并工具')
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet('color: #303133; padding-bottom: 4px;')
        layout.addWidget(title)

        # ---- 拖拽区域 ----
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName('dropZone')
        self.drop_zone.setFixedHeight(100)
        self.drop_zone.setAcceptDrops(True)
        dz_layout = QVBoxLayout(self.drop_zone)
        dz_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.drop_label = QLabel('拖拽 PDF / 图片文件到此处\n或点击下方按钮选择文件')
        self.drop_label.setObjectName('dropLabel')
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        dz_layout.addWidget(self.drop_label)
        layout.addWidget(self.drop_zone)

        # 拖拽区域的事件
        self.drop_zone.dragEnterEvent = self._zone_drag_enter
        self.drop_zone.dropEvent = self._zone_drop

        # ---- 按钮行 ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_add = QPushButton('📂 选择文件')
        self.btn_add.clicked.connect(self._browse_files)
        self.btn_folder = QPushButton('📁 添加文件夹')
        self.btn_folder.clicked.connect(self._add_folder)

        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_folder)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ---- 文件列表 ----
        list_label = QLabel('文件列表（拖拽条目可调整顺序）')
        list_label.setStyleSheet('color: #606266; font-size: 13px; font-weight: bold;')
        layout.addWidget(list_label)

        self.list_widget = DropListWidget()
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(self.list_widget, stretch=1)

        # ---- 操作按钮 ----
        op_row = QHBoxLayout()
        op_row.setSpacing(6)

        self.btn_up = QPushButton('⬆ 上移')
        self.btn_up.clicked.connect(self._move_up)
        self.btn_down = QPushButton('⬇ 下移')
        self.btn_down.clicked.connect(self._move_down)
        self.btn_remove = QPushButton('✕ 移除')
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear = QPushButton('清空')
        self.btn_clear.clicked.connect(self._clear_all)

        op_row.addWidget(self.btn_up)
        op_row.addWidget(self.btn_down)
        op_row.addWidget(self.btn_remove)
        op_row.addWidget(self.btn_clear)
        op_row.addStretch()

        self.btn_merge = QPushButton('合并导出 PDF')
        self.btn_merge.setObjectName('mergeBtn')
        self.btn_merge.clicked.connect(self._start_merge)
        op_row.addWidget(self.btn_merge)

        layout.addLayout(op_row)

        # ---- 进度条 ----
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(6)
        layout.addWidget(self.progress_bar)

        # ---- 状态栏 ----
        self.status_label = QLabel('就绪')
        self.status_label.setObjectName('statusLabel')
        layout.addWidget(self.status_label)

    # ==================== 拖拽区域事件 ====================

    def _zone_drag_enter(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drop_zone.setStyleSheet(
                '#dropZone { background-color: #ecf5ff; border: 2px dashed #409eff; border-radius: 10px; }'
            )

    def _zone_drop(self, event: QDropEvent):
        self.drop_zone.setStyleSheet(
            '#dropZone { background-color: #ffffff; border: 2px dashed #c0c4cc; border-radius: 10px; }'
            '#dropZone:hover { border-color: #409eff; background-color: #ecf5ff; }'
        )
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls()]
            self.add_files(paths)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.drop_zone.setStyleSheet(
            '#dropZone { background-color: #ffffff; border: 2px dashed #c0c4cc; border-radius: 10px; }'
            '#dropZone:hover { border-color: #409eff; background-color: #ecf5ff; }'
        )

    # ==================== 文件操作 ====================

    def add_files(self, paths):
        added = 0
        for p in paths:
            p = str(p).strip('"').strip('{').strip('}')
            ext = os.path.splitext(p)[1].lower()
            if ext in SUPPORTED_EXTS and os.path.isfile(p):
                if not any(p == fp for _, fp in self.files):
                    fname = os.path.basename(p)
                    self.files.append((fname, p))
                    item = QListWidgetItem(fname)
                    item.setToolTip(p)
                    self.list_widget.addItem(item)
                    added += 1
        if added:
            self._set_status(f'已添加 {added} 个文件，共 {len(self.files)} 个')

    def _on_rows_moved(self, parent, start, end, dest, row):
        """列表拖拽排序后同步 files 列表"""
        # 重建 files 顺序以匹配 list_widget
        new_files = []
        for i in range(self.list_widget.count()):
            fname = self.list_widget.item(i).text()
            for name, path in self.files:
                if name == fname and not any(path == p for _, p in new_files):
                    new_files.append((name, path))
                    break
        # 补充未匹配的（理论上不会发生）
        for n, p in self.files:
            if not any(p == fp for _, fp in new_files):
                new_files.append((n, p))
        self.files = new_files

    def _browse_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, '选择文件', '',
            '支持的文件 (*.pdf *.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp);;PDF (*.pdf);;图片 (*.jpg *.jpeg *.png *.bmp)'
        )
        if paths:
            self.add_files(paths)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择文件夹')
        if not folder:
            return
        files = []
        for f in sorted(os.listdir(folder)):
            ext = os.path.splitext(f)[1].lower()
            if ext in SUPPORTED_EXTS:
                files.append(os.path.join(folder, f))
        if files:
            self.add_files(files)
        else:
            QMessageBox.information(self, '提示', '该文件夹内没有支持的 PDF 或图片文件。')

    def _remove_selected(self):
        rows = sorted([self.list_widget.row(item) for item in self.list_widget.selectedItems()], reverse=True)
        for row in rows:
            self.list_widget.takeItem(row)
            del self.files[row]
        self._set_status(f'剩余 {len(self.files)} 个文件')

    def _clear_all(self):
        self.list_widget.clear()
        self.files.clear()
        self._set_status('列表已清空')

    # ==================== 排序操作 ====================

    def _move_up(self):
        row = self.list_widget.currentRow()
        if row <= 0:
            return
        self._swap(row, row - 1)
        self.list_widget.setCurrentRow(row - 1)

    def _move_down(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= self.list_widget.count() - 1:
            return
        self._swap(row, row + 1)
        self.list_widget.setCurrentRow(row + 1)

    def _swap(self, a, b):
        self.files[a], self.files[b] = self.files[b], self.files[a]
        item_a = self.list_widget.takeItem(a)
        item_b = self.list_widget.takeItem(b - 1 if b > a else b)
        self.list_widget.insertItem(b, item_a)
        self.list_widget.insertItem(a, item_b)

    # ==================== 合并 ====================

    def _start_merge(self):
        if not self.files:
            QMessageBox.warning(self, '提示', '请先添加要合并的文件。')
            return

        output, _ = QFileDialog.getSaveFileName(
            self, '保存合并后的 PDF', 'merged_output.pdf',
            'PDF 文件 (*.pdf)'
        )
        if not output:
            return

        self.btn_merge.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self._set_status('正在合并...')

        self.worker = MergeWorker(self.files, output)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_done)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, pct):
        self.progress_bar.setValue(pct)
        self._set_status(f'合并中... {pct}%')

    def _on_done(self, output):
        self.progress_bar.setVisible(False)
        self.btn_merge.setEnabled(True)
        self._set_status('合并完成')

        reply = QMessageBox.question(
            self, '完成',
            f'PDF 已导出到：\n{output}\n\n是否打开所在文件夹？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            os.startfile(os.path.dirname(output))

    def _on_error(self, msg):
        self.progress_bar.setVisible(False)
        self.btn_merge.setEnabled(True)
        self._set_status('合并失败')
        QMessageBox.critical(self, '错误', f'合并过程中出错：\n{msg}')

    def _set_status(self, text):
        self.status_label.setText(text)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    font = app.font()
    font.setFamilies(['Microsoft YaHei', 'Segoe UI', 'PingFang SC', 'sans-serif'])
    font.setPointSize(10)
    app.setFont(font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
