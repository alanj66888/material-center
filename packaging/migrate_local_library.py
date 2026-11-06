"""Copy a consistent SQLite snapshot; never overwrite an existing destination."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3


def migrate(source, destination):
    source, destination = (
        Path(source).resolve(),
        Path(destination).expanduser().resolve(),
    )
    if destination.exists():
        print("目标资料库已存在，保留现有数据：", destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".migration.sqlite3")
    try:
        with closing(
            sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
        ) as original:
            with closing(sqlite3.connect(temporary)) as target:
                original.backup(target)
                if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("索引校验失败")
                count = target.execute(
                    "SELECT COUNT(*) FROM files WHERE missing=0"
                ).fetchone()[0]
        destination.hardlink_to(temporary)
        print("已保留原索引，并迁移有效素材数：", count)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    migrate(args.source, args.destination)
