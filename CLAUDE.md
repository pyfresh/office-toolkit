# 办公工具箱

## 项目概述

Windows 桌面 PDF 工具，统一编辑界面完成 PDF 合并、编辑、导出，PySide6 GUI + PyInstaller 打包为单文件 exe。

## 技术栈

| 层 | 库 | 用途 |
|----|-----|------|
| GUI | PySide6 (Qt 6.11) | 主界面、拖拽、缩略图渲染 |
| PDF 读取/渲染 | PyMuPDF (fitz) | 打开 PDF、渲染页面缩略图 |
| PDF 写入 | pypdf | 合并、导出 PDF |
| 图片处理 | Pillow | 图片转 PDF 页面 |
| OCR | winocr + ollama | Windows 系统 OCR / GLM-OCR 双后端可切换 |
| 打包 | PyInstaller --onefile --windowed | 单文件 exe |

## 文件结构

```
办公工具箱/
├── office_toolkit.py   # 主界面 + MainWindow + BASE_STYLE + 入口
├── edit_page.py        # 编辑：PageEntry, ThumbnailWidget, ExportWorker, EditPage
├── ocr_backend.py      # OCR：双引擎后端 + OcrWorker + OcrResultDialog
├── settings_dialog.py  # 设置对话框
├── icon.ico            # 应用图标
├── requirements.txt    # Python 依赖
├── README.md           # GitHub 项目说明
├── 使用说明.md          # 中文说明书 (Markdown)
├── 使用说明.txt         # 中文说明书 (纯文本)
├── .gitignore
├── CLAUDE.md           # 本文件
└── dist/
    └── 办公工具箱.exe    # 打包产物
```

## 源码架构

```
office_toolkit.py  →  MainWindow (标题栏 + EditPage + 状态栏)
edit_page.py       →  PageEntry, ThumbnailWidget, ExportWorker, EditPage
ocr_backend.py     →  OcrBackend, WindowsOcrBackend, OllamaOcrBackend, OcrWorker, OcrResultDialog
settings_dialog.py →  SettingsDialog
```

## 关键设计决策

### 选中逻辑 (EditPage)
- **纯 toggle 模式**：单击选中，再次单击取消，可多选。不用 Ctrl 修饰键。
- `ThumbnailWidget.clicked` 信号 → `EditPage._on_thumb_clicked` → 切换 `selected_indices` 集合
- 视觉反馈：选中页蓝色边框 + 浅蓝底色，通过 `ThumbnailWidget.set_selected(True/False)` 切换

### 缩略图渲染
- 使用 PyMuPDF 按 `THUMB_SIZE(200px)` 宽度等比缩放渲染
- `PageEntry.render_pixmap()` 带缓存 (`_pixmap`)，首次渲染后缓存 QPixmap
- 重新加载 PDF 时所有 `PageEntry` 重新创建，缓存自动失效

### 数据模型 (PageEntry)
- `entry_type`: `'pdf'` 或 `'image'`
- `source_path`: 源文件绝对路径
- `page_index`: PDF 中的页码索引（图片始终为 0）

### 拖拽支持
- **外部拖入**：`EditPage.drop_zone` 处理 `dragEnterEvent`/`dropEvent`，接受 PDF 和图片
- **内部排序**：`ThumbnailWidget.mouseMoveEvent` 创建 QDrag，`EditPage` 处理 drop 并重排 pages

### 样式
- Element UI 风格蓝白配色
- 全局样式表 `BASE_STYLE`（在 `office_toolkit.py`），特定控件通过 `objectName` 覆盖
- 主按钮 `objectName='primaryBtn'`

## 打包命令

```bash
pyinstaller --onefile --windowed --name "办公工具箱" \
  --icon=icon.ico --add-data "icon.ico;." \
  --hidden-import PySide6 --hidden-import PIL --hidden-import pypdf \
  --hidden-import fitz --hidden-import PIL._tkinter_finder \
  --hidden-import winrt --hidden-import ollama \
  office_toolkit.py
```

## 注意事项

- 用户数据（PDF/图片）已在 .gitignore 中排除，dist/ 和 build/ 也排除
- GitHub 仓库：https://github.com/pyfresh/pdf-merger (public)
- 支持格式：PDF, JPG, JPEG, PNG, BMP, GIF, TIFF, WEBP
- 编辑模块中插入 PDF 会导入该 PDF 的全部页面
- 状态栏通过 `ocr_backend.init_status(fn)` 注入回调，各模块调用 `ocr_backend.status(text)` 更新

### OCR 双后端 (ocr_backend)
- **策略模式**：`OcrBackend` 抽象基类 → `WindowsOcrBackend` / `OllamaOcrBackend`
- **设置持久化**：`QSettings("办公工具箱", "办公工具箱")` 保存 `ocr/engine` 值
- **引擎检测**：启动时检测 Ollama 是否可用，不可用时灰掉选项
- **异步执行**：OCR 在 `OcrWorker(QThread)` 中运行，不阻塞 UI
