"""Local-only catalog snapshots, indexed filtering, and bounded result pages."""
from collections import OrderedDict
from functools import lru_cache
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import threading
import unicodedata
import uuid

from library_features import labels


@lru_cache(maxsize=8192)
def name_key(value):
    value = unicodedata.normalize("NFKC", value).casefold()
    if re.search("[\u3400-\u9fff]", value):
        try:
            from pypinyin import lazy_pinyin

            value = "".join(lazy_pinyin(value))
        except ImportError:
            pass
    return re.sub(
        r"\d+",
        lambda match: "\x01"
        + str(len(match[0].lstrip("0") or "0")).zfill(8)
        + (match[0].lstrip("0") or "0")
        + "\x01",
        value,
    )


def configure(connection):
    connection.create_function("catalog_name_key", 1, name_key, deterministic=True)
    connection.create_function(
        "catalog_tags",
        1,
        lambda value: json.dumps(labels(value), ensure_ascii=False),
        deterministic=True,
    )


def initialize(connection):
    configure(connection)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(files)")}
    if "name_key" not in columns:
        connection.execute(
            "ALTER TABLE files ADD COLUMN name_key TEXT NOT NULL DEFAULT ''"
        )
    connection.executescript(
        """
      CREATE TABLE IF NOT EXISTS catalog_schema(version INTEGER PRIMARY KEY);
      CREATE TABLE IF NOT EXISTS file_tags(file_id INTEGER NOT NULL,tag TEXT NOT NULL,PRIMARY KEY(file_id,tag));
      CREATE INDEX IF NOT EXISTS idx_file_tags_tag ON file_tags(tag,file_id);
      CREATE INDEX IF NOT EXISTS idx_files_scope_modified ON files(root,folder,modified DESC,id) WHERE missing=0;
      CREATE INDEX IF NOT EXISTS idx_files_root_modified ON files(root,modified DESC,id) WHERE missing=0;
      CREATE INDEX IF NOT EXISTS idx_files_modified ON files(modified DESC,id) WHERE missing=0;
      CREATE INDEX IF NOT EXISTS idx_files_kind_modified ON files(kind,modified DESC,id) WHERE missing=0;
      CREATE INDEX IF NOT EXISTS idx_files_favorite_modified ON files(favorite,modified DESC,id) WHERE missing=0;
      CREATE INDEX IF NOT EXISTS idx_files_name ON files(name_key,id) WHERE missing=0;
      CREATE INDEX IF NOT EXISTS idx_files_scope_name ON files(root,folder,name_key,id) WHERE missing=0;
      CREATE INDEX IF NOT EXISTS idx_files_size ON files(size DESC,id) WHERE missing=0;
      CREATE INDEX IF NOT EXISTS idx_files_scope_size ON files(root,folder,size DESC,id) WHERE missing=0;
      CREATE VIRTUAL TABLE IF NOT EXISTS file_search USING fts5(name,path,tags,content='files',content_rowid='id',tokenize='trigram');
      CREATE TRIGGER IF NOT EXISTS catalog_insert AFTER INSERT ON files BEGIN
        UPDATE files SET name_key=catalog_name_key(NEW.name) WHERE id=NEW.id;
        INSERT OR IGNORE INTO file_tags SELECT NEW.id,value FROM json_each(catalog_tags(NEW.tags));
        INSERT INTO file_search(rowid,name,path,tags) VALUES(NEW.id,NEW.name,NEW.path,NEW.tags);
      END;
      CREATE TRIGGER IF NOT EXISTS catalog_name AFTER UPDATE OF name ON files WHEN NEW.name!=OLD.name BEGIN
        UPDATE files SET name_key=catalog_name_key(NEW.name) WHERE id=NEW.id;
      END;
      CREATE TRIGGER IF NOT EXISTS catalog_tags_update AFTER UPDATE OF tags ON files WHEN NEW.tags!=OLD.tags BEGIN
        DELETE FROM file_tags WHERE file_id=NEW.id;
        INSERT OR IGNORE INTO file_tags SELECT NEW.id,value FROM json_each(catalog_tags(NEW.tags));
      END;
      CREATE TRIGGER IF NOT EXISTS catalog_search_update AFTER UPDATE OF name,path,tags ON files
      WHEN NEW.name!=OLD.name OR NEW.path!=OLD.path OR NEW.tags!=OLD.tags BEGIN
        INSERT INTO file_search(file_search,rowid,name,path,tags) VALUES('delete',OLD.id,OLD.name,OLD.path,OLD.tags);
        INSERT INTO file_search(rowid,name,path,tags) VALUES(NEW.id,NEW.name,NEW.path,NEW.tags);
      END;
      CREATE TRIGGER IF NOT EXISTS catalog_delete AFTER DELETE ON files BEGIN
        DELETE FROM file_tags WHERE file_id=OLD.id;
        INSERT INTO file_search(file_search,rowid,name,path,tags) VALUES('delete',OLD.id,OLD.name,OLD.path,OLD.tags);
      END;
    """
    )
    if not connection.execute(
        "SELECT 1 FROM catalog_schema WHERE version=1"
    ).fetchone():
        connection.execute("UPDATE files SET name_key=catalog_name_key(name)")
        connection.execute(
            "INSERT OR IGNORE INTO file_tags SELECT f.id,j.value FROM files f,json_each(catalog_tags(f.tags)) j WHERE f.tags!=''"
        )
        connection.execute("INSERT INTO file_search(file_search) VALUES('rebuild')")
        connection.execute("INSERT INTO catalog_schema VALUES(1)")


