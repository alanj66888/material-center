"""Reproducible local-index benchmark. Does not read or write a real NAS."""
from pathlib import Path
import json
import os
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

BASE = Path(__file__).resolve().parents[1] / ".build/performance-120k"
BASE.mkdir(exist_ok=True)
server.DATA = BASE / "data"
server.initialize()
root = BASE / "模拟NAS素材"
root.mkdir(exist_ok=True)
with server.db() as c:
    c.execute("INSERT OR IGNORE INTO roots(path) VALUES(?)", (str(root),))
    rid = c.execute("SELECT id FROM roots WHERE path=?", (str(root),)).fetchone()[0]
    existing = c.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    start = time.perf_counter()
    if existing < 120000:
        for offset in range(existing, 120000, 1000):
            rows = []
            directories = set()
            for i in range(offset, min(offset + 1000, 120000)):
                folder = "A_大文件夹" if i < 40000 else f"B_分类/{i//100:04d}"
                filename = f'{"风光" if i%5==0 else "DJI"}_{i:08d}.txt'
                rows.append(
                    (
                        rid,
                        str(root / folder / filename),
                        filename,
                        folder,
                        "txt",
                        "other",
                        i * 1024,
                        1700000000 + i,
                        i % 37 == 0,
                        f"主题{i%500}, 地点{i%100}",
                    )
                )
                directories.update([".", "B_分类", folder])
            c.executemany(
                "INSERT INTO files(root,path,name,folder,ext,kind,size,modified,favorite,tags) VALUES(?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            c.executemany(
                "INSERT OR IGNORE INTO directories VALUES(?,?)",
                [(rid, folder) for folder in directories],
            )
        print(
            "fixture built seconds", round(time.perf_counter() - start, 3), flush=True
        )


def timed(task, count=12):
    times = []
    result = None
    for _ in range(count):
        start = time.perf_counter()
        result = task()
        times.append((time.perf_counter() - start) * 1000)
    return {
        "median_ms": round(statistics.median(times), 2),
        "p95_ms": round(sorted(times)[int((len(times) - 1) * 0.95)], 2),
        "max_ms": round(max(times), 2),
    }, result


report = {
    "records": 120000,
    "scope": "Generated local SQLite index; not real NAS throughput",
}
report["catalog"], summary = timed(lambda: server.READER.catalog(server.DATA))
report["catalog_payload_bytes"] = len(json.dumps(summary, ensure_ascii=False).encode())
queries = {
    "first_page": {"root": [str(rid)], "recursive": ["1"], "sort": ["modified"]},
    "deep_page": {
        "root": [str(rid)],
        "recursive": ["1"],
        "offset": ["110000"],
        "sort": ["modified"],
    },
    "large_folder": {"root": [str(rid)], "folder": ["A_大文件夹"], "sort": ["modified"]},
    "name_sort": {"root": [str(rid)], "recursive": ["1"], "sort": ["name"]},
    "search": {"recursive": ["1"], "search": ["DJI_00099"]},
    "two_char_search": {"recursive": ["1"], "search": ["风光"]},
    "tag_filter": {"tag": ["主题123"], "sort": ["modified"]},
    "favorite": {"view": ["favorite"], "sort": ["modified"]},
}
for name, query in queries.items():
    report[name], result = timed(lambda: server.READER.items(server.DATA, query))
    report[name].update(
        total=result["total"],
        returned=len(result["files"]),
        payload_bytes=len(json.dumps(result, ensure_ascii=False).encode()),
    )
with server.db() as c:
    start = time.perf_counter()
    legacy = [dict(row) for row in c.execute("SELECT * FROM files WHERE missing=0")]
    serialized = json.dumps(legacy, ensure_ascii=False).encode()
    report["legacy_full_load"] = {
        "ms": round((time.perf_counter() - start) * 1000, 2),
        "payload_bytes": len(serialized),
    }
(BASE / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
