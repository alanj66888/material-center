"""Publish matching third-party sources separately from the project's NC license."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import tarfile
from prepare_ffmpeg import artifact, VERSION as FFMPEG_VERSION, SOURCE_SHA

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_version import VERSION

BUILD = ROOT / ".build"
SOURCES = [
    (
        "ffmpeg-8.0.1.tar.xz",
        "https://ffmpeg.org/releases/ffmpeg-8.0.1.tar.xz",
        SOURCE_SHA,
    ),
    (
        "rawpy-0.28.0.tar.gz",
        "https://files.pythonhosted.org/packages/84/17/d9b34cdf64b1377e4f9d070375674276a5f68954741849592eda81c67557/rawpy-0.28.0.tar.gz",
        "3176c865b786dfec4e54251759f98e5a00733035f1f256e8c09909c59b5353d2",
    ),
    (
        "LibRaw-0.22.2.tar.gz",
        "https://www.libraw.org/data/LibRaw-0.22.2.tar.gz",
        "de86b035655accff8d4010f1a221fdf50d353cb7b1422ba26f14a0db92612cfa",
    ),
]


def main():
    stage = BUILD / "third-party-source-stage"
    stage.mkdir(exist_ok=True)
    records = []
    for filename, url, digest in SOURCES:
        local = BUILD / (
            "nc-" + filename if filename.startswith("ffmpeg-") else filename
        )
        artifact(url, local, digest)
        shutil.copy2(local, stage / filename)
        records.append({"filename": filename, "url": url, "sha256": digest})
    (stage / "sources.json").write_text(json.dumps(records, indent=2) + "\n")
    (stage / "README.txt").write_text(
        "Third-party sources for Material Center "
        + VERSION
        + "\n\nThese sources retain their upstream licenses, not the project noncommercial license.\nFFmpeg: official unmodified 8.0.1 sources; use prepare_ffmpeg.py and the per-platform configure JSON to reproduce.\nrawpy: matching 0.28.0 source distribution, including its external/LibRaw tree.\nLibRaw: additional upstream 0.22.2 source release, LGPL/CDDL notices retained.\nNo GPL demosaic packs are used in distributed rawpy wheels.\n"
    )
    shutil.copy2(ROOT / "packaging/prepare_ffmpeg.py", stage / "prepare_ffmpeg.py")
    for target in ["mac-arm64", "win-x64"]:
        shutil.copy2(
            BUILD / "release-media-noncommercial" / target / "ffmpeg/build.json",
            stage / (target + "-ffmpeg-configure.json"),
        )
    output = ROOT / "releases" / f"third-party-sources-{VERSION}.tar.xz"
    with tarfile.open(output, "w:xz") as archive:
        for file in sorted(stage.iterdir()):
            archive.add(file, arcname="third-party-sources/" + file.name)
    print(output)


if __name__ == "__main__":
    main()
