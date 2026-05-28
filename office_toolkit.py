"""
办公工具箱 - PySide6 现代化界面
- 编辑：预览、拖拽排序、插入、删除、导出 PDF 页面（支持 PDF + 图片）
"""

import ctypes
import io
import logging
import os
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
from pypdf import PdfReader, PdfWriter
from PySide6.QtCore import QMimeData, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QIcon,
    QImage,
    QMouseEvent,
    QPainter,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logging.getLogger("pypdf").setLevel(logging.ERROR)

SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp"}
THUMB_SIZE = 200

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


# ==================== 数据模型 ====================


class PageEntry:
    """PDF 编辑中的一页"""

    def __init__(self, entry_type, source_path, page_index=0):
        self.entry_type = entry_type  # 'pdf' or 'image'
        self.source_path = source_path
        self.page_index = page_index  # 源文件中的页码索引
        self._pixmap = None

    @property
    def label(self):
        name = os.path.basename(self.source_path)
        if self.entry_type == "pdf":
            return f"{name} - 第{self.page_index + 1}页"
        return f"{name}"

    def render_pixmap(self, size=THUMB_SIZE):
        if self._pixmap:
            return self._pixmap
        try:
            if self.entry_type == "pdf":
                doc = fitz.open(self.source_path)
                page = doc[self.page_index]
                zoom = size / page.rect.width
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                img = QImage(
                    pix.samples,
                    pix.width,
                    pix.height,
                    pix.stride,
                    QImage.Format.Format_RGB888,
                )
                self._pixmap = QPixmap.fromImage(img)
                doc.close()
            else:  # image
                self._pixmap = QPixmap(self.source_path)
                if self._pixmap.width() > size:
                    self._pixmap = self._pixmap.scaledToWidth(
                        size, Qt.TransformationMode.SmoothTransformation
                    )
            return self._pixmap
        except Exception:
            return QPixmap()


# ==================== 缩略图控件 ====================


