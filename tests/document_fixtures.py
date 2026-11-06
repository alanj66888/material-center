"""Small original font and vector fixtures, free of user files or external assets."""
from pathlib import Path
import shutil


def make_documents(folder):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    from fontTools.ttLib import TTFont, TTCollection

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    characters = "ABCabc012素材中心字体预览"
    order = [".notdef"] + [f"g{index}" for index in range(len(characters))]
    mapping = {ord(char): order[index + 1] for index, char in enumerate(characters)}
    metrics = {name: (900, 0) for name in order}
    for extension in ("ttf", "otf"):
        builder = FontBuilder(1000, isTTF=extension == "ttf")
        builder.setupGlyphOrder(order)
        builder.setupCharacterMap(mapping)
        shapes = {}
        for index, name in enumerate(order):
            pen = TTGlyphPen(None) if extension == "ttf" else T2CharStringPen(900, None)
            pen.moveTo((80, 50))
            pen.lineTo((760, 50))
            pen.lineTo((760, 700 - index % 4 * 60))
            pen.lineTo((80, 700 - index % 4 * 60))
            pen.closePath()
            shapes[name] = pen.glyph() if extension == "ttf" else pen.getCharString()
        if extension == "ttf":
            builder.setupGlyf(shapes)
        else:
            builder.setupCFF(
                "MaterialPreviewFixture",
                {
                    "FullName": "Material Preview Fixture",
                    "FamilyName": "Material Preview Fixture",
                    "Weight": "Regular",
                },
                shapes,
                {},
            )
        builder.setupHorizontalMetrics(metrics)
        builder.setupHorizontalHeader(ascent=850, descent=-150)
        builder.setupNameTable(
            {
                "familyName": "Material Preview Fixture",
                "styleName": "Regular",
                "uniqueFontIdentifier": "Material Preview Fixture",
                "fullName": "Material Preview Fixture",
                "psName": "MaterialPreviewFixture",
            }
        )
        builder.setupOS2(
            sTypoAscender=850, sTypoDescender=-150, usWinAscent=850, usWinDescent=150
        )
        builder.setupPost()
        builder.setupMaxp()
        builder.save(folder / ("字体样张." + extension))
    collection = TTCollection()
    collection.fonts = [TTFont(folder / "字体样张.ttf")]
    collection.save(folder / "字体合集.ttc")
    for flavor in ("woff", "woff2"):
        with TTFont(folder / "字体样张.ttf") as font:
            font.flavor = flavor
            font.save(folder / ("网页字体." + flavor))
    contents = b"0.13 0.45 0.86 rg 20 20 360 200 re f 1 1 1 rg 80 70 240 100 re f\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 240] /Resources << >> /Contents 4 0 R >>",
        b"<< /Length "
        + str(len(contents)).encode()
        + b" >>\nstream\n"
        + contents
        + b"endstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(str(index).encode() + b" 0 obj\n" + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(b"xref\n0 5\n0000000000 65535 f \n")
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    (folder / "矢量图.pdf").write_bytes(data)
    shutil.copy2(folder / "矢量图.pdf", folder / "PDF兼容矢量图.ai")
    eps = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 400 240\n%%EndComments\n0.13 0.45 0.86 setrgbcolor\n20 20 360 200 rectfill\n1 1 1 setrgbcolor\n80 70 240 100 rectfill\nshowpage\n%%EOF\n"
    (folder / "矢量图.eps").write_bytes(eps)
    (folder / "PostScript兼容矢量图.ai").write_bytes(eps)
    (folder / "矢量图.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="240"><rect x="20" y="20" width="360" height="200" fill="#2173db"/><circle cx="200" cy="120" r="60" fill="white"/></svg>'
    )
    return list(folder.iterdir())
