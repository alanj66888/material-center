# 素材中心 · Material Center 1.4.0

直接连接已有本地或 NAS 素材文件夹，保留目录结构，浏览、预览、检索和归类，无需上传素材。

**源码公开，欢迎非商业用途的共创。本项目不是允许商业使用的 OSI 开源项目。** 自有代码、文档与项目方提供的图标按 [PolyForm Noncommercial 1.0.0](LICENSE) 提供。未经许可，不授权用于收费售卖、商业服务、商业剪辑接单，以及公司/工作室的内部生产、经营或商业研发。具体权利以 LICENSE 为准。第三方组件保留各自许可证，见 [第三方声明](THIRD_PARTY_NOTICES.md)。

## 安装

从 [GitHub Releases](https://github.com/alanj66888/material-center/releases) 下载：

- **Mac**：Apple M 系列，macOS **13 或以上**。DMG 打开后将应用拖入 Applications。
- **Windows**：Windows 10/11 x64。安装 ZIP 解压后运行其中的 EXE 向导。

先退出旧版再更新。资料库目录继续沿用旧名称以保留索引、收藏和标签：Mac 为 `~/Library/Application Support/素材屿`；Windows 为 `%APPDATA%\素材屿`。卸载程序不删除原素材或资料库。备份时退出应用，复制整个资料库目录。

程序未进行商业发行者签名。Windows 实机安装、显示效果与真实 NAS 双机并发仍需实际环境验收。

## 功能

- 连接已有目录，关闭“显示子文件夹素材”时显示直属文件夹与素材，支持空文件夹。
- 搜索名称/路径/标签，收藏、批量标签，文件夹名称与数量排序。
- 视频缩略图左右滑动定位，双击预览自动播放，下方切换附近素材；音频单击试听。
- 选择展示时长、大小、尺寸；左右侧栏和目录/标签区域可拖动调整。
- 素材区空白处拖动框选，靠近边缘自动滚动；Shift 跨页连选，Ctrl/⌘ 追加选择；单次最多选择 5000 项。
- 可预览的临时回收站，支持还原。移入回收站会移动实际文件；还原不覆盖同名文件；永久删除需明确确认。
- 两台电脑连接 NAS 同一级根目录并启用共享标签后，约每 15 秒同步。收藏仍在本机。
- 跟随系统/浅色/深色外观和运行中图标选择。安装图标固定为蓝紫版本。
- 桌面版可拖缩略图到文件管理器或支持的剪辑软件。Mac 既有原文件拖放经过用户验证，Windows 仍需实机验收。

## 大素材库与 NAS

每页读取 160 条，最多缓存 8 页，中央网格与目录树只绘制可见部分。选择项和附近预览会单独保留；选择上限不会限制素材库总数量。

日常列出素材使用本机 SQLite 索引，不逐个探测 NAS 文件。新增/移动/改名后右键重新扫描。扫描在后台遍历，完成后统一发布；失败时保留上一份完整索引。扫描中可继续浏览和打标签。

本机预览最多同时生成 2 个，兼容视频最多转换 1 个，队列有上限，跳过过期的屏幕外任务。缓存超过约 6 GiB 时清理较旧内容；正在生成或近期使用的缓存暂不清理，可能临时超过配额。

已用生成的 120,000 条本地索引验证分页、深层滚动与跨页预览。目录摘要约 81 KB、160 条一页约 65 KB，旧全量约 48 MB。这不是实际 NAS 吞吐、窗口帧率或素材数量上限。首次抽帧/RAW 解码与原片播放仍受 NAS 带宽、时延和编码影响。

NAS 共享标签与回收内容保存在根目录隐藏的 `.material-center` 目录。请一并备份，不要随意删除。应用外改名或移动后，旧路径标签不会自动迁移。

## 1.4.0 许可迁移与格式变化

PDF/AI/SVG 改用 PDFium/resvg，移除 PyMuPDF、MuPDF 和 Ghostscript。字体样张、DNG/RAW、常见视频与 MTS 仍受支持，不能保证所有私有格式、相机型号、加密或损坏文件都能解码。

- PDF 与包含 PDF 兼容内容的 AI：预览首页。
- SVG/SVGZ：静态渲染，禁用外部文件/网络资源引用。
- EPS/旧 AI/PostScript：只读取已有内嵌预览；不执行 PostScript。没有兼容内容时保留文件索引并提示转换，不展示误导性破图。
- XPS/OXPS：可收录，暂无内置完整渲染，请转换为 PDF。
- 兼容 H.264 视频使用 macOS VideoToolbox 或 Windows Media Foundation；Windows N/缺少媒体组件的系统可能需要安装系统媒体功能。

Mac 最低版本提高到 macOS 13（PDFium 组件要求）。旧 1.3.0 安装包未按本次非商用分发方案整理，不作为本仓库的公开发行物。

## 源码运行与验证

Python 3.11+，Node 18+。创建并激活虚拟环境：

```sh
python -m pip install -r requirements.txt
python server.py
```

需要 FFmpeg：可使用自己安装的版本，或运行下面的自编译脚本后设置 `SUCAIYU_MEDIA_LIBS` 指向对应目录。发行构建不使用 imageio-ffmpeg 中的预编译二进制。

```sh
python -m unittest discover -s tests -p 'test_*.py'
npm install
npm test
python tests/benchmark_catalog.py
```

测试仅使用生成的样片与索引，不需要真实 NAS。源码默认索引目录为 `.library`；可用 `SUCAIYU_DATA_DIR` 指向独立测试目录。不要把这些数据提交到仓库。

## 发行构建

在 Apple M 系列 Mac 上构建，需 Swift 工具链、Python 3.11、PyInstaller 5.13、Windows 运行环境和 NSIS 工具集。下载、验证与构建脚本位于 `packaging/`：

```sh
python packaging/prepare_release_media.py
python packaging/prepare_ffmpeg.py mac-arm64
python packaging/prepare_ffmpeg.py win-x64
python packaging/prepare_icons.py
python packaging/prepare_source_bundle.py
python packaging/download_runtimes.py
python packaging/build_release.py mac
python packaging/build_release.py windows
python packaging/build_windows_installer.py
python packaging/verify_release.py
```

多媒体组件在 `.build/release-media-noncommercial/`，由系统架构选择载入。保留第三方许可证、对应源码附件与构建配置；不允许将整个安装包中的第三方内容误标为非商用。

## 参与共创

使用 [Issues](https://github.com/alanj66888/material-center/issues) 报告问题或讨论需求；Fork 后提交 Pull Request。请先阅读 [贡献指南](CONTRIBUTING.md) 与 [安全说明](SECURITY.md)。没有额外邀请的人也可以提交 PR，但不能直接修改主仓库。请勿提交真实素材、NAS 地址、标签数据库、缓存或凭据。
