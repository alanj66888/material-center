"""Build independent LGPL-only FFmpeg executables; keep matching source for releases."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".build"
VERSION = "8.0.1"
SOURCE_SHA = "05ee0b03119b45c0bdb4df654b96802e909e0a752f72e4fe3794f487229e5a41"
LLVM_TAG = "20261104"
LLVM_SHA = "66cbd5178c4a71b0d473e68ede172f8eb7d15d023e67f39201d0a69e21f6bf3c"


def artifact(url, path, digest):
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        subprocess.run(
            ["curl", "--fail", "--location", "--retry", "3", url, "-o", str(path)],
            check=True,
        )
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("SHA256 mismatch: " + path.name)


def extract(archive):
    with tarfile.open(archive) as tar:
        base = BUILD.resolve()
        for item in tar.getmembers():
            target = (base / item.name).resolve()
            if not target.is_relative_to(base):
                raise ValueError("Unsafe archive path")
            if item.issym() or item.islnk():
                link = (
                    target.parent / item.linkname
                    if item.issym()
                    else base / item.linkname
                ).resolve()
                if not link.is_relative_to(base):
                    raise ValueError("Unsafe archive link")
        tar.extractall(base)


def build(target):
    archive = BUILD / f"nc-ffmpeg-{VERSION}.tar.xz"
    artifact(
        f"https://ffmpeg.org/releases/ffmpeg-{VERSION}.tar.xz", archive, SOURCE_SHA
    )
    source = BUILD / f"ffmpeg-{VERSION}"
    if not source.exists():
        extract(archive)
    work = BUILD / ("ffmpeg-lgpl-" + target)
    work.mkdir(exist_ok=True)
    destination = BUILD / "release-media-noncommercial" / target / "ffmpeg"
    destination.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    nasm = BUILD / "nasm-2.16.03"
    if target == "win-x64" and not (nasm / "nasm").exists():
        archive_nasm = BUILD / "nasm-2.16.03.tar.xz"
        artifact(
            "https://www.nasm.us/pub/nasm/releasebuilds/2.16.03/nasm-2.16.03.tar.xz",
            archive_nasm,
            "1412a1c760bbd05db026b6c0d1657affd6631cd0a63cddb6f73cc6d4aa616148",
        )
        if not nasm.exists():
            extract(archive_nasm)
        subprocess.run(["./configure"], cwd=nasm, check=True)
        subprocess.run(["make", "-j8"], cwd=nasm, check=True)
    if (nasm / "nasm").exists():
        env["PATH"] = str(nasm) + os.pathsep + env["PATH"]
    flags = [
        "--disable-doc",
        "--disable-debug",
        "--disable-network",
        "--disable-autodetect",
        "--disable-gpl",
        "--disable-nonfree",
        "--disable-version3",
        "--disable-programs",
        "--enable-ffmpeg",
        "--disable-encoders",
        "--enable-encoder=mjpeg,png,mpeg2video,aac,mp2,pcm_s16le",
        "--disable-muxers",
        "--enable-muxer=mp4,mpegts,image2,null,wav,adts",
        "--disable-outdevs",
        "--disable-indevs",
        "--enable-indev=lavfi",
        "--enable-small",
    ]
    if target == "mac-arm64":
        env["MACOSX_DEPLOYMENT_TARGET"] = "13.0"
        flags += [
            "--extra-cflags=-mmacosx-version-min=13.0",
            "--extra-ldflags=-mmacosx-version-min=13.0",
            "--arch=arm64",
            "--cc=/usr/bin/clang",
            "--enable-videotoolbox",
            "--enable-audiotoolbox",
            "--enable-encoder=h264_videotoolbox",
        ]
    else:
        name = f"llvm-mingw-{LLVM_TAG}-ucrt-macos-universal"
        tool = BUILD / name
        if not tool.exists():
            llvm = BUILD / (name + ".tar.xz")
            artifact(
                f"https://github.com/mstorsjo/llvm-mingw/releases/download/{LLVM_TAG}/{name}.tar.xz",
                llvm,
                LLVM_SHA,
            )
            extract(llvm)
        env["PATH"] = str(tool / "bin") + os.pathsep + env["PATH"]
        flags += [
            "--target-os=mingw32",
            "--arch=x86_64",
            "--enable-cross-compile",
            "--cross-prefix=x86_64-w64-mingw32-",
            "--cc=x86_64-w64-mingw32-clang",
            "--cxx=x86_64-w64-mingw32-clang++",
            "--enable-mediafoundation",
            "--enable-d3d11va",
            "--enable-encoder=h264_mf",
        ]
        if not shutil.which("nasm", path=env["PATH"]):
            flags += ["--disable-x86asm"]
    fingerprint = work / "build-options.json"
    options = json.dumps(flags, sort_keys=True)
    if (work / "Makefile").exists() and (
        not fingerprint.exists() or fingerprint.read_text() != options
    ):
        subprocess.run(["make", "clean"], cwd=work, env=env, check=True)
    configuration = [str(source / "configure"), *flags]
    subprocess.run(configuration, cwd=work, env=env, check=True)
    subprocess.run(
        ["make", "-j", str(min(8, os.cpu_count() or 2))], cwd=work, env=env, check=True
    )
    fingerprint.write_text(options)
    binary = "ffmpeg.exe" if target == "win-x64" else "ffmpeg"
    shutil.copy2(work / binary, destination / binary)
    shutil.copy2(source / "COPYING.LGPLv2.1", destination / "COPYING.LGPLv2.1")
    shutil.copy2(source / "LICENSE.md", destination / "FFmpeg-LICENSE.md")
    (destination / "build.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "target": target,
                "source_sha256": SOURCE_SHA,
                "configure": flags,
                "source_asset": f"ffmpeg-{VERSION}-source.tar.xz",
            },
            indent=2,
        )
    )
    release = ROOT / "releases"
    release.mkdir(exist_ok=True)
    shutil.copy2(archive, release / f"ffmpeg-{VERSION}-source.tar.xz")
    print(destination / binary, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=["mac-arm64", "win-x64"])
    build(parser.parse_args().target)
