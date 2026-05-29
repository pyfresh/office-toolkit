# 合并功能融入编辑模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除独立的合并模块（MergePage/MergeWorker/DropListWidget/导航栏），增强编辑模块使其从零开始接受多文件拖入，单一页面完成所有合并和编辑操作。

**Architecture:** MainWindow 直接嵌入 EditPage，无需 QStackedWidget 和导航栏。EditPage 的 drop zone 和「添加文件」按钮统一接受所有支持的格式（PDF + 图片），不再要求先打开 PDF。

**Tech Stack:** PySide6, PyMuPDF, pypdf, Pillow

---

### Task 1: 删除合并模块相关代码

**Files:**
- Modify: `C:\Users\Litbug\Desktop\办公工具箱\office_toolkit.py`

删除整个 `MergeWorker` 类（约 lines 281-316）、`DropListWidget` 类（约 lines 361-383）、`MergePage` 类（约 lines 389-614）。

- [ ] **Step 1: 删除 MergeWorker 类**

删除以下代码块:
```python
class MergeWorker(QThread):
    progress = Signal(int)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, files, output_path):
        ...
```

- [ ] **Step 2: 删除 DropListWidget 类**

删除以下代码块:
```python
class DropListWidget(QListWidget):
    def __init__(self, parent=None):
        ...
```

- [ ] **Step 3: 删除 MergePage 类**

删除整个 `MergePage` 类（约 226 行）。

- [ ] **Step 4: 删除未使用的 imports**

从文件顶部的 imports 中移除不再需要的引用。检查后 `QListWidget` 和 `QListWidgetItem` 不再使用，可删除。

### Task 2: 简化 MainWindow

**Files:**
- Modify: `C:\Users\Litbug\Desktop\办公工具箱\office_toolkit.py`

移除导航栏、QStackedWidget，直接嵌入 EditPage。

- [ ] **Step 1: 重写 MainWindow._build_ui**

将当前 `_build_ui`（约 lines 1112-1168）替换为:

```python
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
```

- [ ] **Step 2: 删除 MainWindow 中不再需要的属性和方法**

删除:
- `self.stack` 相关代码
- `self.merge_page` 相关代码
- `self.btn_nav_merge`, `self.btn_nav_edit` 相关代码
- `_switch_page` 方法
- `_nav_style` 方法
- `add_merge_files` 方法
- `from PySide6.QtWidgets import ... QStackedWidget` 中的 `QStackedWidget`（如果不再使用）

- [ ] **Step 3: 清理 _center 方法**

`_center` 方法保持不变，无需修改。

### Task 3: 改造 EditPage 支持从零开始

**Files:**
- Modify: `C:\Users\Litbug\Desktop\办公工具箱\office_toolkit.py`

- [ ] **Step 1: 重写 EditPage._build_ui 中的 UI 文案和按钮**

将 `_build_ui` 方法中的相关部分修改为:

```python
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
```

_说明：将 "打开 PDF" 改名 "添加文件"，"插入文件" 按钮移除（可通过右键菜单插入），新增 "清空" 按钮。_

- [ ] **Step 2: 重写 _zone_drop 支持所有文件类型初始化**

```python
def _zone_drop(self, event: QDropEvent):
    self.drop_zone.setStyleSheet("")
    if event.mimeData().hasUrls():
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        if paths:
            self._insert_paths(paths, len(self.pages))
        event.acceptProposedAction()
```

_说明：去掉 "先判断是否 PDF" 的逻辑，统一走 `_insert_paths`。空列表时 `_insert_paths` 等效于初始化。_

- [ ] **Step 3: 重写 _open_pdf → _add_files**

将 `_open_pdf` 方法替换为:

```python
def _add_files(self):
    """添加文件（追加到末尾）"""
    paths, _ = QFileDialog.getOpenFileNames(
        self, "选择文件", "",
        "支持的文件 (*.pdf *.jpg *.jpeg *.png *.bmp *.gif *.tiff *.webp);;PDF (*.pdf);;图片 (*.jpg *.jpeg *.png *.bmp)"
    )
    if paths:
        self._insert_paths(paths, len(self.pages))
```

- [ ] **Step 4: 新增 _clear_document 方法**

