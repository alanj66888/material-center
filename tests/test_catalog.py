"""Correctness and failure-isolation checks for large-library infrastructure."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from catalog_index import CatalogReader, CatalogChanged, name_key
from preview_jobs import PreviewJobs, PreviewBusy
from cache_maintenance import pin, trim


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data = server.DATA
        server.DATA = Path(self.tmp.name) / "data"
        server.initialize()
        self.root = Path(self.tmp.name) / "media"
        self.root.mkdir()
        (self.root / "sub").mkdir()
        for index in range(245):
            folder = self.root if index < 5 else self.root / "sub"
            (folder / f"风光_{index:04}.txt").write_text(str(index))
        server.scan(self.root)
        self.reader = CatalogReader()

    def tearDown(self):
        if self.reader.connection:
            self.reader.connection.close()
        server.DATA = self.old_data
        self.tmp.cleanup()

    def items(self, query="recursive=1", **extra):
        params = parse_qs(query, keep_blank_values=True)
        params.update({key: [str(value)] for key, value in extra.items()})
        return self.reader.items(server.DATA, params)

    def test_pagination_scopes_tags_search_and_invalidation(self):
        summary = self.reader.catalog(server.DATA)
        self.assertEqual(summary["total"], 245)
        self.assertEqual(self.items()["total"], 245)
        self.assertEqual(len(self.items()["files"]), 160)
        self.assertEqual(len(self.items(offset=240)["files"]), 5)
        self.assertEqual(len(self.items(limit=99999)["files"]), 200)
        self.assertEqual(self.items("")["total"], 0)
        self.assertEqual(self.items("root=1")["total"], 5)
        self.assertEqual(self.items("root=1&folder=sub")["total"], 240)
        self.assertEqual(self.items("recursive=1&search=风光_000")["total"], 10)
        self.assertEqual(self.items("recursive=1&search=%25")["total"], 0)
        with server.db() as c:
            c.execute("UPDATE files SET tags='风景, 风景区',favorite=1 WHERE id=1")
        with self.assertRaises(CatalogChanged):
            self.items(revision=summary["revision"])
        self.assertEqual(self.items("recursive=1&tag=风景")["total"], 1)
        self.assertEqual(self.items("recursive=1&tag=风")["total"], 0)
        self.assertEqual(self.items("view=favorite")["total"], 1)
        latest = self.reader.catalog(server.DATA)
        self.assertEqual(latest["favorites"], 1)
        self.assertNotEqual(latest["revision"], summary["revision"])
        self.assertEqual(
            self.reader.catalog(server.DATA)["revision"], latest["revision"]
        )

    def test_browsing_cached_index_never_stats_nas(self):
        real_stat = Path.stat

        def guarded(path, *args, **kwargs):
            if str(path).startswith(str(self.root)):
                raise AssertionError("Browsing should not contact NAS")
            return real_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", guarded):
            self.assertEqual(self.reader.catalog(server.DATA)["total"], 245)
            self.assertEqual(self.items()["total"], 245)
            row = self.items()["files"][0]
            server.MediaSupport(server.DATA).folder(row)

    def test_scan_walk_does_not_lock_readers_or_tag_writer(self):
        entered, release = threading.Event(), threading.Event()
        failures = []
        real_scan = server.os.scandir
        (self.root / "new.txt").write_text("new")

        def paused(path):
            if Path(path) == self.root.resolve():
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("test stalled")
            return real_scan(path)

        def run():
            try:
                server.scan(self.root)
            except Exception as error:
                failures.append(error)

        with patch.object(server.os, "scandir", paused):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(self.items()["total"], 245)
                with server.db() as c:
                    c.execute("UPDATE files SET tags='扫描中修改',favorite=1 WHERE id=1")
                self.assertEqual(self.items("recursive=1&tag=扫描中修改")["total"], 1)
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(self.items()["total"], 246)
        self.assertEqual(self.items("recursive=1&tag=扫描中修改")["total"], 1)

    def test_no_change_rescan_does_not_invalidate_catalog(self):
        before = self.reader.catalog(server.DATA)["revision"]
        server.scan(self.root)
        self.assertEqual(self.reader.catalog(server.DATA)["revision"], before)

    def test_upgrade_legacy_index_preserves_tags_and_favorites(self):
        import sqlite3

        server.DATA = Path(self.tmp.name) / "legacy"
        server.DATA.mkdir()
        c = sqlite3.connect(server.DATA / "library.sqlite3")
        c.executescript(
            """CREATE TABLE roots(id INTEGER PRIMARY KEY,path TEXT UNIQUE);
          CREATE TABLE files(id INTEGER PRIMARY KEY,root INTEGER,path TEXT UNIQUE,name TEXT,folder TEXT,ext TEXT,kind TEXT,size INTEGER,modified REAL,favorite INTEGER DEFAULT 0,tags TEXT DEFAULT '',missing INTEGER DEFAULT 0);
          INSERT INTO roots VALUES(5,'/offline/legacy');
          INSERT INTO files VALUES(7,5,'/offline/legacy/子目录/图像10.jpg','图像10.jpg','子目录','jpg','image',100,100,1,'旧标签',0);"""
        )
        c.commit()
        c.close()
        server.initialize()
        self.assertEqual(self.items("view=favorite")["total"], 1)
        self.assertEqual(self.items("recursive=1&tag=旧标签")["files"][0]["id"], 7)
        self.assertEqual(self.reader.catalog(server.DATA)["total"], 1)
        self.assertEqual(
            self.reader.catalog(server.DATA)["directories"][0]["folder"], "子目录"
        )

    def test_natural_name_order(self):
        values = ["file10", "file2", "file1", "FILE3"]
        self.assertEqual(
            sorted(values, key=name_key), ["file1", "file2", "FILE3", "file10"]
        )


class ResourceBoundsTests(unittest.TestCase):
    def test_preview_queue_coalesces_bounds_and_skips_obsolete_work(self):
        queue = PreviewJobs(workers=1, pending=1)
        entered, release = threading.Event(), threading.Event()

        def active():
            entered.set()
            release.wait(4)
            return "done"

        first = queue.submit("first", 1, active)
        self.assertTrue(entered.wait(2))
        self.assertIs(first, queue.submit("first", 1, lambda: None))
        ran = []
        queue.focus("client", [2])
        obsolete = queue.submit("second", 2, lambda: ran.append(2), client="client")
        with self.assertRaises(PreviewBusy):
            queue.submit("third", 3, lambda: None)
        queue.focus("client", [])
        release.set()
        self.assertEqual(first.result(timeout=3), "done")
        with self.assertRaises(PreviewBusy):
            obsolete.result(timeout=3)
        self.assertEqual(ran, [])

    def test_cache_quota_retains_pinned_and_original_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            cache = data / "preview-cache"
            cache.mkdir()
            original = data / "original.txt"
            original.write_text("keep")
            a, b = cache / ("a" * 64), cache / ("b" * 64)
            for folder in [a, b]:
                folder.mkdir()
                (folder / "poster.jpg").write_bytes(b"1" * 100)
            with pin(a):
                result = trim(data, limit=50, min_age=0)
                self.assertEqual(result["removed"], 1)
                self.assertTrue(a.is_dir())
                self.assertFalse(b.exists())
            self.assertEqual(original.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
