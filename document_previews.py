"""Read-only font specimens and bounded raster previews for vector documents."""
import gzip
import io
from pathlib import Path
import threading

GRAPHICS = frozenset({"pdf", "ai", "eps", "ps", "svg", "svgz", "xps", "oxps"})
FONT_FORMATS = frozenset({"ttf", "otf", "ttc", "woff", "woff2"})
DOCUMENT_LOCK = (
    threading.Lock()
)  # PDFium must not be entered concurrently from HTTP workers.


def font_details(file):
    from fontTools.ttLib import TTFont

    with TTFont(file["path"], fontNumber=0, lazy=True) as font:
        cmap = font.getBestCmap() or {}
        names = font["name"].names if "name" in font else []

        def name(identifiers):
            for identifier in identifiers:
                matches = [entry for entry in names if entry.nameID == identifier]
                matches.sort(key=lambda entry: entry.langID != 0x804)
                for entry in matches:
                    try:
                        value = entry.toUnicode().strip()
                        if value:
                            return value[:200]
                    except (UnicodeError, ValueError):
                        pass
            return ""

        chinese = "".join(char for char in "素材中心字体预览山川湖海春夏秋冬" if ord(char) in cmap)
        latin = "".join(
            char
            for char in "Aa Bb Cc Dd Ee Ff Gg Hh"
            if char == " " or ord(char) in cmap
        ).strip()
        digits = "".join(char for char in "0123456789" if ord(char) in cmap)
        fallback = "".join(
            chr(code)
            for code in sorted(cmap)
            if chr(code).isprintable() and not chr(code).isspace()
        )[:16]
        lines = [text for text in [chinese[:8], latin, digits] if text]
        if not lines:
            lines = [fallback or "Aa"]
        return {
            "font_family": name([16, 1]),
            "font_style": name([17, 2]),
            "font_glyphs": len(cmap),
            "font_sample": lines[:3],
        }


def render_font(file, output):
    from PIL import Image, ImageDraw, ImageFont
    from fontTools.ttLib import TTFont

    details = font_details(file)
    source = file["path"]
    if file["ext"] in {"woff", "woff2"}:
        with TTFont(source) as font:
            font.flavor = None
            converted = io.BytesIO()
            font.save(converted)
        source = converted
    image = Image.new("RGB", (1280, 800), "#f5f7fb")
    draw = ImageDraw.Draw(image)
    heading = ImageFont.load_default(size=27)
    draw.text(
        (70, 42),
        "FONT PREVIEW  /  " + file["ext"].upper(),
        font=heading,
        fill="#65738a",
    )
    lines = details["font_sample"]
    for index, text in enumerate(lines):
        size = 132 if index == 0 else 95
        while True:
            if isinstance(source, io.BytesIO):
                source.seek(0)
            face = ImageFont.truetype(source, size=size, index=0)
            bounds = draw.textbbox((0, 0), text, font=face)
            if bounds[2] - bounds[0] <= 1140 or size <= 24:
                break
            size -= 6
        draw.text(
            (70 - bounds[0], 150 + index * 190 - bounds[1]),
            text,
            font=face,
            fill="#243149",
        )
    draw.line((70, 730, 1210, 730), fill="#d6deeb", width=2)
    draw.text(
        (70, 747),
        f"{details['font_glyphs']} glyphs  /  No installation required",
        font=heading,
        fill="#65738a",
    )
    image.save(output, "JPEG", quality=90)


def svg_source(file):
    import re
    import xml.etree.ElementTree as ET

    limit = 16 * 1024 * 1024
    if file["ext"] == "svgz":
        with gzip.open(file["path"], "rb") as source:
            data = source.read(limit + 1)
    else:
        with open(file["path"], "rb") as source:
            data = source.read(limit + 1)
    if len(data) > limit or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("SVG 内容过大或含有不支持的实体声明")
    root = ET.fromstring(data)
    if root.tag.split("}")[-1] != "svg":
        raise ValueError("文件不是有效 SVG")

    def unsafe(value):
        urls = re.findall(r"url\(\s*[\"']?([^)'\"]+)", value, re.I)
        return "@import" in value.lower() or any(
            not url.strip().startswith("#") for url in urls
        )

    for parent in list(root.iter()):
        for child in list(parent):
            local = child.tag.split("}")[-1]
            if (
                local in {"script", "foreignObject"}
                or local == "style"
                and unsafe(child.text or "")
            ):
                parent.remove(child)
        for key, value in list(parent.attrib.items()):
            if (
                key.split("}")[-1] == "href"
                and not value.startswith(
                    (
                        "#",
                        "data:image/png;",
                        "data:image/jpeg;",
                        "data:image/webp;",
                        "data:image/gif;",
                    )
                )
                or unsafe(value)
            ):
                del parent.attrib[key]
    box = re.split(r"[\s,]+", root.attrib.get("viewBox", "").strip())
    try:
        view = tuple(map(float, box))
        fallback = view[2:4] if len(view) == 4 else (300, 150)
    except ValueError:
        fallback = (300, 150)

    def dimension(name, default):
        text = root.attrib.get(name, "")
        match = re.fullmatch(r"\s*([\d.]+)(px|pt|pc|in|cm|mm)?\s*", text)
        if not match:
            return default
        value = (
            float(match[1])
            * {
                None: 1,
                "px": 1,
                "pt": 96 / 72,
                "pc": 16,
                "in": 96,
                "cm": 96 / 2.54,
                "mm": 96 / 25.4,
            }[match[2]]
        )
        return value if 0 < value < 1e7 else default

    width, height = dimension("width", fallback[0]), dimension("height", fallback[1])
    if not 0 < width < 1e7 or not 0 < height < 1e7:
        raise ValueError("SVG 尺寸无效")
    root.set("width", str(width))
    root.set("height", str(height))
    return ET.tostring(root, encoding="unicode"), width, height


