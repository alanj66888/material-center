"""Download SHA256-verified wheels for each offline desktop runtime."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
from pathlib import Path
import subprocess
import threading
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".build"
PACKAGES = {
    "numpy": "2.3.5",
    "Pillow": "13.0.0",
    "rawpy": "0.28.0",
    "pypdfium2": "5.14.0",
    "resvg_py": "0.5.0",
    "fonttools": "4.61.1",
    "brotli": "1.2.1",
    "pypinyin": "0.55.0",
}
METADATA_LOCK = threading.Lock()
ARCHIVE_LOCKS = {}
TARGETS = {
    "mac-arm64": ("cp311", "arm64"),
    "win-x64": ("cp314", "win_amd64"),
}


def fetch(url, output):
    subprocess.run(
        [
            "curl",
            "--compressed",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--retry",
            "2",
            "--max-time",
            "300",
            url,
            "-o",
            str(output),
        ],
        check=True,
    )


def install(job):
    target, name = job
    python, architecture = TARGETS[target]
    version = PACKAGES[name]
    metadata = BUILD / f"media-{name}-{version}.json"
    with METADATA_LOCK:
        try:
            info = json.loads(metadata.read_text())
        except (OSError, ValueError):
            temporary = metadata.with_suffix(".download")
            fetch(f"https://pypi.org/pypi/{name}/{version}/json", temporary)
            info = json.loads(temporary.read_text())
            temporary.replace(metadata)

    def compatible(entry):
        filename = entry["filename"]
        universal = "py3-none-any.whl" in filename
        abi = re.search(r"cp3(\d+)-abi3-", filename)
        python_ok = (
            f"{python}-{python}-" in filename
            or "py3-none-" in filename
            or bool(abi and int(abi[1]) <= int(python[3:]))
        )
        platform_ok = (
            universal
            or (
                architecture in filename
                or target.startswith("mac")
                and "universal2" in filename
            )
            and (not target.startswith("mac") or "macosx" in filename)
        )
        return filename.endswith(".whl") and python_ok and platform_ok

    candidates = [entry for entry in info["urls"] if compatible(entry)]
    if not candidates:
        raise RuntimeError(f"No wheel: {target} {name} {version}")
    # Prefer the wheel with the lowest macOS deployment target.
    entry = sorted(
        candidates,
        key=lambda item: ("py3-none-any" not in item["filename"], item["filename"]),
    )[0]
    archive = BUILD / entry["filename"]
    with ARCHIVE_LOCKS.setdefault(archive.name, threading.Lock()):
        if (
            not archive.exists()
            or hashlib.sha256(archive.read_bytes()).hexdigest()
            != entry["digests"]["sha256"]
        ):
            count = 8
            chunk = (entry["size"] + count - 1) // count

            def part(index):
                start, end = index * chunk, min(
                    entry["size"] - 1, (index + 1) * chunk - 1
                )
                output = BUILD / (entry["filename"] + f".release-part{index}")
                required = end - start + 1
                for attempt in range(12):
                    completed = output.stat().st_size if output.exists() else 0
                    if completed == required:
                        return output
                    if completed > required:
                        output.unlink()
                        completed = 0
                    temporary = Path(str(output) + ".resume")
                    headers = Path(str(output) + ".headers")
                    result = subprocess.run(
                        [
                            "curl",
                            "--http1.1",
                            "--fail",
                            "--silent",
                            "--show-error",
                            "--location",
                            "--connect-timeout",
                            "20",
                            "--max-time",
                            "120",
                            "--range",
                            f"{start+completed}-{end}",
                            "-D",
                            str(headers),
                            entry["url"],
                            "-o",
                            str(temporary),
                        ]
                    )
                    content = temporary.read_bytes() if temporary.exists() else b""
                    expected = f"bytes {start+completed}-{end}/"
                    if (
                        content
                        and len(content) <= required - completed
                        and expected in headers.read_text()
                    ):
                        with output.open("ab") as destination:
                            destination.write(content)
                    temporary.unlink(missing_ok=True)
                if not output.exists() or output.stat().st_size != required:
                    raise ValueError("Component download did not complete")
                return output

            with ThreadPoolExecutor(max_workers=8) as pool:
                parts = list(pool.map(part, range(count)))
            with archive.open("wb") as output:
                for path in parts:
                    output.write(path.read_bytes())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != entry["digests"]["sha256"]:
            raise ValueError("Wheel SHA256 mismatch")
    destination = BUILD / "release-media-noncommercial" / target
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as wheel:
        wheel.extractall(destination)
    for binary in destination.glob("imageio_ffmpeg/binaries/ffmpeg-*"):
        binary.chmod(0o755)
    print(f'{target}: {entry["filename"]} verified', flush=True)
    return {
        "target": target,
        "package": name,
        "version": version,
        "filename": entry["filename"],
        "sha256": digest,
        "source": entry["url"],
    }


if __name__ == "__main__":
    BUILD.mkdir(exist_ok=True)
    jobs = [(target, name) for target in TARGETS for name in PACKAGES]
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(install, jobs))
    (BUILD / "release-media-manifest.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2)
    )
