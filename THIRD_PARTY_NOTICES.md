# 第三方组件与分发说明

**项目的非商用限制仅适用于项目自有内容，不能限制第三方组件按其原许可证授予的权利。** 以下组件不改用 PolyForm Noncommercial。

| 组件 | 固定版本 | 许可与用途 |
| --- | --- | --- |
| pypdfium2 / PDFium | 5.14.0 | Python 绑定选择 BSD-3-Clause；PDFium 及其依赖保留轮包中的 BSD、Apache、MIT、FTL 等原声明，用于 PDF 与 PDF 兼容 AI。 |
| resvg_py / resvg | 0.5.0 / 0.48.1 | MIT 包装；resvg 0.48.1 选择 MIT（该版为 MIT/Apache 双许可），用于静态 SVG。 |
| Pillow | 13.0.0 | HPND/PIL 及随附依赖许可，用于图片和字体样张。 |
| rawpy / LibRaw | 0.28.0 / 0.22.2 | 包装 MIT，LibRaw 选择 LGPL-2.1-or-later，使用独立可替换的动态库；不包含 GPL demosaic packs。 |
| NumPy | 2.3.5 | BSD-3-Clause 及随附数学库声明。 |
| FontTools / Brotli / pypinyin | 4.61.1 / 1.2.1 / 0.55.0 | MIT / MIT / MIT。 |
| FFmpeg（独立程序） | 8.0.1 | LGPL-2.1-or-later；从官方源码自编译，禁用 GPL、nonfree 和 version3，使用系统 H.264 编码器；未静态链接到本项目程序。 |
| CPython / Electron | 发行脚本所固定的版本 | PSF / MIT 及 Electron 随附 Chromium 等第三方许可。 |

发行包保留各 wheel 的 `.dist-info` 许可目录、FFmpeg 的 LGPL 正文和上游声明、CPython 与 Electron 自带许可。PDFium 的构建许可在其 dist-info 的 `licenses/data/` 目录。

## 对应源码

每次公开发布必须同时提供 `third-party-sources-<版本>.tar.xz`，其中含与分发版本匹配的 FFmpeg 8.0.1 官方源码、rawpy 0.28.0（包含 LibRaw 源码）及 LibRaw 0.22.2 官方源码，以及来源 URL、SHA256 与本项目构建脚本。所有第三方源码仍按其原许可提供，不适用本项目的非商用限制。

FFmpeg 无源码补丁；配置记录在各架构 `vendor/<架构>/ffmpeg/build.json`，重建脚本为 `packaging/prepare_ffmpeg.py`。LibRaw 可使用同 ABI 的自行编译库替换，保留相应接口与原声明即可。允许为调试这类 LGPL 组件的修改而按上游许可进行必要的逆向工程；本项目许可不限制上游授予的权利。

## 1.4.0 移除的组件

发行包不包含 PyMuPDF、MuPDF 或 Ghostscript。PDF/SVG 已替换渲染器。纯 PostScript、缺少内嵌预览的 EPS/AI 及 XPS 不再提供完整渲染；请用原制作软件导出 PDF/SVG 或带预览的 EPS。未修改任何原素材。

## 上游

- https://github.com/pypdfium2-team/pypdfium2
- https://github.com/linebender/resvg/tree/v0.48.1
- https://github.com/baseplate-admin/resvg-py
- https://github.com/letmaik/rawpy
- https://www.libraw.org/
- https://ffmpeg.org/