def filter_query(parameters):
    def value(name, default=""):
        return parameters.get(name, [default])[0]

    where = ["f.missing=0"]
    arguments = []
    root = value("root")
    folder = value("folder")
    recursive = value("recursive") == "1"
    view = value("view", "all")
    kind = value("kind", "all")
    tag = value("tag")
    search = value("search").strip()
    if root:
        where.append("f.root=?")
        arguments.append(int(root))
        if not recursive:
            where.append("f.folder=?")
            arguments.append(folder or ".")
        elif folder:
            where.append("(f.folder=? OR f.folder LIKE ? ESCAPE '\\')")
            arguments.extend([folder, escape_like(folder) + "/%"])
    elif not recursive and view == "all" and kind == "all" and not tag and not search:
        where.append("0")  # The library homepage shows connected folders.
    if view == "favorite":
        where.append("f.favorite=1")
    elif view in {"video", "image", "audio"}:
        where.append("f.kind=?")
        arguments.append(view)
    if kind != "all":
        where.append("f.kind=?")
        arguments.append(kind)
    if tag:
        where.append("f.id IN (SELECT file_id FROM file_tags WHERE tag=?)")
        arguments.append(tag)
    if search:
        if len(search) >= 3:
            where.append(
                "f.id IN (SELECT rowid FROM file_search WHERE file_search MATCH ?)"
            )
            arguments.append('"' + search.replace('"', '""') + '"')
        else:
            where.append(
                "(f.name LIKE ? ESCAPE '\\' OR f.path LIKE ? ESCAPE '\\' OR f.tags LIKE ? ESCAPE '\\')"
            )
            arguments.extend(["%" + escape_like(search) + "%"] * 3)
    order = {
        "name": "f.name_key,f.id",
        "size": "f.size DESC,f.id",
        "modified": "f.modified DESC,f.id",
    }.get(value("sort"), "f.modified DESC,f.id")
    return " AND ".join(where), arguments, order


