# PDF 合并工具

一款基于 PySide6 的现代化 Windows 桌面工具，可将多个 PDF 和图片文件按自定义顺序合并为一个 PDF 文档。

## 功能特性

- **拖拽添加** — 将文件直接拖入窗口即可添加，支持 PDF 和常见图片格式
- **拖拽排序** — 在列表中拖拽条目自由调整合并顺序
- **批量导入** — 支持一键导入整个文件夹
- **实时进度** — 合并过程显示百分比进度
- **绿色免安装** — 打包为单个 exe，无需安装 Python 或任何依赖

## 支持格式

| 类型 | 格式 |
|------|------|
| PDF | `.pdf` |
| 图片 | `.jpg` `.jpeg` `.png` `.bmp` `.gif` `.tiff` `.webp` |

## 使用说明

1. 下载 `dist/PDF合并工具.exe`
2. 双击运行，将 PDF/图片拖入窗口
3. 在列表中拖拽调整顺序
4. 点击「合并导出 PDF」选择保存位置
5. 完成

详细说明见 [使用说明](使用说明.md)

## 从源码运行

```
pip install -r requirements.txt
python pdf_merger_gui.py
```

## 自行打包

```
pip install pyinstaller
pyinstaller --onefile --windowed --name "PDF合并工具" pdf_merger_gui.py
```

## 技术栈

- Python 3.12
- PySide6 — GUI 框架
- pypdf — PDF 合并
- Pillow — 图片处理
- PyInstaller — 打包为 exe

## 许可证

MIT License