def is_pdf(file):
    with open(file["path"], "rb") as source:
        return b"%PDF-" in source.read(1024)


def embedded_image(file):
    """Read existing bitmap previews; never interpret or execute PostScript."""
    import re
    import struct
    from PIL import Image, ImageOps

    path = Path(file["path"])
    with path.open("rb") as source:
        header = source.read(30)
        if header[:4] == b"\xc5\xd0\xd3\xc6" and len(header) >= 28:
            offset, size = struct.unpack_from("<II", header, 20)
            if (
                size
                and size <= 32 * 1024 * 1024
                and offset >= 30
                and offset + size <= path.stat().st_size
            ):
                source.seek(offset)
                data = source.read(size)
                with Image.open(io.BytesIO(data)) as image:
                    if image.width * image.height > 16000000:
                        raise ValueError("内嵌预览尺寸过大")
                    return image.copy()
        source.seek(0)
        data = source.read(4 * 1024 * 1024)
    match = re.search(
        rb"%%BeginPreview:\s*(\d+)\s+(\d+)\s+(1|8)\s+(\d+)[^\r\n]*[\r\n]+(.*?)%%EndPreview",
        data,
        re.S,
    )
    if match:
        width, height, depth = map(int, match.group(1, 2, 3))
        if not 0 < width * height <= 16000000:
            raise ValueError("内嵌预览尺寸过大")
        text = b"".join(
            line.strip().lstrip(b"%").strip() for line in match[5].splitlines()
        )
        pixels = bytes.fromhex(text.decode("ascii"))
        required = ((width * depth + 7) // 8) * height
        if len(pixels) != required:
            raise ValueError("内嵌预览数据不完整")
        image = Image.frombytes(
            "1" if depth == 1 else "L", (width, height), pixels
        ).convert("RGB")
        return ImageOps.invert(image)
    raise ValueError(
        "此 AI/EPS/PostScript 未包含 PDF 或可读取的内嵌预览；请用原制作软件另存 PDF/SVG 兼容版本。原文件未修改。"
    )


def graphic_details(file, folder):
    if file["ext"] in {"svg", "svgz"}:
        _, width, height = svg_source(file)
        return {
            "page_count": 1,
            "page_width": round(width, 2),
            "page_height": round(height, 2),
        }
    if file["ext"] in {"ai", "eps", "ps"} and not is_pdf(file):
        import re

        with open(file["path"], "rb") as source:
            data = source.read(65536)
        match = re.search(
            rb"%%(?:HiRes)?BoundingBox:\s*([-+\d.]+)\s+([-+\d.]+)\s+([-+\d.]+)\s+([-+\d.]+)",
            data,
        )
        if match:
            x1, y1, x2, y2 = map(float, match.groups())
            return {
                "page_count": 1,
                "page_width": round(x2 - x1, 2),
                "page_height": round(y2 - y1, 2),
            }
        image = embedded_image(file)
        return {"page_count": 1, "page_width": image.width, "page_height": image.height}
    if file["ext"] in {"xps", "oxps"}:
        raise ValueError("当前非商业分发版不再包含 XPS 解码器，请转换为 PDF 后预览。")
    import pypdfium2 as pdfium

    with DOCUMENT_LOCK, pdfium.PdfDocument(file["path"]) as document:
        if not len(document):
            raise ValueError("文件没有可预览的页面")
        page = document[0]
        try:
            width, height = page.get_size()
        finally:
            page.close()
        return {
            "page_count": len(document),
            "page_width": round(width, 2),
            "page_height": round(height, 2),
        }


def render_graphic(file, folder, output):
    from PIL import Image

    if file["ext"] in {"svg", "svgz"}:
        import resvg_py

        text, width, height = svg_source(file)
        scale = min(1600 / max(width, height, 1), 3)
        data = resvg_py.svg_to_bytes(
            svg_string=text,
            width=max(1, round(width * scale)),
            height=max(1, round(height * scale)),
            background="white",
            resources_dir=None,
        )
        with Image.open(io.BytesIO(data)) as image:
            image.convert("RGB").save(output, "JPEG", quality=90)
        return
    if file["ext"] in {"ai", "eps", "ps"} and not is_pdf(file):
        image = embedded_image(file).convert("RGB")
        image.thumbnail((1600, 1600))
        image.save(output, "JPEG", quality=90)
        return
    if file["ext"] in {"xps", "oxps"}:
        raise ValueError("当前非商业分发版不再包含 XPS 解码器，请转换为 PDF 后预览。")
    import pypdfium2 as pdfium

    with DOCUMENT_LOCK, pdfium.PdfDocument(file["path"]) as document:
        if not len(document):
            raise ValueError("文件没有可预览的页面")
        page = document[0]
        try:
            width, height = page.get_size()
            scale = min(1600 / max(width, height, 1), 3)
            bitmap = page.render(scale=scale, fill_color=(255, 255, 255, 255))
            try:
                bitmap.to_pil().convert("RGB").save(output, "JPEG", quality=90)
            finally:
                bitmap.close()
        finally:
            page.close()