def escape_like(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class CatalogChanged(ValueError):
    pass


class CatalogReader:
    """A persistent read connection detects commits from every writer/process via data_version."""

    def __init__(self):
        self.lock = threading.RLock()
        self.connection = None
        self.identity = None
        self.version = None
        self.summary = None
        self.counts = OrderedDict()
        self.epoch = uuid.uuid4().hex[:12]

    def connect(self, data):
        path = Path(data) / "library.sqlite3"
        identity = (str(path.resolve()), path.stat().st_ino)
        if self.identity != identity:
            if self.connection:
                self.connection.close()
            self.connection = sqlite3.connect(path, check_same_thread=False, timeout=5)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA query_only=ON")
            self.identity = identity
            self.version = None
            self.summary = None
            self.counts.clear()
            self.epoch = uuid.uuid4().hex[:12]
        version = self.connection.execute("PRAGMA data_version").fetchone()[0]
        if version != self.version:
            self.version = version
            self.summary = None
            self.counts.clear()
        return self.connection

    def transaction(self, data):
        c = self.connect(data)
        c.execute("BEGIN")
        version = c.execute("PRAGMA data_version").fetchone()[0]
        if version != self.version:
            self.version = version
            self.summary = None
            self.counts.clear()
        return c

    def revision(self):
        return self.epoch + "-" + str(self.version)

    def catalog(self, data):
        with self.lock:
            c = self.transaction(data)
            try:
                if self.summary is None:
                    roots = [
                        dict(row)
                        for row in c.execute(
                            """SELECT r.*,COALESCE(s.enabled,0) AS shared_tags,COALESCE(s.error,'') AS sync_error
                      FROM roots r LEFT JOIN shared_roots s ON s.root=r.id"""
                        )
                    ]
                    direct = [
                        dict(row)
                        for row in c.execute(
                            "SELECT root,folder,COUNT(*) AS count,COALESCE(SUM(size),0) AS size FROM files WHERE missing=0 GROUP BY root,folder"
                        )
                    ]
                    totals = c.execute(
                        "SELECT COUNT(*),COALESCE(SUM(favorite),0),COALESCE(SUM(size),0) FROM files WHERE missing=0"
                    ).fetchone()
                    counts = {}
                    sizes = {}
                    for row in direct:
                        ancestors = (
                            ["."]
                            if row["folder"] == "."
                            else [
                                ".",
                                *[
                                    "/".join(PurePosixPath(row["folder"]).parts[:i])
                                    for i in range(
                                        1, len(PurePosixPath(row["folder"]).parts) + 1
                                    )
                                ],
                            ]
                        )
                        for folder in ancestors:
                            key = (row["root"], folder)
                            counts[key] = counts.get(key, 0) + row["count"]
                            sizes[key] = sizes.get(key, 0) + row["size"]
                    directories = [
                        {
                            **dict(row),
                            "count": counts.get((row["root"], row["folder"]), 0),
                            "size": sizes.get((row["root"], row["folder"]), 0),
                        }
                        for row in c.execute("SELECT * FROM directories")
                    ]
                    for root in roots:
                        root.update(
                            count=counts.get((root["id"], "."), 0),
                            size=sizes.get((root["id"], "."), 0),
                        )
                    tags = [
                        dict(row)
                        for row in c.execute(
                            "SELECT t.tag,COUNT(*) AS count FROM file_tags t JOIN files f ON f.id=t.file_id WHERE f.missing=0 GROUP BY t.tag ORDER BY t.tag"
                        )
                    ]
                    self.summary = {
                        "roots": roots,
                        "directories": directories,
                        "tags": tags,
                        "total": totals[0],
                        "favorites": totals[1],
                        "total_size": totals[2],
                    }
                return {**self.summary, "revision": self.revision()}
            finally:
                c.execute("ROLLBACK")

    def items(self, data, parameters):
        with self.lock:
            c = self.transaction(data)
            try:
                revision = parameters.get("revision", [""])[0]
                if revision and revision != self.revision():
                    raise CatalogChanged("素材索引已更新，正在重新加载")
                where, args, order = filter_query(parameters)
                offset = max(0, int(parameters.get("offset", ["0"])[0]))
                limit = max(1, min(200, int(parameters.get("limit", ["160"])[0])))
                key = (where, tuple(args))
                counts = self.counts.get(key)
                if counts is None:
                    row = c.execute(
                        "SELECT COUNT(*),COALESCE(SUM(f.size),0) FROM files f WHERE "
                        + where,
                        args,
                    ).fetchone()
                    counts = (row[0], row[1])
                    self.counts[key] = counts
                    if len(self.counts) > 64:
                        self.counts.popitem(last=False)
                rows = [
                    dict(row)
                    for row in c.execute(
                        "SELECT f.* FROM files f WHERE "
                        + where
                        + " ORDER BY "
                        + order
                        + " LIMIT ? OFFSET ?",
                        [*args, limit, offset],
                    )
                ]
                return {
                    "files": rows,
                    "total": counts[0],
                    "size": counts[1],
                    "offset": offset,
                    "limit": limit,
                    "revision": self.revision(),
                }
            finally:
                c.execute("ROLLBACK")


READER = CatalogReader()
