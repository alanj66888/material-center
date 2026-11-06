#!/usr/bin/env python3
"""Local media index, shared tags, recoverable deletion, and media previews."""
import argparse
from contextlib import contextmanager
import json
import mimetypes
import os
import re
import secrets
import sys
import stat
import sqlite3
import subprocess
import threading
import time
import webbrowser
import uuid
import signal
from concurrent.futures import TimeoutError as PreviewTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from app_version import VERSION
from runtime_support import configure_media_libraries

configure_media_libraries()
from library_features import (
    LibraryFeatures,
    LOCK as FEATURE_LOCK,
    initialize as initialize_features,
    labels,
)
from media_support import MediaSupport, capabilities, stop_processes
from preview_jobs import PREVIEWS, PreviewJobs, PreviewBusy
import cache_maintenance
from catalog_index import (
    configure as configure_catalog,
    initialize as initialize_catalog,
    READER,
    CatalogChanged,
)
from scan_jobs import SCANS

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DATA = Path(
    os.environ.get(
        "SUCAIYU_DATA_DIR", str(Path(__file__).resolve().parent / ".library")
    )
)
EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".mkv",
    ".avi",
    ".mpg",
    ".mpeg",
    ".mts",
    ".m2ts",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".avif",
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
}
IMAGES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif"}
AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def suffixes(value):
    return {"." + ext for ext in value.split()}


IMAGES |= suffixes(
    "3fr erf kdc mrw mos mef dcr iiq rwl k25 bay ptx cap gpr fff arq tif tiff heic heif raw dng cr2 cr3 nef nrw arw srf sr2 raf orf rw2 pef srw x3f psd psb ai eps svg svgz ps ico icns tga exr hdr jxl jp2 j2k dds ktx"
)
AUDIO |= suffixes(
    "aif aiff aifc wma opus ape alac amr ac3 dts mid midi caf mka aiff bwf pcm"
)
VIDEO = suffixes(
    "mp4 mov m4v webm mkv avi mpg mpeg mts m2ts ts mxf r3d braw crm ari cine dpx prores 3gp 3g2 flv f4v wmv asf vob ogv m2v divx rm rmvb dv av1"
)
DOCUMENTS = suffixes(
    "pdf txt md rtf doc docx xls xlsx csv tsv ppt pptx pages numbers key epub srt ass ssa vtt lrc"
)
FONTS = suffixes("ttf otf ttc woff woff2 eot")
PROJECTS = suffixes(
    "aep aepx prproj drp dra fcpxml fcpbundle blend c4d max ma mb obj fbx stl gltf glb usd usdz skp sketch fig afdesign afphoto indd idml"
)
ARCHIVES = suffixes("zip rar 7z tar gz bz2 xz tgz dmg iso")


def file_kind(ext):
    for kind, extensions in [
        ("image", IMAGES),
        ("audio", AUDIO),
        ("video", VIDEO),
        ("document", DOCUMENTS),
        ("font", FONTS),
        ("project", PROJECTS),
        ("archive", ARCHIVES),
    ]:
        if ext in extensions:
            return kind
    return "other"


TOKEN = secrets.token_urlsafe(32)
SCAN_LOCK = threading.Lock()
CACHED_CAPABILITIES = capabilities()
TRASH_COUNTS = {}
PROXIES = PreviewJobs(workers=1, pending=2)


@contextmanager
def db():
    c = sqlite3.connect(DATA / "library.sqlite3", timeout=30)
    c.row_factory = sqlite3.Row
    configure_catalog(c)
    c.execute("PRAGMA busy_timeout=5000")
    try:
        with c:
            yield c
    finally:
        c.close()


def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=FULL")
        c.executescript(
            """CREATE TABLE IF NOT EXISTS roots(id INTEGER PRIMARY KEY, path TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, root INTEGER, path TEXT UNIQUE,
        name TEXT, folder TEXT, ext TEXT, kind TEXT, size INTEGER, modified REAL,
        favorite INTEGER DEFAULT 0, tags TEXT DEFAULT '', missing INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS directories(root INTEGER, folder TEXT, PRIMARY KEY(root,folder));"""
        )
        initialize_features(c)
        initialize_catalog(c)
        # Populate old libraries without requiring a scan before browsing folders.
        for row in c.execute(
            "SELECT DISTINCT root,folder FROM files WHERE missing=0"
        ).fetchall():
            parts = Path(row["folder"]).parts
            for length in range(1, len(parts) + 1):
                c.execute(
                    "INSERT OR IGNORE INTO directories VALUES(?,?)",
                    (row["root"], Path(*parts[:length]).as_posix()),
                )


