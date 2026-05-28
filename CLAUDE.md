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
| 打包 | PyInstaller --onefile --windowed | 单文件 exe |

## 文件结构

```
办公工具箱/
├── office_toolkit.py   # 唯一源码文件
├── icon.ico            # 应用图标
├── requirements.txt    # Python 依赖
├── README.md           # GitHub 项目说明
├── 使用说明.md          # 中文说明书 (Markdown)
├── 使用说明.txt         # 中文说明书 (纯文本)
├── .gitignore
├── CLAUDE.md           # 本文件
└── dist/
    └── 办公工具箱.exe    # 打包产物 (107 MB)
```

## 源码架构 (office_toolkit.py)

```
MainWindow
├── 标题栏 (应用名称)
├── EditPage               # 统一编辑界面
│   ├── PageEntry          # 数据模型（一页的元信息 + 缩略图缓存）
│   ├── ThumbnailWidget    # 单页缩略图控件（点击选中/取消 + 拖拽排序）
│   └── ExportWorker       # QThread 后台导出
└── 底部状态栏
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
- **外部拖入**：`DropListWidget`（合并）/ `EditPage.drop_zone`（编辑）处理 `dragEnterEvent`/`dropEvent`
- **内部排序**：合并列表使用 `QListWidget.InternalMove` 模式

### 样式
- Element UI 风格蓝白配色
- 全局样式表 `BASE_STYLE`，特定控件通过 `objectName` 覆盖
- 主按钮 `objectName='primaryBtn'`，导航按钮 `objectName='navBtn'`

## 打包命令

```bash
pyinstaller --onefile --windowed --name "办公工具箱" \
  --icon=icon.ico --add-data "icon.ico;." \
  --hidden-import PySide6 --hidden-import PIL --hidden-import pypdf \
  --hidden-import fitz --hidden-import PIL._tkinter_finder \
  office_toolkit.py
```

## 注意事项

- 用户数据（PDF/图片）已在 .gitignore 中排除，dist/ 和 build/ 也排除
- GitHub 仓库：https://github.com/pyfresh/pdf-merger (public)
- 支持格式：PDF, JPG, JPEG, PNG, BMP, GIF, TIFF, WEBP
- 编辑模块中插入 PDF 会导入该 PDF 的全部页面
- `MainWindow.set_status()` 是静态方法，子页面通过它更新底部状态栏
