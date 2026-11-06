import os
from pathlib import Path
import sys
import tempfile
import unittest

if os.environ.get("SUCAIYU_MEDIA_LIBS"):
    sys.path.insert(0, os.environ["SUCAIYU_MEDIA_LIBS"])
from media_support import MediaSupport
from document_fixtures import make_documents
from document_previews import svg_source


class DocumentPreviewTest(unittest.TestCase):
    def test_actual_fonts_and_vectors_keep_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            files = make_documents(folder / "样片")
            support = MediaSupport(folder / "data")
            for path in files:
                with self.subTest(path=path.name):
                    original = path.read_bytes()
                    extension = path.suffix[1:]
                    row = {
                        "path": str(path),
                        "ext": extension,
                        "kind": "font"
                        if extension in {"ttf", "otf", "ttc", "woff", "woff2"}
                        else "document"
                        if extension == "pdf"
                        else "image",
                    }
                    information = support.metadata(row)
                    self.assertNotIn("error", information, information)
                    if row["kind"] == "font":
                        self.assertEqual(
                            information["font_family"], "Material Preview Fixture"
                        )
                    else:
                        self.assertEqual(information["page_count"], 1)
                    if extension == "eps" or path.name == "PostScript兼容矢量图.ai":
                        with self.assertRaisesRegex(ValueError, "内嵌预览"):
                            support.poster(row)
                        self.assertEqual(path.read_bytes(), original)
                        continue
                    poster = support.poster(row)
                    self.assertTrue(poster.read_bytes().startswith(b"\xff\xd8"))
                    from PIL import Image, ImageStat

                    with Image.open(poster) as image:
                        self.assertLessEqual(max(image.size), 1600)
                        self.assertGreater(max(ImageStat.Stat(image).var), 100)
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(support.poster(row), poster)

    def test_eps_embedded_tiff_preview_without_postscript_execution(self):
        import io, struct
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            sample = Image.new("RGB", (80, 40), "white")
            ImageDraw.Draw(sample).rectangle((5, 5, 40, 35), fill="blue")
            stream = io.BytesIO()
            sample.save(stream, format="TIFF")
            data = stream.getvalue()
            postscript = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 80 40\n"
            header = struct.pack(
                "<7IH",
                0xC6D3D0C5,
                30,
                len(postscript),
                0,
                0,
                30 + len(postscript),
                len(data),
                0xFFFF,
            )
            source = folder / "sample.eps"
            source.write_bytes(header + postscript + data)
            row = {"path": str(source), "ext": "eps", "kind": "image"}
            output = MediaSupport(folder / "data").poster(row)
            with Image.open(output) as image:
                self.assertEqual(image.size, (80, 40))
            self.assertEqual(source.read_bytes(), header + postscript + data)

    def test_svg_external_resources_removed_and_svgz_bounded(self):
        import gzip

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.svg"
            path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="240"><image href="file:///private/secret.png"/><style>@import url(https://invalid.test/style);</style><script>alert(1)</script></svg>'
            )
            text, width, height = svg_source({"path": str(path), "ext": "svg"})
            self.assertNotIn("secret.png", text)
            self.assertNotIn("@import", text)
            self.assertNotIn("script", text)
            self.assertEqual((width, height), (400, 240))
            compressed = path.with_suffix(".svgz")
            with gzip.open(compressed, "wb") as output:
                output.write(b" " * (16 * 1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "内容过大"):
                svg_source({"path": str(compressed), "ext": "svgz"})


if __name__ == "__main__":
    unittest.main()
