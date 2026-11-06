from contextlib import contextmanager
import errno
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from library_features import LibraryFeatures


class FeaturesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.original_data = server.DATA
        self.nas = self.folder / "共享素材"
        self.nas.mkdir()
        (self.nas / "manifest.json").write_bytes(b"original media bytes")
        self.ids = {}
        for device in ["a", "b"]:
            server.DATA = self.folder / device
            server.initialize()
            server.scan(self.nas)
            with server.db() as c:
                row = c.execute("SELECT * FROM files").fetchone()
                self.ids[device] = (row["root"], row["id"])
        server.DATA = self.original_data

    def tearDown(self):
        server.DATA = self.original_data
        self.tmp.cleanup()

    @contextmanager
    def device(self, name):
        server.DATA = self.folder / name
        with server.db() as c:
            yield LibraryFeatures(c), c

    def test_shared_tags_merge_and_remove_without_clobbering_other_device(self):
        ar, af = self.ids["a"]
        br, bf = self.ids["b"]
        with self.device("a") as (a, c):
            c.execute("UPDATE files SET tags=? WHERE id=?", ("甲", af))
            a.enable(ar)
        with self.device("b") as (b, c):
            c.execute("UPDATE files SET tags=? WHERE id=?", ("乙", bf))
            b.synchronize(b.root(br))
            self.assertEqual(
                set(c.execute("SELECT tags FROM files").fetchone()[0].split(", ")),
                {"甲", "乙"},
            )
        with self.device("a") as (a, c):
            a.synchronize(a.root(ar))
            a.set_tags([(af, ["甲", "乙", "A"], "甲, 乙")])
        with self.device("b") as (b, c):
            b.set_tags([(bf, ["甲", "乙", "B"], "甲, 乙")])
        with self.device("a") as (a, c):
            a.synchronize(a.root(ar))
            tags = c.execute("SELECT tags FROM files").fetchone()[0]
            self.assertEqual(set(tags.split(", ")), {"甲", "乙", "A", "B"})
            a.set_tags([(af, ["乙", "A", "B"], tags)])
        with self.device("b") as (b, c):
            b.synchronize(b.root(br))
            self.assertNotIn("甲", c.execute("SELECT tags FROM files").fetchone()[0])
        for event in (self.nas / ".material-center/tags-v1/events").glob("*.json"):
            self.assertNotIn(str(self.nas), event.read_text())

    def test_recycle_restore_across_devices_and_keep_filename_manifest(self):
        root, fid = self.ids["a"]
        with self.device("a") as (a, c):
            c.execute("UPDATE files SET tags=?,favorite=1 WHERE id=?", ("重要", fid))
            result = a.recycle([fid])
            self.assertFalse(result["errors"])
            self.assertFalse((self.nas / "manifest.json").exists())
            entries, errors = a.trash_entries()
            self.assertFalse(errors)
            self.assertEqual(
                Path(entries[0]["payload"]).read_bytes(), b"original media bytes"
            )
            selected = {"root": self.ids["b"][0], "id": entries[0]["id"]}
        with self.device("b") as (b, c):
            self.assertTrue(b.refresh_trash())
            self.assertEqual(c.execute("SELECT missing FROM files").fetchone()[0], 1)
            with patch(
                "library_features.os.link",
                side_effect=OSError(errno.EOPNOTSUPP, "unsupported"),
            ):
                restored = b.restore([selected])
                self.assertFalse(restored["errors"])
            self.assertEqual(
                (self.nas / "manifest.json").read_bytes(), b"original media bytes"
            )
        with self.device("a") as (a, c):
            a.refresh_trash()
            row = c.execute("SELECT tags,favorite,missing FROM files").fetchone()
            self.assertEqual(tuple(row), ("重要", 1, 0))

    def test_restore_collision_and_confirmed_purge_only_inside_bin(self):
        with self.device("a") as (a, c):
            a.recycle([self.ids["a"][1]])
            item = a.trash_entries()[0][0]
            selected = {"root": item["root"], "id": item["id"]}
            (self.nas / "manifest.json").write_bytes(b"new same-name media")
            self.assertTrue(a.restore([selected])["errors"])
            self.assertEqual(
                (self.nas / "manifest.json").read_bytes(), b"new same-name media"
            )
            with self.assertRaises(ValueError):
                a.purge([selected], "")
            self.assertTrue(Path(item["payload"]).is_file())
            self.assertEqual(
                len(a.purge([selected], "PERMANENTLY_DELETE")["processed"]), 1
            )
            self.assertEqual(
                (self.nas / "manifest.json").read_bytes(), b"new same-name media"
            )

    def test_corrupt_or_traversing_manifest_is_not_deleted(self):
        outside = self.folder / "outside.txt"
        outside.write_text("keep")
        with self.device("a") as (a, c):
            a.recycle([self.ids["a"][1]])
            item = a.trash_entries()[0][0]
            manifest = Path(item["directory"]) / "manifest.json"
            record = json.loads(manifest.read_text())
            record["relative"] = "../outside.txt"
            manifest.write_text(json.dumps(record))
            self.assertTrue(a.trash_entries()[1])
            self.assertTrue(
                a.purge(
                    [{"root": item["root"], "id": item["id"]}], "PERMANENTLY_DELETE"
                )["errors"]
            )
        self.assertEqual(outside.read_text(), "keep")

    def test_shared_metadata_and_recycle_files_are_not_rescanned(self):
        with self.device("a") as (a, c):
            a.enable(self.ids["a"][0])
            a.recycle([self.ids["a"][1]])
        server.DATA = self.folder / "a"
        self.assertEqual(server.scan(self.nas), 0)


if __name__ == "__main__":
    unittest.main()
