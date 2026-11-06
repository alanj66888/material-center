import http.client
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data = server.DATA
        server.DATA = Path(self.tmp.name) / "data"
        server.initialize()
        self.root = Path(self.tmp.name) / "clips"
        self.root.mkdir()
        (self.root / "sample.mp4").write_bytes(b"0123456789")
        (self.root / "ignore.txt").write_text("ignore")
        (self.root / "sub").mkdir()
        (self.root / "sub" / "still.jpg").write_bytes(b"picture")
        self.http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        server.DATA = self.old_data
        self.tmp.cleanup()

    def request(self, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.http.server_port)
        conn.request(
            method, path, json.dumps(data) if data is not None else None, headers or {}
        )
        response = conn.getresponse()
        result = (response.status, dict(response.headers), response.read())
        conn.close()
        return result

    def test_trash_previews_are_read_only_and_stop_after_restore(self):
        server.scan(self.root)
        with server.db() as c:
            file = dict(c.execute("SELECT * FROM files WHERE ext='mp4'").fetchone())
            result = server.LibraryFeatures(c).recycle([file["id"]])
            self.assertEqual(len(result["processed"]), 1)
            item = server.LibraryFeatures(c).trash_entries()[0][0]
        base = f"/trash-preview/{item['root']}/{item['id']}/"
        self.assertEqual(
            self.request("GET", base + "media", headers={"Range": "bytes=2-5"})[2],
            b"2345",
        )
        with patch.object(
            server.MediaSupport, "metadata", return_value={"width": 320, "height": 180}
        ):
            status, _, body = self.request("GET", base + "metadata")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["width"], 320)
        poster = server.DATA / "mock-frame.jpg"
        poster.write_bytes(b"frame-test")
        with patch.object(server.MediaSupport, "frame", return_value=poster) as frame:
            self.assertEqual(
                self.request("GET", base + "frame?position=60")[2], b"frame-test"
            )
            self.assertEqual(frame.call_args.args[1], "60")
            self.assertEqual(frame.call_args.args[0]["path"], item["payload"])
        self.assertTrue(Path(item["payload"]).is_file())
        self.assertFalse(Path(file["path"]).exists())
        self.assertNotEqual(self.request("GET", base + "anything")[0], 200)
        self.assertEqual(
            self.request(
                "POST", "/api/trash-prepare", {"root": item["root"], "id": item["id"]}
            )[0],
            403,
        )
        with server.db() as c:
            server.LibraryFeatures(c).restore(
                [{"root": item["root"], "id": item["id"]}]
            )
        self.assertNotEqual(self.request("GET", base + "media")[0], 200)
        self.assertEqual(Path(file["path"]).read_bytes(), b"0123456789")

    def test_scan_update_rescan_and_missing(self):
        self.assertEqual(server.scan(self.root), 3)
        with server.db() as c:
            f = dict(c.execute("SELECT * FROM files WHERE ext='mp4'").fetchone())
        status, _, _ = self.request(
            "POST",
            "/api/update",
            {"id": f["id"], "favorite": 1, "tags": "风景"},
            {"X-Library-Token": server.TOKEN},
        )
        self.assertEqual(status, 200)
        server.scan(self.root)
        with server.db() as c:
            row = c.execute("SELECT * FROM files WHERE id=?", (f["id"],)).fetchone()
            self.assertEqual((row["favorite"], row["tags"]), (1, "风景"))
        (self.root / "sample.mp4").unlink()
        server.scan(self.root)
        status, _, body = self.request("GET", "/api/library")
        self.assertEqual(len(json.loads(body)["files"]), 2)
        self.assertEqual(self.request("GET", "/media/" + str(f["id"]))[0], 404)

    def test_range_and_request_boundaries(self):
        server.scan(self.root)
        with server.db() as c:
            fid = c.execute("SELECT id FROM files WHERE ext='mp4'").fetchone()[0]
        url = "/media/" + str(fid)
        status, headers, body = self.request("GET", url, headers={"Range": "bytes=2-5"})
        self.assertEqual(
            (status, body, headers["Content-Range"]), (206, b"2345", "bytes 2-5/10")
        )
        self.assertEqual(
            self.request("GET", url, headers={"Range": "bytes=-3"})[2], b"789"
        )
        self.assertEqual(
            self.request("GET", url, headers={"Range": "bytes=20-"})[0], 416
        )
        self.assertEqual(self.request("GET", "/../../etc/passwd")[0], 404)
        self.assertEqual(
            self.request("POST", "/api/scan", {"path": str(self.root)})[0], 403
        )
        self.assertEqual(
            self.request(
                "POST",
                "/api/scan",
                {"path": str(self.root)},
                {"X-Library-Token": server.TOKEN, "Origin": "https://example.com"},
            )[0],
            403,
        )
        self.assertEqual(
            self.request("GET", "/api/library", headers={"Host": "example.com"})[0], 403
        )
        self.assertEqual(
            self.request(
                "GET", "/api/library", headers={"Origin": "https://example.com"}
            )[0],
            403,
        )
        self.assertEqual(
            self.request(
                "POST",
                "/api/scan",
                {},
                {"X-Library-Token": server.TOKEN, "Content-Length": "-1"},
            )[0],
            400,
        )
        self.assertEqual(
            json.loads(self.request("GET", "/api/health")[2])["app"], "sucaiyu"
        )

    def test_scan_failure_keeps_existing_index(self):
        server.scan(self.root)
        with patch(
            "server.os.scandir", side_effect=OSError("simulated NAS read failure")
        ):
            with self.assertRaises(ValueError):
                server.scan(self.root)
        with server.db() as c:
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM files WHERE missing=0").fetchone()[0], 3
            )

    def test_paged_catalog_async_scan_and_pending_preview(self):
        import time
        from concurrent.futures import Future

        headers = {"X-Library-Token": server.TOKEN}
        status, _, body = self.request(
            "POST", "/api/scan-start", {"path": str(self.root)}, headers
        )
        self.assertEqual(status, 200)
        job = json.loads(body)
        deadline = time.monotonic() + 5
        while job["running"] and time.monotonic() < deadline:
            time.sleep(0.02)
            job = json.loads(self.request("GET", "/api/scan-status?id=" + job["id"])[2])
        self.assertEqual(job["phase"], "done")
        catalog = json.loads(self.request("GET", "/api/catalog")[2])
        self.assertEqual(catalog["total"], 3)
        self.assertNotIn("files", catalog)
        page = json.loads(self.request("GET", "/api/items?recursive=1&limit=1")[2])
        self.assertEqual(len(page["files"]), 1)
        self.assertEqual(page["total"], 3)
        identifier = next(
            row["id"]
            for row in json.loads(self.request("GET", "/api/library")[2])["files"]
            if row["ext"] == "mp4"
        )
        with patch.object(server.PREVIEWS, "submit", return_value=Future()):
            status, _, body = self.request(
                "GET", f"/preview-image/{identifier}?client=test"
            )
        self.assertEqual(status, 429)
        self.assertTrue(json.loads(body)["pending"])
        self.assertEqual(self.request("GET", "/api/catalog")[0], 200)
        self.assertEqual(self.request("GET", "/catalog.js")[0], 200)
        status, _, body = self.request("POST", "/api/sync-tags", {}, headers)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["changed"])

    def test_windows_open_and_reveal(self):
        server.scan(self.root)
        with server.db() as c:
            fid = c.execute("SELECT id FROM files WHERE ext='mp4'").fetchone()[0]
        headers = {"X-Library-Token": server.TOKEN}
        with patch.object(server.sys, "platform", "win32"), patch.object(
            server.os, "startfile", create=True
        ) as startfile, patch("server.subprocess.Popen") as popen:
            self.assertEqual(
                self.request("POST", "/api/open", {"id": fid}, headers)[0], 200
            )
            startfile.assert_called_once_with(str((self.root / "sample.mp4").resolve()))
            self.assertEqual(
                self.request("POST", "/api/reveal", {"id": fid}, headers)[0], 200
            )
            popen.assert_called_once_with(
                ["explorer.exe", "/select," + str((self.root / "sample.mp4").resolve())]
            )

    def test_add_and_batch_tags(self):
        headers = {"X-Library-Token": server.TOKEN}
        status, _, body = self.request(
            "POST", "/api/scan", {"path": str(self.root)}, headers
        )
        self.assertEqual((status, json.loads(body)["count"]), (200, 3))
        with server.db() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM files")]
        for _ in range(2):
            self.assertEqual(
                self.request(
                    "POST", "/api/tags", {"ids": ids, "tags": ["航拍", "风景"]}, headers
                )[0],
                200,
            )
        server.scan(self.root)
        with server.db() as c:
            self.assertEqual(
                [r[0] for r in c.execute("SELECT tags FROM files")], ["航拍, 风景"] * 3
            )
        self.assertEqual(
            self.request("POST", "/api/scan", {"path": "/nonexistent-folder"}, headers)[
                0
            ],
            400,
        )
        with patch(
            "server.subprocess.run",
            return_value=SimpleNamespace(
                returncode=1, stderr="picker failed", stdout=""
            ),
        ):
            status, _, body = self.request("POST", "/api/choose", {}, headers)
            self.assertEqual(status, 400)
            self.assertIn("picker failed", json.loads(body)["error"])

    def test_extended_formats_and_empty_directories(self):
        (self.root / "empty" / "nested").mkdir(parents=True)
        for name in [
            "photo.CR3",
            "drawing.PSD",
            "clip.MXF",
            "font.OTF",
            "project.blend",
            "notes.pdf",
            "pack.7z",
            "unknown.xyz",
            "LICENSE",
        ]:
            (self.root / name).write_bytes(b"test")
        server.scan(self.root)
        with server.db() as c:
            kinds = {
                r["name"]: r["kind"] for r in c.execute("SELECT name,kind FROM files")
            }
            directories = {r[0] for r in c.execute("SELECT folder FROM directories")}
        self.assertEqual(
            [
                kinds[n]
                for n in [
                    "photo.CR3",
                    "drawing.PSD",
                    "clip.MXF",
                    "font.OTF",
                    "project.blend",
                    "notes.pdf",
                    "pack.7z",
                    "unknown.xyz",
                    "LICENSE",
                ]
            ],
            [
                "image",
                "image",
                "video",
                "font",
                "project",
                "document",
                "archive",
                "other",
                "other",
            ],
        )
        self.assertTrue({"empty", "empty/nested"} <= directories)


if __name__ == "__main__":
    unittest.main()
