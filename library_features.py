"""NAS-safe tag operations and a recoverable, per-library file recycle bin."""
import errno
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import threading
import time
import unicodedata
import uuid

LOCK = threading.RLock()
EVENT_CACHE = {}
SYNC_SIGNATURES = {}
META = ".material-center"


def labels(value):
    return list(
        dict.fromkeys(
            tag.strip() for tag in re.split("[,，]", str(value)) if tag.strip()
        )
    )


def relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("素材相对路径无效")
    return unicodedata.normalize("NFC", path.as_posix())


def atomic_json(path, value):
    temporary = path.parent / ("." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def metadata_path(root, *parts, create=False):
    base = Path(root).resolve()
    current = base
    for component in (META, *parts):
        current = current / component
        if current.is_symlink() or not current.resolve().is_relative_to(base):
            raise ValueError("素材库管理目录包含不安全链接")
        if create:
            current.mkdir(exist_ok=True)
    return current


def initialize(connection):
    connection.executescript(
        """CREATE TABLE IF NOT EXISTS shared_roots(
        root INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 0, bootstrapped INTEGER DEFAULT 0,
        error TEXT DEFAULT '');"""
    )


class LibraryFeatures:
    def __init__(self, connection):
        self.c = connection

    def roots(self):
        return self.c.execute("SELECT * FROM roots").fetchall()

    def root(self, rid):
        row = self.c.execute("SELECT * FROM roots WHERE id=?", (int(rid),)).fetchone()
        if row is None:
            raise ValueError("素材库不存在")
        return row

    def enabled(self, root):
        row = self.c.execute(
            "SELECT enabled FROM shared_roots WHERE root=?", (root["id"],)
        ).fetchone()
        return (
            bool(row and row[0])
            or metadata_path(root["path"], "tags-v1", "config.json").is_file()
        )

    def status(self, root):
        row = self.c.execute(
            "SELECT error FROM shared_roots WHERE root=?", (root["id"],)
        ).fetchone()
        try:
            return {
                "shared_tags": self.enabled(root),
                "sync_error": row[0] if row else "",
            }
        except (OSError, ValueError) as error:
            return {"shared_tags": False, "sync_error": str(error)}

    def states(self, root):
        events = metadata_path(root["path"], "tags-v1", "events")
        states = {}
        if not events.is_dir():
            return states
        for directory_entry in os.scandir(events):
            entry = Path(directory_entry.path)
            if not re.fullmatch(r"[0-9a-f]{32}\.json", entry.name):
                continue
            if directory_entry.is_symlink():
                raise ValueError("共享标签记录不应为链接")
            key = (str(events), entry.name)
            operation = EVENT_CACHE.get(key)
            if operation is None:
                if entry.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("共享标签记录过大")
                operation = json.loads(entry.read_text(encoding="utf-8"))
                if operation.get("schema") != 1 or not isinstance(
                    operation.get("changes"), dict
                ):
                    raise ValueError("共享标签记录格式错误")
                for name, change in operation["changes"].items():
                    relative(name)
                    if not isinstance(change.get("adds"), dict) or not isinstance(
                        change.get("removes"), list
                    ):
                        raise ValueError("共享标签变更格式错误")
                    if any(
                        not re.fullmatch("[0-9a-f]{32}", token)
                        or not isinstance(tag, str)
                        or not tag
                        or len(tag) > 2000
                        for token, tag in change["adds"].items()
                    ):
                        raise ValueError("共享标签内容无效")
                    if any(
                        not isinstance(token, str)
                        or not re.fullmatch("[0-9a-f]{32}", token)
                        for token in change["removes"]
                    ):
                        raise ValueError("共享标签删除记录无效")
                EVENT_CACHE[key] = operation
            for name, change in operation["changes"].items():
                state = states.setdefault(
                    relative(name), {"adds": {}, "removes": set()}
                )
                state["adds"].update(change["adds"])
                state["removes"].update(change["removes"])
        return states

    @staticmethod
    def live(state):
        return sorted(
            {
                tag
                for token, tag in state["adds"].items()
                if token not in state["removes"]
            }
        )

    def publish(self, root, changes):
        if not changes:
            return
        folder = metadata_path(root["path"], "tags-v1", "events", create=True)
        items = list(changes.items())
        for start in range(0, len(items), 500):
            atomic_json(
                folder / (uuid.uuid4().hex + ".json"),
                {
                    "schema": 1,
                    "changes": dict(items[start : start + 500]),
                    "created": time.time(),
                },
            )

    def synchronize(self, root, force=False):
        if not self.enabled(root):
            return False
        if not Path(root["path"]).is_dir():
            raise ValueError("NAS 或素材盘未连接，共享标签暂未更新")
        current = self.c.execute(
            "SELECT bootstrapped FROM shared_roots WHERE root=?", (root["id"],)
        ).fetchone()
        first = not current or not current[0]
        database = self.c.execute("PRAGMA database_list").fetchone()[2]
        events = metadata_path(root["path"], "tags-v1", "events")
        signature = (
            tuple(
                sorted(
                    entry.name
                    for entry in os.scandir(events)
                    if re.fullmatch("[0-9a-f]{32}\.json", entry.name)
                )
            )
            if events.is_dir()
            else ()
        )
        key = (database, root["path"])
        if not force and not first and SYNC_SIGNATURES.get(key) == signature:
            self.c.execute(
                "UPDATE shared_roots SET error='' WHERE root=? AND error!=''",
                (root["id"],),
            )
            return False
        # Capture local values before network reads; a concurrent edit cannot be
        # replaced by an older remote snapshot after the read completes.
        version = self.c.execute("PRAGMA data_version").fetchone()[0]
        rows = self.c.execute(
            "SELECT id,path,tags FROM files WHERE root=?", (root["id"],)
        ).fetchall()
        states = self.states(root)
        if first:
            changes = {}
            for row in rows:
                relative_path = relative(
                    Path(row["path"]).relative_to(root["path"]).as_posix()
                )
                existing = set(
                    self.live(states.get(relative_path, {"adds": {}, "removes": set()}))
                )
                additions = {
                    uuid.uuid4().hex: tag
                    for tag in labels(row["tags"])
                    if tag not in existing
                }
                if additions:
                    changes[relative_path] = {"adds": additions, "removes": []}
            self.publish(root, changes)
            if changes:
                states = self.states(root)
        if self.c.execute("PRAGMA data_version").fetchone()[0] != version:
            return False
        self.c.execute(
            "INSERT OR IGNORE INTO shared_roots(root,enabled,bootstrapped) VALUES(?,1,1)",
            (root["id"],),
        )
        self.c.execute(
            "UPDATE shared_roots SET enabled=1,bootstrapped=1 WHERE root=? AND (enabled!=1 OR bootstrapped!=1)",
            (root["id"],),
        )
        changed = False
        for row in rows:
            relative_path = relative(
                Path(row["path"]).relative_to(root["path"]).as_posix()
            )
            if relative_path not in states:
                continue
            value = ", ".join(self.live(states[relative_path]))
            if value != row["tags"]:
                changed = (
                    bool(
                        self.c.execute(
                            "UPDATE files SET tags=? WHERE id=? AND tags=?",
                            (value, row["id"], row["tags"]),
                        ).rowcount
                    )
                    or changed
                )
        self.c.execute(
            "UPDATE shared_roots SET error='' WHERE root=? AND error!=''", (root["id"],)
        )
        SYNC_SIGNATURES[key] = signature
        return changed

    def enable(self, rid):
        root = self.root(rid)
        folder = metadata_path(root["path"], "tags-v1", create=True)
        config = folder / "config.json"
        if not config.exists():
            atomic_json(config, {"schema": 1, "enabled": True})
        self.synchronize(root)

    def set_tags(self, updates, append=False):
        grouped = {}
        for fid, requested, baseline in updates:
            row = self.c.execute(
                "SELECT * FROM files WHERE id=?", (int(fid),)
            ).fetchone()
            if row is None:
                raise ValueError("素材不存在")
            grouped.setdefault(row["root"], []).append(
                (row, list(dict.fromkeys(requested)), baseline)
            )
        result = {}
        for rid, items in grouped.items():
            root = self.root(rid)
            shared = self.enabled(root)
            if shared:
                self.synchronize(root, force=True)
                self.c.commit()  # Do not keep a SQLite write lock during NAS reads.
            states = self.states(root) if shared else {}
            changes = {}
            for row, requested, baseline in items:
                current = self.c.execute(
                    "SELECT tags FROM files WHERE id=?", (row["id"],)
                ).fetchone()[0]
                if shared:
                    relative_path = relative(
                        Path(row["path"]).relative_to(root["path"]).as_posix()
                    )
                    if relative_path in states:
                        current = ", ".join(self.live(states[relative_path]))
                desired = list(
                    dict.fromkeys((labels(current) if append else []) + requested)
                )
                if baseline is not None and not append:
                    base = set(labels(baseline))
                    wanted = set(requested)
                    desired = list(
                        (set(labels(current)) - (base - wanted)) | (wanted - base)
                    )
                if len(", ".join(desired)) > 2000:
                    raise ValueError("标签总长度不能超过 2000 个字符")
                if shared:
                    key = relative(
                        Path(row["path"]).relative_to(root["path"]).as_posix()
                    )
                    state = states.get(key, {"adds": {}, "removes": set()})
                    active = {
                        token: tag
                        for token, tag in state["adds"].items()
                        if token not in state["removes"]
                    }
                    changes[key] = {
                        "adds": {
                            uuid.uuid4().hex: tag
                            for tag in desired
                            if tag not in active.values()
                        },
                        "removes": [
                            token for token, tag in active.items() if tag not in desired
                        ],
                    }
                result[row["id"]] = ", ".join(sorted(desired))
            # Publish before acknowledging success. Unavailable NAS does not silently save a local-only edit.
            if shared:
                self.publish(root, changes)
            for row, _, _ in items:
                self.c.execute(
                    "UPDATE files SET tags=? WHERE id=?", (result[row["id"]], row["id"])
                )
        return result

    def trash_entries(self, include_restored=False):
        entries = []
        errors = []
        for root in self.roots():
            try:
                folder = metadata_path(root["path"], "trash")
                if not folder.is_dir():
                    continue
                for item in folder.iterdir():
                    if not re.fullmatch("[0-9a-f]{32}", item.name):
                        continue
                    if item.is_symlink() or not item.resolve().is_relative_to(
                        folder.resolve()
                    ):
                        raise ValueError("回收站目录包含不安全链接")
                    manifest = item / "manifest.json"
                    if not manifest.is_file() or manifest.is_symlink():
                        continue
                    if manifest.stat().st_size > 65536:
                        raise ValueError("回收站记录过大")
                    record = json.loads(manifest.read_text(encoding="utf-8"))
                    relative(record["relative"])
                    filename = record["name"]
                    if (
                        filename != Path(filename).name
                        or "/" in filename
                        or "\\" in filename
                    ):
                        raise ValueError("回收站文件名无效")
                    payload_name = record.get("payload_name", filename)
                    if (
                        payload_name != Path(payload_name).name
                        or "/" in payload_name
                        or "\\" in payload_name
                    ):
                        raise ValueError("回收站存储名无效")
                    payload = item / payload_name
                    if payload.is_symlink():
                        raise ValueError("回收站素材不应为链接")
                    record.update(
                        id=item.name,
                        root=root["id"],
                        root_name=Path(root["path"]).name,
                        root_path=root["path"],
                        payload=str(payload),
                        directory=str(item),
                    )
                    if payload.is_file():
                        record["state"] = "trashed"
                        entries.append(record)
                    elif include_restored and record.get("state") == "restored":
                        entries.append(record)
            except (OSError, ValueError, KeyError) as error:
                errors.append(str(error))
        return entries, errors

    def refresh_trash(self):
        version = self.c.execute("PRAGMA data_version").fetchone()[0]
        entries, _ = self.trash_entries(include_restored=True)
        updates = []
        for item in entries:
            original = self.original(item)
            row = self.c.execute(
                "SELECT id,missing FROM files WHERE path=?", (str(original),)
            ).fetchone()
            if not row:
                continue
            exists = original.is_file()
            missing = (
                0
                if item["state"] == "restored" and exists
                else 1
                if not exists
                else row["missing"]
            )
            if missing != row["missing"]:
                updates.append((missing, row["id"], row["missing"]))
        if self.c.execute("PRAGMA data_version").fetchone()[0] != version:
            return False
        self.c.executemany(
            "UPDATE files SET missing=? WHERE id=? AND missing=?", updates
        )
        return bool(updates)

    @staticmethod
    def original(item):
        root = Path(item["root_path"]).resolve()
        path = root / PurePosixPath(item["relative"])
        if not path.resolve().is_relative_to(root):
            raise ValueError("原位置包含不安全链接，无法还原")
        return path

    def recycle(self, ids):
        result = []
        errors = []
        for fid in ids:
            try:
                row = self.c.execute(
                    "SELECT * FROM files WHERE id=? AND missing=0", (int(fid),)
                ).fetchone()
                if not row:
                    raise ValueError("素材不存在或已移入回收站")
                root = self.root(row["root"])
                source = Path(row["path"])
                relative(source.relative_to(root["path"]).as_posix())
                if "\\" in source.name:
                    raise ValueError("此文件名不适合跨平台回收站，未移动文件")
                if (
                    source.is_symlink()
                    or not source.is_file()
                    or not source.resolve().is_relative_to(Path(root["path"]).resolve())
                ):
                    raise ValueError("素材不存在或路径不安全")
                folder = (
                    metadata_path(root["path"], "trash", create=True) / uuid.uuid4().hex
                )
                folder.mkdir()
                record = {
                    "schema": 1,
                    "relative": source.relative_to(root["path"]).as_posix(),
                    "name": source.name,
                    "size": row["size"],
                    "modified": row["modified"],
                    "kind": row["kind"],
                    "ext": row["ext"],
                    "tags": row["tags"],
                    "favorite": row["favorite"],
                    "deleted": time.time(),
                    "state": "pending",
                    "payload_name": "content" + source.suffix,
                }
                atomic_json(folder / "manifest.json", record)
                try:
                    os.rename(source, folder / record["payload_name"])
                except OSError:
                    (folder / "manifest.json").unlink()
                    folder.rmdir()
                    raise
                # The manifest is already durable: a crash here is recoverable by payload existence.
                record["state"] = "trashed"
                atomic_json(folder / "manifest.json", record)
                self.c.execute("UPDATE files SET missing=1 WHERE id=?", (row["id"],))
                result.append(fid)
            except (OSError, ValueError) as error:
                errors.append({"id": fid, "error": str(error)})
        return {"processed": result, "errors": errors}

    def find_trash(self, rid, identifier):
        if not re.fullmatch("[0-9a-f]{32}", str(identifier)):
            raise ValueError("回收站编号无效")
        entries, _ = self.trash_entries()
        item = next(
            (
                item
                for item in entries
                if item["root"] == int(rid) and item["id"] == identifier
            ),
            None,
        )
        if not item:
            raise ValueError("回收站素材不存在，可能已被另一台电脑处理")
        return item

    def restore(self, items):
        result = []
        errors = []
        for selected in items:
            try:
                item = self.find_trash(selected["root"], selected["id"])
                source = Path(item["payload"])
                target = self.original(item)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise ValueError("原位置已有同名文件，未覆盖；请先处理同名文件后重试")
                try:
                    os.link(source, target)
                except OSError as error:
                    if error.errno == errno.EEXIST:
                        raise ValueError("原位置已有同名文件，未覆盖")
                    # Filesystems without hard links: exclusive copy, then remove the recycled source.
                    created = False
                    try:
                        with target.open("xb") as output:
                            created = True
                            with source.open("rb") as original:
                                shutil.copyfileobj(original, output, 1024 * 1024)
                            output.flush()
                            os.fsync(output.fileno())
                    except BaseException:
                        if created:
                            target.unlink(missing_ok=True)
                        raise
                try:
                    shutil.copystat(source, target)
                except OSError:
                    pass
                source.unlink()
                item["state"] = "restored"
                atomic_json(
                    Path(item["directory"]) / "manifest.json",
                    {
                        key: value
                        for key, value in item.items()
                        if key
                        not in [
                            "id",
                            "root",
                            "root_name",
                            "root_path",
                            "payload",
                            "directory",
                        ]
                    },
                )
                status = target.stat()
                folder = target.parent.relative_to(item["root_path"]).as_posix()
                self.c.execute(
                    """INSERT INTO files(root,path,name,folder,ext,kind,size,modified,favorite,tags)
                    VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET missing=0,size=excluded.size,modified=excluded.modified""",
                    (
                        item["root"],
                        str(target),
                        target.name,
                        folder,
                        item["ext"],
                        item["kind"],
                        status.st_size,
                        status.st_mtime,
                        item["favorite"],
                        item["tags"],
                    ),
                )
                for parent in [PurePosixPath(folder), *PurePosixPath(folder).parents]:
                    self.c.execute(
                        "INSERT OR IGNORE INTO directories VALUES(?,?)",
                        (item["root"], str(parent)),
                    )
                result.append(selected)
            except (OSError, ValueError) as error:
                errors.append({"id": selected.get("id"), "error": str(error)})
        return {"processed": result, "errors": errors}

    def purge(self, items, confirmation):
        if confirmation != "PERMANENTLY_DELETE":
            raise ValueError("彻底删除需要明确确认")
        result = []
        errors = []
        for selected in items:
            try:
                item = self.find_trash(selected["root"], selected["id"])
                Path(item["payload"]).unlink()
                (Path(item["directory"]) / "manifest.json").unlink()
                Path(item["directory"]).rmdir()
                result.append(selected)
            except (OSError, ValueError) as error:
                errors.append({"id": selected.get("id"), "error": str(error)})
        return {"processed": result, "errors": errors}
