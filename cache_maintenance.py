"""Size-bounded local preview cache. Never traverses original media directories."""
from contextlib import contextmanager
from pathlib import Path
import os
import re
import shutil
import threading
import time

LOCK = threading.Lock()
ACTIVE = {}
TOUCHED = {}


@contextmanager
def pin(folder):
    key = str(folder)
    with LOCK:
        ACTIVE[key] = ACTIVE.get(key, 0) + 1
    try:
        yield
    finally:
        with LOCK:
            ACTIVE[key] -= 1
            if not ACTIVE[key]:
                ACTIVE.pop(key, None)


def touch(folder):
    key = str(folder)
    now = time.monotonic()
    with LOCK:
        if now - TOUCHED.get(key, 0) < 60:
            return
        TOUCHED[key] = now
        while len(TOUCHED) > 8192:
            TOUCHED.pop(next(iter(TOUCHED)))
    try:
        os.utime(folder, None)
    except OSError:
        pass


def trim(data, limit=6 * 1024**3, min_age=300):
    cache = Path(data) / "preview-cache"
    if not cache.is_dir():
        return {"bytes": 0, "removed": 0}
    candidates = []
    total = 0
    removed = 0
    for entry in os.scandir(cache):
        if (
            not re.fullmatch("[0-9a-f]{64}", entry.name)
            or entry.is_symlink()
            or not entry.is_dir(follow_symlinks=False)
        ):
            continue
        folder = Path(entry.path)
        try:
            size = sum(
                child.stat(follow_symlinks=False).st_size
                for child in os.scandir(folder)
                if child.is_file(follow_symlinks=False)
            )
            modified = entry.stat(follow_symlinks=False).st_mtime
            total += size
            candidates.append((modified, folder, size))
        except OSError:
            continue
    if total <= limit:
        return {"bytes": total, "removed": 0}
    for modified, folder, size in sorted(candidates):
        if total <= limit * 0.9:
            break
        if time.time() - modified < min_age:
            continue
        with LOCK:
            if str(folder) in ACTIVE:
                continue
            try:
                if time.time() - folder.stat().st_mtime < min_age:
                    continue
            except OSError:
                continue
            # Generated cache directories only. The lock prevents a new decoder
            # from pinning a directory between the check and removal.
            try:
                shutil.rmtree(folder)
            except OSError:
                continue
        total -= size
        removed += 1
    return {"bytes": total, "removed": removed}


def start(data):
    def run():
        while True:
            time.sleep(60)
            try:
                trim(data)
            except OSError:
                pass
            time.sleep(240)

    threading.Thread(target=run, name="preview-cache-maintenance", daemon=True).start()
