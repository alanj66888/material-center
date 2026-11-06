import os
import sys

if os.environ.get("SUCAIYU_MEDIA_LIBS"):
    sys.path.insert(0, os.environ["SUCAIYU_MEDIA_LIBS"])
from pathlib import Path
import tempfile
import unittest
from feature_fixtures import make_media
from media_support import MediaSupport, capabilities, run, ffmpeg


@unittest.skipUnless(all(capabilities().values()), "需要隔离测试的 FFmpeg/RAW/Pillow 依赖")
class MediaTest(unittest.TestCase):
    def test_actual_dng_mts_poster_metadata_and_proxy(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            make_media(folder / "素材")
            support = MediaSupport(folder / "data")

            def row(name, kind):
                return {
                    "path": str(folder / "素材" / name),
                    "kind": kind,
                    "ext": name.rsplit(".", 1)[1].lower(),
                }

            raw = row("03_RAW原片.DNG", "image")
            original = Path(raw["path"]).read_bytes()
            metadata = support.metadata(raw)
            self.assertEqual((metadata["width"], metadata["height"]), (128, 96))
            self.assertTrue(support.poster(raw).read_bytes().startswith(b"\xff\xd8"))
            self.assertEqual(Path(raw["path"]).read_bytes(), original)
            video = row("04_相机素材.MTS", "video")
            metadata = support.metadata(video)
            self.assertEqual((metadata["width"], metadata["height"]), (320, 180))
            self.assertGreater(metadata["duration"], 1)
            self.assertTrue(support.poster(video).is_file())
            self.assertTrue(support.frame(video, 40).is_file())
            proxy = support.proxy(video)
            self.assertGreater(proxy.stat().st_size, 0)
            inspection = run(
                [ffmpeg(), "-hide_banner", "-i", str(proxy)]
            ).stderr.decode(errors="replace")
            self.assertIn("h264", inspection)
            self.assertEqual(support.proxy(video), proxy)


if __name__ == "__main__":
    unittest.main()