class ThumbnailWidget(QFrame):
    clicked = Signal(int)
    insert_requested = Signal(int)  # 在指定位置前插入

    def __init__(self, page_entry, page_num, parent=None):
        super().__init__(parent)
        self.page_entry = page_entry
        self.page_num = page_num
        self._selected = False
        self._drag_start_pos = None
        self._build()

    def _build(self):
        img_h = int(THUMB_SIZE * 1.414)
        self.setFixedSize(THUMB_SIZE + 24, img_h + 42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(6)

        # 缩略图
        self.img_label = QLabel()
        self.img_label.setFixedSize(THUMB_SIZE, img_h)
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setScaledContents(True)
        layout.addWidget(self.img_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # 页码
        self.num_label = QLabel(f"第 {self.page_num + 1} 页")
        self.num_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.num_label.setStyleSheet("color: #606266; font-size: 11px;")
        layout.addWidget(self.num_label)

        self._update_style()

    def set_pixmap(self, pixmap):
        self.img_label.setPixmap(pixmap)

    def set_selected(self, val):
        self._selected = val
        self._update_style()

    @property
    def selected(self):
        return self._selected

    def _update_style(self):
        if self._selected:
            self.setStyleSheet(
                "ThumbnailWidget { background-color: #ecf5ff; border: 2px solid #409eff; "
                "border-radius: 8px; }"
            )
        else:
            self.setStyleSheet(
                "ThumbnailWidget { background-color: #ffffff; border: 1px solid #ebeef5; "
                "border-radius: 8px; }"
                "ThumbnailWidget:hover { border-color: #c6e2ff; }"
            )

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            self.clicked.emit(self.page_num)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_start_pos is None:
            return super().mouseMoveEvent(event)
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(event)
        pos = event.position().toPoint()
        if (pos - self._drag_start_pos).manhattanLength() < 10:
            return super().mouseMoveEvent(event)

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-pdf-page-index", str(self.page_num).encode())
        drag.setMimeData(mime)

        pixmap = self.grab()
        scaled = pixmap.scaled(
            pixmap.width() * 2 // 3,
            pixmap.height() * 2 // 3,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter = QPainter(scaled)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_DestinationIn
        )
        painter.fillRect(scaled.rect(), QColor(0, 0, 0, 150))
        painter.end()
        drag.setPixmap(scaled)
        drag.setHotSpot(pos)

        self._drag_start_pos = None
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction(
            "在此页前插入", lambda: self.insert_requested.emit(self.page_num)
        )
        menu.addAction(
            "在此页后插入", lambda: self.insert_requested.emit(self.page_num + 1)
        )
        menu.exec(event.globalPos())


# ==================== 工作线程 ====================


class ExportWorker(QThread):
    """后台导出编辑后的 PDF"""

    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, pages, output_path):
        super().__init__()
        self.pages = pages
        self.output_path = output_path

    def run(self):
        try:
            writer = PdfWriter()
            total = len(self.pages)
            for i, entry in enumerate(self.pages):
                if entry.entry_type == "pdf":
                    reader = PdfReader(entry.source_path)
                    writer.add_page(reader.pages[entry.page_index])
                else:
                    img = Image.open(entry.source_path)
                    if img.mode == "RGBA":
                        img = img.convert("RGB")
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    tmp = entry.source_path + ".tmp.pdf"
                    img.save(tmp)
                    for page in PdfReader(tmp).pages:
                        writer.add_page(page)
                    os.remove(tmp)
                self.progress.emit(int((i + 1) / total * 100))
            writer.write(self.output_path)
            writer.close()
            self.finished.emit(self.output_path)
        except Exception as e:
            self.error.emit(str(e))


# ==================== 编辑页面 ====================


class EditPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pages = []  # list[PageEntry]
        self.selected_indices = set()
        self._last_cols = 0
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._on_resize_timeout)
        self._build_ui()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.pages:
            self._resize_timer.start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        # 拖拽区域 + 按钮
        top_area = QHBoxLayout()
        self.drop_zone = QFrame(objectName="dropZone")
        self.drop_zone.setFixedHeight(70)
        self.drop_zone.setAcceptDrops(True)
        dz_layout = QVBoxLayout(self.drop_zone)
        dz_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label = QLabel(
            "拖拽 PDF / 图片文件到此处\n或点击按钮选择文件",
            objectName="dropLabel",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        dz_layout.addWidget(self.drop_label)
        self.drop_zone.dragEnterEvent = self._zone_drag_enter
        self.drop_zone.dropEvent = self._zone_drop
        top_area.addWidget(self.drop_zone, stretch=1)

        btn_vert = QVBoxLayout()
        btn_vert.setSpacing(4)
        self.btn_add = QPushButton("📂 添加文件")
        self.btn_add.clicked.connect(self._add_files)
        self.btn_clear = QPushButton("🗑 清空")
        self.btn_clear.clicked.connect(self._clear_document)
        self.btn_clear.setEnabled(False)
        btn_vert.addWidget(self.btn_add)
        btn_vert.addWidget(self.btn_clear)
        top_area.addLayout(btn_vert)
        layout.addLayout(top_area)

        # 缩略图网格
        thumb_label = QLabel("页面预览（点击选中，右键插入）")
        thumb_label.setStyleSheet("color: #606266; font-size: 13px; font-weight: bold;")
        layout.addWidget(thumb_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.thumb_container = QWidget()
        self.thumb_container.setAcceptDrops(True)
        self.thumb_container.dragEnterEvent = self._thumb_drag_enter
        self.thumb_container.dragMoveEvent = self._thumb_drag_move
        self.thumb_container.dragLeaveEvent = self._thumb_drag_leave
        self.thumb_container.dropEvent = self._thumb_drop
        self.thumb_layout = QGridLayout(self.thumb_container)
        self.thumb_layout.setSpacing(16)
        self.thumb_layout.setContentsMargins(8, 8, 8, 8)
        self.thumb_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.scroll_area.setWidget(self.thumb_container)

        # 空状态
        self.empty_label = QLabel(
            "拖拽文件到此处或点击「添加文件」开始", alignment=Qt.AlignmentFlag.AlignCenter
        )
        self.empty_label.setStyleSheet(
            "color: #c0c4cc; font-size: 16px; padding: 60px;"
        )
        self.thumb_layout.addWidget(self.empty_label, 0, 0, 1, 4)

        # 拖拽排序指示线
        self.drop_indicator = QFrame(self.thumb_container)
        self.drop_indicator.setFixedWidth(3)
        self.drop_indicator.setStyleSheet(
            "background-color: #409eff; border-radius: 1px;"
        )
        self.drop_indicator.hide()
        self._drop_target_index = -1

        layout.addWidget(self.scroll_area, stretch=1)

        # 操作按钮
        op_row = QHBoxLayout()
        op_row.setSpacing(6)

        self.btn_delete = QPushButton("🗑 删除选中页")
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_delete.setEnabled(False)
        self.btn_clear_sel = QPushButton("取消选中")
        self.btn_clear_sel.clicked.connect(self._clear_selection)
        self.btn_clear_sel.setEnabled(False)

        op_row.addWidget(self.btn_delete)
        op_row.addWidget(self.btn_clear_sel)
        op_row.addStretch()

        self.btn_export = QPushButton("导出 PDF", objectName="primaryBtn")
        self.btn_export.clicked.connect(self._export_pdf)
        self.btn_export.setEnabled(False)
        op_row.addWidget(self.btn_export)
        layout.addLayout(op_row)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(6)
        layout.addWidget(self.progress_bar)

    # === 拖拽 ===
    def _zone_drag_enter(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            for url in urls:
                if os.path.splitext(url.toLocalFile())[1].lower() in SUPPORTED_EXTS:
                    event.acceptProposedAction()
                    self.drop_zone.setStyleSheet(
                        "#dropZone { background-color: #ecf5ff; border: 2px dashed #409eff; border-radius: 10px; }"
                    )
                    return

    def _zone_drop(self, event: QDropEvent):
        self.drop_zone.setStyleSheet("")
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls()]
            if paths:
                self._insert_paths(paths, len(self.pages))
            event.acceptProposedAction()

    # === 缩略图拖拽排序 ===
    def _thumb_drag_enter(self, event: QDragEnterEvent):
        if event.mimeData().hasFormat("application/x-pdf-page-index"):
            event.acceptProposedAction()

    def _thumb_drag_move(self, event: QDragMoveEvent):
        if not event.mimeData().hasFormat("application/x-pdf-page-index"):
            return
        self._update_drop_indicator(event)
        event.acceptProposedAction()

    def _thumb_drag_leave(self, event):
        self.drop_indicator.hide()

    def _thumb_drop(self, event: QDropEvent):
        self.drop_indicator.hide()
        if not event.mimeData().hasFormat("application/x-pdf-page-index"):
            return
        source_idx = int(
            event.mimeData().data("application/x-pdf-page-index").data().decode()
        )
        target = self._drop_target_index
        if target < 0 or source_idx == target or source_idx == target - 1:
            return
        entry = self.pages.pop(source_idx)
        if source_idx < target:
            target -= 1
        self.pages.insert(target, entry)
        new_selected = set()
        for idx in self.selected_indices:
            if idx == source_idx:
                new_selected.add(target)
            elif source_idx < target:
                if idx < source_idx:
                    new_selected.add(idx)
                elif idx <= target:
                    new_selected.add(idx - 1)
            else:
                if idx < target:
                    new_selected.add(idx)
                elif idx < source_idx:
                    new_selected.add(idx + 1)
        new_selected.add(target)
        self.selected_indices = new_selected
        self._refresh_thumbnails()
        event.acceptProposedAction()

    def _update_drop_indicator(self, event):
        pos = event.position().toPoint()

        # Collect all thumbnails sorted by page order
        thumbs = []
        for i in range(self.thumb_layout.count()):
            w = self.thumb_layout.itemAt(i).widget()
            if isinstance(w, ThumbnailWidget):
                thumbs.append(w)
        thumbs.sort(key=lambda w: w.page_num)

        target = len(self.pages)
        for w in thumbs:
            geo = w.geometry()
            if pos.y() < geo.bottom():
                if pos.y() >= geo.top():
                    # Same row: left half -> insert before this page; right half -> keep going
                    if pos.x() < geo.center().x():
                        target = w.page_num
                        break
                else:
                    # Between rows (above this widget's row)
                    target = w.page_num
                    break

        self._drop_target_index = target

        if target < len(self.pages):
            for w in thumbs:
                if w.page_num == target:
                    self.drop_indicator.setGeometry(
                        w.geometry().left() - 2,
                        w.geometry().top(),
                        3,
                        w.geometry().height(),
                    )
                    break
        else:
            last = thumbs[-1] if thumbs else None
            if last:
                self.drop_indicator.setGeometry(
                    last.geometry().right() + 1,
                    last.geometry().top(),
                    3,
                    last.geometry().height(),
                )
        self.drop_indicator.show()
        self.drop_indicator.raise_()

    # === 添加文件 ===
    def _add_files(self):
        """添加文件（追加到末尾）"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择文件", "",
            "支持的文件 (*.pdf *.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp);;PDF (*.pdf);;图片 (*.jpg *.jpeg *.png *.bmp)"
        )
        if paths:
            self._insert_paths(paths, len(self.pages))

    def _clear_document(self):
        self.pages.clear()
        self.selected_indices.clear()
        self._refresh_thumbnails()
        self.btn_export.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self.btn_clear_sel.setEnabled(False)
        self.empty_label.setVisible(True)
        self.drop_label.setText("拖拽 PDF / 图片文件到此处\n或点击按钮选择文件")
        MainWindow.set_status("页面已清空")

    # === 缩略图 ===
    def _on_resize_timeout(self):
        cols = max(1, (self.scroll_area.viewport().width() - 20) // (THUMB_SIZE + 30))
        if cols != self._last_cols:
            self._last_cols = cols
            self._refresh_thumbnails()

    def _refresh_thumbnails(self):
        # 清除旧控件
        while self.thumb_layout.count():
            item = self.thumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.pages:
            self.empty_label = QLabel(
                "拖拽文件到此处或点击「添加文件」开始", alignment=Qt.AlignmentFlag.AlignCenter
            )
            self.empty_label.setStyleSheet(
                "color: #c0c4cc; font-size: 16px; padding: 60px;"
            )
            self.thumb_layout.addWidget(self.empty_label, 0, 0, 1, 4)
            return

        cols = max(1, (self.scroll_area.viewport().width() - 20) // (THUMB_SIZE + 30))
        self._last_cols = cols
        for i, entry in enumerate(self.pages):
            thumb = ThumbnailWidget(entry, i)
            thumb.clicked.connect(self._on_thumb_clicked)
            thumb.insert_requested.connect(self._on_insert_requested)

            # 异步渲染
            pixmap = entry.render_pixmap()
            thumb.set_pixmap(pixmap)

            if i in self.selected_indices:
                thumb.set_selected(True)

            row, col = i // cols, i % cols
            self.thumb_layout.addWidget(thumb, row, col)

        MainWindow.set_status(f"共 {len(self.pages)} 页")

    def _on_thumb_clicked(self, page_num):
        if page_num in self.selected_indices:
            self.selected_indices.discard(page_num)
        else:
            self.selected_indices.add(page_num)

        self._update_selection_visual()
        self.btn_delete.setEnabled(len(self.selected_indices) > 0)
        self.btn_clear_sel.setEnabled(len(self.selected_indices) > 0)
        MainWindow.set_status(f"已选中 {len(self.selected_indices)} 页")

    def _update_selection_visual(self):
        for i in range(self.thumb_layout.count()):
            w = self.thumb_layout.itemAt(i).widget()
            if isinstance(w, ThumbnailWidget):
                w.set_selected(w.page_num in self.selected_indices)

    def _clear_selection(self):
        self.selected_indices.clear()
        self._update_selection_visual()
        self.btn_delete.setEnabled(False)
        self.btn_clear_sel.setEnabled(False)
        MainWindow.set_status(f"共 {len(self.pages)} 页")

    # === 删除 ===
    def _delete_selected(self):
        if not self.selected_indices:
            return
        indices = sorted(self.selected_indices, reverse=True)
        for i in indices:
            if 0 <= i < len(self.pages):
                del self.pages[i]
        self.selected_indices.clear()
        self._refresh_thumbnails()
        self.btn_delete.setEnabled(False)
        self.btn_clear_sel.setEnabled(False)
        if not self.pages:
            self.btn_export.setEnabled(False)
            self.btn_clear.setEnabled(False)
            self.empty_label.setVisible(True)
            self.drop_label.setText("拖拽 PDF / 图片文件到此处\n或点击按钮选择文件")

    # === 插入 ===
    def _on_insert_requested(self, position):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择要插入的文件",
            "",
            "支持的文件 (*.pdf *.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp);;PDF (*.pdf);;图片 (*.jpg *.jpeg *.png *.bmp)",
        )
        if paths:
            self._insert_paths(paths, position)

    def _insert_paths(self, paths, position):
        new_entries = []
        for p in paths:
            p = str(p)
            ext = os.path.splitext(p)[1].lower()
            if ext not in SUPPORTED_EXTS or not os.path.isfile(p):
                continue
            if ext == ".pdf":
                try:
                    doc = fitz.open(p)
                    count = doc.page_count
                    doc.close()
                    for pi in range(count):
                        new_entries.append(PageEntry("pdf", p, pi))
                except Exception:
                    new_entries.append(PageEntry("image", p, 0))
            else:
                new_entries.append(PageEntry("image", p, 0))

        was_empty = not self.pages
        position = min(position, len(self.pages))
        self.pages[position:position] = new_entries
        self._refresh_thumbnails()
        if was_empty and self.pages:
            self.empty_label.setVisible(False)
            self.btn_export.setEnabled(True)
            self.btn_clear.setEnabled(True)
            self.drop_label.setText(
                f"已加载 {len(self.pages)} 页\n可继续拖入文件追加"
            )
        MainWindow.set_status(f"已插入 {len(new_entries)} 页，共 {len(self.pages)} 页")

    # === 导出 ===
    def _export_pdf(self):
        if not self.pages:
            QMessageBox.warning(self, "提示", "没有页面可导出。")
            return
        # Default filename based on original PDF name
        src_name = (
            os.path.basename(self.pages[0].source_path)
            if self.pages
            else "edited_output.pdf"
        )
        default_name = os.path.splitext(src_name)[0] + "_编辑.pdf"
        output, _ = QFileDialog.getSaveFileName(
            self, "导出编辑后的 PDF", default_name, "PDF 文件 (*.pdf)"
        )
        if not output:
            return

        self.btn_export.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        MainWindow.set_status("正在导出...")

        self.worker = ExportWorker(self.pages, output)
        self.worker.progress.connect(
            lambda v: (
                self.progress_bar.setValue(v),
                MainWindow.set_status(f"导出中... {v}%"),
            )
        )
        self.worker.finished.connect(self._on_export_done)
        self.worker.error.connect(self._on_export_error)
        self.worker.start()

    def _on_export_done(self, output):
        self.progress_bar.setVisible(False)
        self.btn_export.setEnabled(True)
        MainWindow.set_status("导出完成")
        if (
            QMessageBox.question(
                self, "完成", f"PDF 已导出到：\n{output}\n\n是否打开文件？"
            )
            == QMessageBox.StandardButton.Yes
        ):
            os.startfile(output)

    def _on_export_error(self, msg):
        self.progress_bar.setVisible(False)
        self.btn_export.setEnabled(True)
        MainWindow.set_status("导出失败")
        QMessageBox.critical(self, "错误", f"导出过程中出错：\n{msg}")


# ==================== 主窗口 ====================


class MainWindow(QMainWindow):
    _status_label = None

    @staticmethod
    def set_status(text):
        if MainWindow._status_label:
            MainWindow._status_label.setText(text)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("办公工具箱")
        self.setWindowIcon(QIcon(_get_icon_path()))
        self.resize(900, 650)
        self.setMinimumSize(700, 500)
        self._center()
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
        tb_layout.addStretch()
        layout.addWidget(title_bar)

        # ---- 编辑页面 ----
        self.edit_page = EditPage()
        layout.addWidget(self.edit_page, stretch=1)

        # ---- 底部状态栏 ----
        status_bar = QWidget()
        status_bar.setStyleSheet(
            "background-color: #ffffff; border-top: 1px solid #e4e7ed;"
        )
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(16, 6, 16, 6)
        self.status_label = QLabel("就绪", objectName="statusLabel")
        MainWindow._status_label = self.status_label
        sb_layout.addWidget(self.status_label)
        layout.addWidget(status_bar)


# ==================== 入口 ====================


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
    icon_path = _get_icon_path()
    app_icon = QIcon(icon_path)
    app.setWindowIcon(app_icon)
    app.setStyleSheet(BASE_STYLE)
    font = app.font()
    font.setFamilies(["Microsoft YaHei", "Segoe UI", "PingFang SC", "sans-serif"])
    font.setPointSize(10)
    app.setFont(font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
