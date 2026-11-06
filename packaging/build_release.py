#!/usr/bin/env python3
"""Build offline desktop distributions without including personal library data."""
import argparse
import ast
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".build"
OUTPUT = ROOT / "releases"
sys.path.insert(0, str(ROOT))
from app_version import VERSION


def run(*args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def icon(destination):
    shutil.copy2(ROOT / "web/icon-dark.png", destination)


def copy_notices(destination):
    for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, destination / name)
    (destination / "SOURCE_INFO.txt").write_text(
        "Project source and third-party source assets: https://github.com/alanj66888/material-center/releases/tag/v"
        + VERSION
        + "\n"
        "Third-party components retain their own licenses; the project NC terms do not override them.\n"
    )


def mac():
    env = {**os.environ, "PYINSTALLER_CONFIG_DIR": str(BUILD / "pyinstaller-cache")}
    vendor = BUILD / "release-media-noncommercial"
    for target in ("mac-arm64",):
        if not all(
            (vendor / target / item).exists()
            for item in ("rawpy", "pypdfium2", "resvg_py", "fontTools", "ffmpeg/ffmpeg")
        ):
            raise ValueError("先运行 prepare_release_media.py")
    # Decoder extensions remain in architecture-specific wheel directories. Collect their
    # standard-library imports into the frozen interpreter, not the extensions.
    hidden = {
        "ctypes",
        "ctypes.util",
        "importlib.metadata",
        "importlib.resources",
        "multiprocessing",
        "multiprocessing.popen_spawn_posix",
    }
    for source in (vendor / "mac-arm64").rglob("*.py"):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
        except (UnicodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom) and not node.level and node.module
                else []
            )
            hidden.update(
                name
                for name in names
                if name.split(".")[0] in sys.stdlib_module_names
                and name.split(".")[0] not in {"winreg", "msvcrt", "_winapi", "nt"}
            )
    arguments = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "LibraryServer",
        "--target-arch",
        "arm64",
        "--distpath",
        BUILD / "macos-backend",
        "--workpath",
        BUILD / "pyinstaller",
        "--specpath",
        BUILD,
        "--add-data",
        str(ROOT / "web") + ":web",
    ]
    for name in (
        "pypinyin",
        "numpy",
        "PIL",
        "rawpy",
        "imageio_ffmpeg",
        "pypdfium2",
        "pypdfium2_raw",
        "resvg_py",
        "pymupdf",
        "fitz",
        "fontTools",
        "brotli",
        "_brotli",
    ):
        arguments += ["--exclude-module", name]
    for name in sorted(hidden):
        arguments += ["--hidden-import", name]
    with (BUILD / "macos-backend-build.log").open("w") as log:
        run(
            *arguments,
            ROOT / "server.py",
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    backend = BUILD / "macos-backend/LibraryServer"
    for target in ("mac-arm64",):
        shutil.copytree(
            vendor / target,
            backend / "vendor" / target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    shutil.copy2(
        BUILD / "release-media-manifest.json", backend / "media-components.json"
    )
    stage = BUILD / "mac-release"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(exist_ok=True)
    app = stage / "素材中心.app"
    if app.exists():
        shutil.rmtree(app)
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    resources = contents / "Resources"
    resources.mkdir()
    copy_notices(resources)
    shutil.copy2(ROOT / "assets/AppIcon.icns", resources / f"AppIcon-{VERSION}.icns")
    shutil.copytree(
        BUILD / "macos-backend/LibraryServer", resources / "backend", symlinks=True
    )
    info = dict(
        CFBundleName="素材中心",
        CFBundleDisplayName="素材中心",
        CFBundleIdentifier="local.sucaiyu.desktop",
        CFBundleExecutable="Sucaiyu",
        CFBundlePackageType="APPL",
        CFBundleVersion=VERSION,
        CFBundleShortVersionString=VERSION,
        CFBundleIconFile=f"AppIcon-{VERSION}.icns",
        NSHighResolutionCapable=True,
        LSMinimumSystemVersion="13.0",
        NSAppTransportSecurity={"NSAllowsLocalNetworking": True},
    )
    with (contents / "Info.plist").open("wb") as f:
        plistlib.dump(info, f)
    run(
        "swiftc",
        "-parse-as-library",
        "-target",
        "arm64-apple-macos12.3",
        "-module-cache-path",
        BUILD / "swift-cache",
        ROOT / "desktop/main.swift",
        "-o",
        contents / "MacOS/Sucaiyu",
        "-framework",
        "Cocoa",
        "-framework",
        "WebKit",
        "-framework",
        "UniformTypeIdentifiers",
    )
    license_file = (
        Path(sys.base_prefix)
        / "Resources/English.lproj/Documentation/_sources/license.rst.txt"
    )
    if license_file.exists():
        shutil.copy2(license_file, resources / "Python-LICENSE.txt")
    run("codesign", "--force", "--deep", "--sign", "-", app)
    run("codesign", "--verify", "--deep", "--strict", app)
    shutil.copy2(ROOT / "packaging/使用说明-Mac.txt", stage / "使用说明.txt")
    application_link = stage / "Applications"
    if not application_link.exists():
        application_link.symlink_to("/Applications")
    destination = OUTPUT / f"素材中心-{VERSION}-macOS-M系列.dmg"
    run(
        "hdiutil",
        "create",
        "-ov",
        "-volname",
        "素材中心 " + VERSION,
        "-srcfolder",
        stage,
        "-format",
        "UDZO",
        destination,
    )
    return destination


def windows(electron_version, python_version):
    archive = BUILD / f"electron-v{electron_version}-win32-x64.zip"
    sums = (BUILD / "electron-SHASUMS256.txt").read_text()
    expected = next(
        line.split()[0]
        for line in sums.splitlines()
        if line.split()[-1].lstrip("*") == archive.name
    )
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise ValueError("Electron 官方 SHA256 校验未通过")
    python_archive = BUILD / f"python-{python_version}-embed-amd64.zip"
    stage = BUILD / "win-release"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    with zipfile.ZipFile(archive) as z:
        z.extractall(stage)
    (stage / "electron.exe").rename(stage / "素材中心.exe")
    application = stage / "resources/app"
    application.mkdir(parents=True, exist_ok=True)
    for name in ("package.json", "main.cjs", "preload.cjs"):
        shutil.copy2(ROOT / "desktop/windows" / name, application / name)
    backend = application / "backend"
    backend.mkdir()
    copy_notices(stage)
    copy_notices(backend)
    for name in (
        "server.py",
        "catalog_index.py",
        "scan_jobs.py",
        "preview_jobs.py",
        "cache_maintenance.py",
        "library_features.py",
        "media_support.py",
        "document_previews.py",
        "runtime_support.py",
        "app_version.py",
    ):
        shutil.copy2(ROOT / name, backend / name)
    shutil.copytree(
        BUILD / "release-media-noncommercial/win-x64",
        backend / "vendor/win-x64",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(
        BUILD / "release-media-manifest.json", backend / "media-components.json"
    )
    shutil.copytree(ROOT / "web", backend / "web")
    runtime = stage / "resources/python"
    runtime.mkdir()
    with zipfile.ZipFile(python_archive) as z:
        corrupt = z.testzip()
        if corrupt:
            raise ValueError("Python 压缩包损坏：" + corrupt)
        z.extractall(runtime)
    # Native image/font extensions also need the C++
    # runtime. Reuse the verified runtime payloads already shipped by CPython/NumPy.
    cpp_runtime = next((backend / "vendor/win-x64/numpy.libs").glob("msvcp140-*.dll"))
    shutil.copy2(cpp_runtime, runtime / "msvcp140.dll")
    # Embeddable Python's ._pth deliberately ignores script directories; add only
    # our packaged backend, without enabling site-packages from the host machine.
    for configuration in runtime.glob("python*._pth"):
        configuration.write_text(
            configuration.read_text() + "\n../app/backend\n", encoding="utf-8"
        )
    icon(application / "icon.png")
    shutil.copy2(ROOT / "assets/app-icon.ico", stage / "素材中心.ico")
    shutil.copy2(ROOT / "assets/app-icon.ico", stage / f"素材中心-{VERSION}.ico")
    run(sys.executable, ROOT / "packaging/brand_windows_exe.py", stage / "素材中心.exe")
    shutil.copy2(ROOT / "packaging/使用说明-Windows.txt", stage / "使用说明.txt")
    (stage / "运行环境版本.json").write_text(
        json.dumps(
            {
                "app": VERSION,
                "electron": electron_version,
                "python": python_version,
                "electron_sha256": expected,
                "python_sha256": hashlib.sha256(
                    python_archive.read_bytes()
                ).hexdigest(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    destination = OUTPUT / f"素材中心-{VERSION}-Windows-x64.zip"
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for file in sorted(stage.rglob("*")):
            if file.is_file():
                z.write(file, Path("素材中心") / file.relative_to(stage))
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("platform", choices=["mac", "windows"])
    parser.add_argument("--electron", default="45.2.2")
    parser.add_argument("--python", default="3.14.10")
    args = parser.parse_args()
    BUILD.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    artifact = mac() if args.platform == "mac" else windows(args.electron, args.python)
    print(artifact)