def scan(path, progress=None):
    report = progress or (lambda **values: None)
    if not SCAN_LOCK.acquire(blocking=False):
        raise ValueError("已有扫描任务正在运行")
    staging = None
    try:
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("文件夹不存在或无法读取，请检查路径。")
        if not os.access(root, os.R_OK | os.X_OK):
            raise ValueError("没有读取此文件夹的权限。")
        staging = DATA / ("scan-stage-" + uuid.uuid4().hex + ".sqlite3")
        temporary = sqlite3.connect(staging)
        temporary.executescript(
            "PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; CREATE TABLE items(path TEXT PRIMARY KEY,name TEXT,folder TEXT,ext TEXT,kind TEXT,size INTEGER,modified REAL); CREATE TABLE dirs(folder TEXT PRIMARY KEY);"
        )
        count = 0
        directory_count = 0
        batch = []
        pending = [(root, ".")]
        last_report = 0
        try:
            while pending:
                directory, relative = pending.pop()
                temporary.execute("INSERT INTO dirs VALUES(?)", (relative,))
                directory_count += 1
                try:
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            if entry.name.startswith(".") or entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name.casefold() not in {
                                    "#recycle",
                                    "#snapshot",
                                    "@eadir",
                                    "@recycle",
                                    "$recycle.bin",
                                    "system volume information",
                                }:
                                    pending.append(
                                        (
                                            Path(entry.path),
                                            entry.name
                                            if relative == "."
                                            else relative + "/" + entry.name,
                                        )
                                    )
                                continue
                            status = entry.stat(follow_symlinks=False)
                            if not stat.S_ISREG(status.st_mode):
                                continue
                            extension = Path(entry.name).suffix.lower()
                            batch.append(
                                (
                                    entry.path,
                                    entry.name,
                                    relative,
                                    extension[1:],
                                    file_kind(extension),
                                    status.st_size,
                                    status.st_mtime,
                                )
                            )
                            count += 1
                            if len(batch) >= 1000:
                                temporary.executemany(
                                    "INSERT INTO items VALUES(?,?,?,?,?,?,?)", batch
                                )
                                batch.clear()
                            if time.monotonic() - last_report > 0.3:
                                report(
                                    phase="walking",
                                    files=count,
                                    directories=directory_count,
                                )
                                last_report = time.monotonic()
                except OSError as error:
                    raise ValueError(
                        "无法读取目录或文件：" + str(error.filename or directory)
                    ) from error
            if batch:
                temporary.executemany("INSERT INTO items VALUES(?,?,?,?,?,?,?)", batch)
            temporary.commit()
        finally:
            temporary.close()
        report(phase="publishing", files=count, directories=directory_count)
        # Network walking above never holds the live database's writer lock. Publish
        # a complete generation in one transaction, preserving favorites and tags.
        with FEATURE_LOCK, db() as c:
            c.execute("ATTACH DATABASE ? AS scan_stage", (str(staging),))
            c.execute("INSERT OR IGNORE INTO roots(path) VALUES(?)", (str(root),))
            rid = c.execute(
                "SELECT id FROM roots WHERE path=?", (str(root),)
            ).fetchone()[0]
            c.execute(
                "UPDATE files SET missing=1 WHERE root=? AND missing=0 AND NOT EXISTS(SELECT 1 FROM scan_stage.items s WHERE s.path=files.path)",
                (rid,),
            )
            c.execute(
                "DELETE FROM directories WHERE root=? AND NOT EXISTS(SELECT 1 FROM scan_stage.dirs s WHERE s.folder=directories.folder)",
                (rid,),
            )
            c.execute(
                "INSERT OR IGNORE INTO directories SELECT ?,folder FROM scan_stage.dirs",
                (rid,),
            )
            c.execute(
                """INSERT INTO files(root,path,name,folder,ext,kind,size,modified)
              SELECT ?,path,name,folder,ext,kind,size,modified FROM scan_stage.items WHERE 1
              ON CONFLICT(path) DO UPDATE SET root=excluded.root,name=excluded.name,folder=excluded.folder,
              ext=excluded.ext,kind=excluded.kind,size=excluded.size,modified=excluded.modified,missing=0
              WHERE files.root!=excluded.root OR files.name!=excluded.name OR files.folder!=excluded.folder
              OR files.ext!=excluded.ext OR files.kind!=excluded.kind OR files.size!=excluded.size OR files.modified!=excluded.modified OR files.missing!=0""",
                (rid,),
            )
        return count
    finally:
        if staging:
            staging.unlink(missing_ok=True)
        SCAN_LOCK.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def allowed_request(self):
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected:
            self.reply({"error": "Host rejected"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + expected:
            self.reply({"error": "Origin rejected"}, 403)
            return False
        return True

    def do_GET(self):
        if not self.allowed_request():
            return
        try:
            self.get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (PreviewBusy, PreviewTimeout) as e:
            self.reply({"error": str(e) or "正在生成预览，稍后重试", "pending": True}, 429)
        except Exception as e:
            self.reply({"error": str(e)}, 500)

    def get(self):
        url = urlparse(self.path)
        if url.path == "/api/health":
            return self.reply({"app": "sucaiyu", "version": VERSION})
        if url.path == "/api/catalog":
            snapshot = READER.catalog(DATA)
            return self.reply(
                {
                    **snapshot,
                    "token": TOKEN,
                    "version": VERSION,
                    "capabilities": CACHED_CAPABILITIES,
                    "test_mode": os.environ.get("SUCAIYU_TEST_MODE") == "1",
                    "scan": SCANS.status(),
                    "trash_count": TRASH_COUNTS.get(str(DATA)),
                }
            )
        if url.path == "/api/items":
            try:
                return self.reply(
                    READER.items(DATA, parse_qs(url.query, keep_blank_values=True))
                )
            except CatalogChanged as error:
                return self.reply({"error": str(error), "code": "catalog_changed"}, 409)
        if url.path == "/api/scan-status":
            return self.reply(SCANS.status(parse_qs(url.query).get("id", [None])[0]))
        if url.path == "/api/library":
            with FEATURE_LOCK, db() as c:
                features = LibraryFeatures(c)
                features.refresh_trash()
                roots = [{**dict(r), **features.status(r)} for r in features.roots()]
                entries, trash_errors = features.trash_entries()
                self.reply(
                    {
                        "roots": roots,
                        "trash_count": len(entries),
                        "trash_errors": trash_errors,
                        "version": VERSION,
                        "capabilities": capabilities(),
                        "test_mode": os.environ.get("SUCAIYU_TEST_MODE") == "1",
                        "directories": [
                            dict(r) for r in c.execute("SELECT * FROM directories")
                        ],
                        "files": [
                            dict(r)
                            for r in c.execute("SELECT * FROM files WHERE missing=0")
                        ],
                        "token": TOKEN,
                    }
                )
            return
        if url.path == "/api/trash":
            with FEATURE_LOCK, db() as c:
                entries, errors = LibraryFeatures(c).trash_entries()
                TRASH_COUNTS[str(DATA)] = len(entries)
                return self.reply(
                    {
                        "items": sorted(
                            entries, key=lambda row: row["deleted"], reverse=True
                        ),
                        "errors": errors,
                    }
                )
        if url.path.startswith("/trash-preview/"):
            parts = url.path.split("/")
            if len(parts) != 5:
                return self.reply({"error": "Not found"}, 404)
            _, _, root, identifier, action = parts
            with FEATURE_LOCK, db() as c:
                try:
                    item = LibraryFeatures(c).find_trash(root, identifier)
                except ValueError as error:
                    return self.reply({"error": str(error)}, 404)
            row = {**item, "path": item["payload"]}
            media = MediaSupport(DATA)
            if action == "metadata":
                return self.reply(media.metadata(row))
            if action == "frame":
                if row["kind"] != "video":
                    return self.reply({"error": "仅视频支持滑动预览"}, 400)
                path = media.frame(row, parse_qs(url.query).get("position", ["0"])[0])
            elif action == "poster":
                path = media.poster(row)
            elif action == "media":
                path = Path(row["path"])
            elif action == "compatible":
                path = media.folder(row) / "compatible.mp4"
            else:
                return self.reply({"error": "Not found"}, 404)
            if not path.is_file():
                return self.reply({"error": "预览不存在"}, 404)
            return self.send_file(path, media=True)
        if url.path.startswith(
            ("/api/metadata/", "/preview-image/", "/compatible/", "/preview-frame/")
        ):
            with db() as c:
                row = c.execute(
                    "SELECT * FROM files WHERE id=? AND missing=0",
                    (int(url.path.rsplit("/", 1)[-1]),),
                ).fetchone()
            if not row:
                return self.reply({"error": "素材已移走或在回收站中"}, 404)
            media = MediaSupport(DATA)
            folder = media.folder(row)
            query = parse_qs(url.query)
            client = query.get("client", [None])[0]
            interactive = query.get("interactive", ["0"])[0] == "1"
            action = (
                "metadata"
                if url.path.startswith("/api/metadata/")
                else "frame"
                if url.path.startswith("/preview-frame/")
                else "poster"
                if url.path.startswith("/preview-image/")
                else "compatible"
            )
            position = max(0, min(80, int(query.get("position", ["0"])[0])))
            target = folder / (
                "metadata.json"
                if action == "metadata"
                else f"frame-{position}.jpg"
                if action == "frame"
                else "poster.jpg"
                if action == "poster"
                else "compatible.mp4"
            )
            if action == "compatible":
                if not target.is_file():
                    return self.reply({"error": "请先生成兼容预览"}, 404)
                return self.send_file(target, media=True)
            if target.is_file():
                return (
                    self.reply(json.loads(target.read_text()))
                    if action == "metadata"
                    else self.send_file(target, media=True)
                )
            task = (
                (lambda: media.metadata(row))
                if action == "metadata"
                else (lambda: media.frame(row, position))
                if action == "frame"
                else (lambda: media.poster(row))
            )
            future = PREVIEWS.submit(
                (str(target),),
                row["id"],
                task,
                client,
                interactive,
                priority=0
                if interactive or action == "frame"
                else 1
                if action == "metadata"
                else 2,
            )
            result = future.result(timeout=0.08 if client else 65)
            return (
                self.reply(result)
                if action == "metadata"
                else self.send_file(result, media=True)
            )
        if url.path.startswith("/media/"):
            with db() as c:
                row = c.execute(
                    "SELECT path FROM files WHERE id=? AND missing=0",
                    (url.path.split("/")[-1],),
                ).fetchone()
            if not row or not Path(row["path"]).is_file():
                return self.reply({"error": "素材已移动或所在磁盘未连接，请重新扫描。"}, 404)
            return self.send_file(Path(row["path"]), media=True)
        static = {
            "/": "index.html",
            "/app.js": "app.js",
            "/style.css": "style.css",
            "/library.js": "library.js",
            "/app-icon.png": "app-icon.png",
            "/features.js": "features.js",
            "/preferences.js": "preferences.js",
            "/catalog.js": "catalog.js",
            "/selection.js": "selection.js",
            "/icon-light.png": "icon-light.png",
            "/icon-dark.png": "icon-dark.png",
        }
        if url.path in static:
            return self.send_file(BASE / "web" / static[url.path])
        self.reply({"error": "Not found"}, 404)

    def send_file(self, path, media=False):
        size = path.stat().st_size
        start, end = 0, size - 1
        partial = False
        raw = self.headers.get("Range") if media else None
        if raw:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", raw)
            if not match or not any(match.groups()):
                return self.reply({"error": "Invalid range"}, 416)
            a, b = match.groups()
            if a:
                start, end = int(a), min(int(b), end) if b else end
            else:
                start = max(0, size - int(b))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            partial = True
        self.send_response(206 if partial else 200)
        self.send_header(
            "Content-Type",
            mimetypes.guess_type(str(path))[0] or "application/octet-stream",
        )
        self.send_header("Content-Length", str(max(0, end - start + 1)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if media:
            self.send_header("Content-Security-Policy", "sandbox; default-src 'none'")
        self.send_header(
            "Cache-Control", "private, max-age=3600" if media else "no-cache"
        )
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_POST(self):
        if not self.allowed_request():
            return
        if self.headers.get("X-Library-Token") != TOKEN:
            return self.reply({"error": "请刷新页面重试。"}, 403)
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 <= length <= 65536:
                raise ValueError("请求过大")
            body = json.loads(self.rfile.read(length) or "{}")
            if not isinstance(body, dict):
                raise ValueError("请求格式错误")
            if self.path == "/api/choose":
                result = subprocess.run(
                    [
                        "osascript",
                        "-e",
                        'tell application "System Events"\nactivate\nset chosenFolder to choose folder with prompt "选择素材文件夹（只建立索引，不移动文件）"\nreturn POSIX path of chosenFolder\nend tell',
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                if result.returncode:
                    if "-128" in result.stderr:
                        return self.reply({"path": ""})
                    raise ValueError("系统文件夹选择器无法打开。" + result.stderr.strip()[:250])
                return self.reply({"path": result.stdout.strip()})
            if self.path == "/api/scan-start":
                path = body.get("path")
                if not isinstance(path, str) or not path.strip() or len(path) > 4096:
                    raise ValueError("文件夹路径无效")
                return self.reply(SCANS.start(path, scan))
            if self.path == "/api/scan":
                return self.reply({"count": scan(body["path"])})
            if self.path == "/api/trash-prepare":
                with FEATURE_LOCK, db() as c:
                    item = LibraryFeatures(c).find_trash(body["root"], body["id"])
                MediaSupport(DATA).proxy({**item, "path": item["payload"]})
                return self.reply(
                    {"url": f"/trash-preview/{item['root']}/{item['id']}/compatible"}
                )
            if self.path == "/api/preview-focus":
                client = body.get("client")
                ids = body.get("ids", [])
                if (
                    not isinstance(client, str)
                    or not re.fullmatch("[A-Za-z0-9:-]{1,80}", client)
                    or not isinstance(ids, list)
                    or len(ids) > 500
                ):
                    raise ValueError("预览范围无效")
                PREVIEWS.focus(client, [int(identifier) for identifier in ids])
                PROXIES.focus(client, [int(identifier) for identifier in ids])
                return self.reply({"ok": True})
            if self.path == "/api/prepare":
                with db() as c:
                    row = c.execute(
                        "SELECT * FROM files WHERE id=? AND missing=0",
                        (int(body["id"]),),
                    ).fetchone()
                if not row:
                    raise ValueError("素材不存在")
                media = MediaSupport(DATA)
                target = media.folder(row) / "compatible.mp4"
                client = body.get("client")
                if not target.is_file():
                    future = PROXIES.submit(
                        (str(target),),
                        row["id"],
                        lambda: media.proxy(
                            row,
                            cancelled=lambda: client
                            and not PROXIES.wanted(client, row["id"]),
                        ),
                        client=client,
                    )
                    try:
                        future.result(timeout=0.08 if body.get("async") else 610)
                    except PreviewTimeout:
                        return self.reply({"pending": True}, 202)
                return self.reply({"url": "/compatible/" + str(row["id"])})
            if self.path == "/api/shared-enable":
                with FEATURE_LOCK, db() as c:
                    LibraryFeatures(c).enable(body["root"])
                return self.reply({"ok": True})
            if self.path == "/api/sync-tags":
                changed = False
                errors = []
                with db() as c:
                    features = LibraryFeatures(c)
                    for root in features.roots():
                        try:
                            changed = (
                                features.synchronize(
                                    root, force=bool(body.get("force"))
                                )
                                or changed
                            )
                        except (OSError, ValueError) as error:
                            c.execute(
                                "INSERT OR IGNORE INTO shared_roots(root) VALUES(?)",
                                (root["id"],),
                            )
                            c.execute(
                                "UPDATE shared_roots SET error=? WHERE root=?",
                                (str(error), root["id"]),
                            )
                            errors.append({"root": root["id"], "error": str(error)})
                        c.commit()
                    changed = features.refresh_trash() or changed
                    count = len(features.trash_entries()[0])
                    TRASH_COUNTS[str(DATA)] = count
                return self.reply(
                    {"changed": changed, "errors": errors, "trash_count": count}
                )
            if self.path in ("/api/recycle", "/api/restore", "/api/purge"):
                selected = body.get(
                    "ids" if self.path.endswith("recycle") else "items", []
                )
                if not isinstance(selected, list) or not 1 <= len(selected) <= 5000:
                    raise ValueError("请选择 1 到 5000 个素材")
                with FEATURE_LOCK, db() as c:
                    features = LibraryFeatures(c)
                    if self.path.endswith("recycle"):
                        result = features.recycle(
                            list(dict.fromkeys(int(fid) for fid in selected))
                        )
                    elif self.path.endswith("restore"):
                        result = features.restore(selected)
                    else:
                        result = features.purge(selected, body.get("confirmation"))
                return self.reply(result)
            if self.path == "/api/update":
                with FEATURE_LOCK, db() as c:
                    row = c.execute(
                        "SELECT * FROM files WHERE id=?", (int(body["id"]),)
                    ).fetchone()
                    if not row:
                        raise ValueError("素材不存在")
                    actual = row["tags"]
                    if "tags" in body:
                        values = LibraryFeatures(c).set_tags(
                            [
                                (
                                    row["id"],
                                    labels(str(body["tags"])[:2000]),
                                    body.get("base_tags"),
                                )
                            ]
                        )
                        actual = values[row["id"]]
                    if "favorite" in body:
                        c.execute(
                            "UPDATE files SET favorite=? WHERE id=?",
                            (int(bool(body["favorite"])), row["id"]),
                        )
                return self.reply({"ok": True, "tags": actual})
            if self.path == "/api/tags":
                ids = list({int(i) for i in body["ids"]})
                tags = [str(t).strip() for t in body["tags"] if str(t).strip()]
                if not ids or not tags or len(ids) > 5000:
                    raise ValueError("请选择 1 到 5000 个素材，并输入标签")
                with FEATURE_LOCK, db() as c:
                    actual = LibraryFeatures(c).set_tags(
                        [(fid, tags, None) for fid in ids], append=True
                    )
                return self.reply({"ok": True, "tags": actual})
            if self.path in ("/api/reveal", "/api/open"):
                with db() as c:
                    row = c.execute(
                        "SELECT path FROM files WHERE id=?", (int(body["id"]),)
                    ).fetchone()
                if not row or not Path(row["path"]).is_file():
                    raise ValueError("找不到原文件")
                if sys.platform == "win32":
                    if self.path.endswith("reveal"):
                        subprocess.Popen(["explorer.exe", "/select," + row["path"]])
                    else:
                        os.startfile(row["path"])
                elif sys.platform == "darwin":
                    subprocess.Popen(
                        ["open", "-R", row["path"]]
                        if self.path.endswith("reveal")
                        else ["open", row["path"]]
                    )
                else:
                    subprocess.Popen(
                        [
                            "xdg-open",
                            str(Path(row["path"]).parent)
                            if self.path.endswith("reveal")
                            else row["path"],
                        ]
                    )
                return self.reply({"ok": True})
            if self.path == "/api/remove":
                with db() as c:
                    c.execute("DELETE FROM files WHERE root=?", (int(body["id"]),))
                    c.execute(
                        "DELETE FROM directories WHERE root=?", (int(body["id"]),)
                    )
                    c.execute("DELETE FROM roots WHERE id=?", (int(body["id"]),))
                    c.execute(
                        "DELETE FROM shared_roots WHERE root=?", (int(body["id"]),)
                    )
                return self.reply({"ok": True})
            self.reply({"error": "Not found"}, 404)
        except (PreviewBusy, PreviewTimeout) as e:
            self.reply({"error": str(e) or "正在生成预览", "pending": True}, 429)
        except Exception as e:
            self.reply({"error": str(e)}, 400)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--ready-file")
    parser.add_argument("--fallback-port", action="store_true")
    args = parser.parse_args()
    initialize()
    cache_maintenance.start(DATA)

    def terminate(*args):
        stop_processes()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        if not args.fallback_port:
            raise
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    if args.ready_file:
        ready = Path(args.ready_file)
        temporary = ready.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"url": url, "app": "sucaiyu", "version": VERSION, "pid": os.getpid()}
            ),
            encoding="utf-8",
        )
        temporary.replace(ready)
    print(f"素材中心已启动：{url}\n关闭此窗口或按 Ctrl+C 退出。", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if args.ready_file:
            Path(args.ready_file).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
