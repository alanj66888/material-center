"""Download release artifacts over verified TLS; range requests resume individually."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".build"
BUILD.mkdir(exist_ok=True)


def fetch(url, output, *extra):
    subprocess.run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--retry",
            "2",
            "--max-time",
            "600",
            *extra,
            url,
            "-o",
            str(output),
        ],
        check=True,
    )


def electron():
    name = "electron-v45.2.2-win32-x64.zip"
    base = "https://github.com/electron/electron/releases/download/v45.2.2/"
    sums = BUILD / "electron-SHASUMS256.txt"
    fetch(base + "SHASUMS256.txt", sums)
    digest = next(
        row.split()[0]
        for row in sums.read_text().splitlines()
        if row.split()[-1].lstrip("*") == name
    )
    total = 158037212
    count = 16
    size = (total + count - 1) // count

    def part(index):
        start, end = index * size, min(total - 1, (index + 1) * size - 1)
        output = BUILD / f"electron-part-{index:02}"
        headers = BUILD / f"electron-part-{index:02}.headers"
        if (
            output.exists()
            and output.stat().st_size == end - start + 1
            and headers.exists()
            and f"bytes {start}-{end}/{total}" in headers.read_text()
        ):
            return output
        fetch(base + name, output, "--range", f"{start}-{end}", "-D", str(headers))
        if (
            output.stat().st_size != end - start + 1
            or f"bytes {start}-{end}/{total}" not in headers.read_text()
        ):
            raise ValueError("官方服务器未返回预期的分段内容")
        print(f"Electron {index+1}/{count}", flush=True)
        return output

    with ThreadPoolExecutor(max_workers=16) as pool:
        parts = list(pool.map(part, range(count)))
    output = BUILD / name
    with output.open("wb") as target:
        for file in parts:
            target.write(file.read_bytes())
    if hashlib.sha256(output.read_bytes()).hexdigest() != digest:
        raise ValueError("Electron 官方校验失败")
    print("Electron 官方 SHA256 通过", flush=True)


def python():
    name = "python-3.14.10-embed-amd64.zip"
    url = "https://www.python.org/ftp/python/3.14.10/" + name
    output = BUILD / name
    fetch(url, output)
    metadata = BUILD / (name + ".sigstore")
    fetch(url + ".sigstore", metadata)
    import json

    document = json.loads(metadata.read_text())
    expected = (
        document.get("messageSignature", {}).get("messageDigest", {}).get("digest")
    )
    if expected:
        import base64

        if hashlib.sha256(output.read_bytes()).digest() != base64.b64decode(expected):
            raise ValueError("Python 官方校验失败")
    print("Python 官方运行环境下载完成", flush=True)


with ThreadPoolExecutor(max_workers=2) as pool:
    list(pool.map(lambda task: task(), [electron, python]))