```python
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
```

- [ ] **Step 5: 更新 _load_pdf → _on_document_loaded**

将 `_load_pdf` 方法重命名为 `_on_document_loaded`，简化逻辑:

```python
def _on_document_loaded(self, first_path):
    """首次加载文件后的状态更新"""
    count = len(self.pages)
    self.selected_indices.clear()
    self._refresh_thumbnails()
    self.empty_label.setVisible(False)
    self.btn_export.setEnabled(True)
    self.btn_clear.setEnabled(True)
    self.drop_label.setText(f"已加载 {count} 页\n可继续拖入文件追加")
    MainWindow.set_status(f"共 {count} 页")
```

- [ ] **Step 6: 更新 _insert_paths，首次加载时触发状态更新**

在 `_insert_paths` 方法末尾（`self._refresh_thumbnails()` 之前）添加:

```python
# 如果是首次加载（之前为空），更新 UI 状态
was_empty = len(self.pages) == 0
```

修改 `_insert_paths` 的 `self._refresh_thumbnails()` 之后的逻辑:

```python
self._refresh_thumbnails()
if was_empty and self.pages:
    self.empty_label.setVisible(False)
    self.btn_export.setEnabled(True)
    self.btn_clear.setEnabled(True)
    self.drop_label.setText(
        f"已加载 {len(self.pages)} 页\n可继续拖入文件追加"
    )
MainWindow.set_status(f"已插入 {len(new_entries)} 页，共 {len(self.pages)} 页")
```

- [ ] **Step 7: 更新 _delete_selected 清空处理**

在 `_delete_selected` 方法中，更新清空后的处理逻辑（替换现有的按钮隐藏部分）:

```python
if not self.pages:
    self.btn_export.setEnabled(False)
    self.btn_clear.setEnabled(False)
    self.empty_label.setVisible(True)
    self.drop_label.setText("拖拽 PDF / 图片文件到此处\n或点击按钮选择文件")
```

- [ ] **Step 8: 移除 _insert_file 方法**

_说明：插入功能现在通过右键菜单（`_on_insert_requested`）和拖拽即可，不再需要独立的"插入文件"按钮。保留 `_on_insert_requested` 方法不变。_

删除 `_insert_file` 方法（约 lines 998-1007）。

- [ ] **Step 9: 更新空状态文案**

将 `_refresh_thumbnails` 中的空状态文案从 `"请先打开一个 PDF 文件"` 改为:

```python
"拖拽文件到此处或点击「添加文件」开始"
```

### Task 4: 语法验证与构建

- [ ] **Step 1: 语法检查**

```bash
python -c "import ast; ast.parse(open(r'C:\Users\Litbug\Desktop\办公工具箱\office_toolkit.py', encoding='utf-8').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 2: 导入检查**

```bash
python -c "import sys; sys.path.insert(0, r'C:\Users\Litbug\Desktop\办公工具箱'); from PySide6.QtWidgets import QApplication; import fitz; from PIL import Image; from pypdf import PdfReader, PdfWriter; print('Imports OK')"
```

Expected: `Imports OK`

- [ ] **Step 3: 构建 exe**

```bash
cd "C:/Users/Litbug/Desktop/办公工具箱" && pyinstaller --onefile --windowed --name "办公工具箱" --hidden-import PySide6 --hidden-import PIL --hidden-import pypdf --hidden-import fitz --hidden-import PIL._tkinter_finder office_toolkit.py 2>&1 | tail -5
```

Expected: `Build complete!` 成功

- [ ] **Step 4: Commit**

```bash
git add office_toolkit.py
git commit -m "refactor: remove merge module, unify into editor"
```

## 验证

1. 启动程序，确认标题栏只有「办公工具箱」标题，无导航栏
2. 拖入一个 PDF → 缩略图正常显示，所有页面预览正确
3. 拖入另一个 PDF → 追加到末尾，缩略图重新排列
4. 拖入一张图片 → 追加为单页
5. 拖拽调整页面顺序 → 排序正确
6. 选中页面删除 → 删除正确
7. 右键插入文件 → 插入正确
8. 点击「清空」→ 所有页面清除，恢复空状态
9. 导出 PDF → 内容正确，所有页面按顺序合并
