"""Verify the shipped backend in isolation and audit the Windows archive."""
import argparse
import hashlib
import sys
import http.client
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time
import zipfile
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app_version import VERSION


def backend_smoke(architecture="arm64"):
    binary = (
        ROOT / ".build/mac-release/素材中心.app/Contents/Resources/backend/LibraryServer"
    )
    with tempfile.TemporaryDirectory(prefix="sucaiyu-release-") as temporary:
        folder = Path(temporary)
        data = folder / "索引"
        ready = folder / "ready.json"
        material = folder / "素材 with spaces"
        material.mkdir()
        (material / "片段.MP4").write_bytes(b"0123456789")
        (material / "笔记.txt").write_text("fixture", encoding="utf-8")
        (material / "空目录").mkdir()
        sys.path.insert(0, str(ROOT / ".build/release-media-noncommercial/mac-arm64"))
        sys.path.insert(0, str(ROOT / "tests"))
        from feature_fixtures import make_media
        from document_fixtures import make_documents

        from unittest.mock import patch

        with patch.dict(
            os.environ,
            {
                "SUCAIYU_FFMPEG": str(
                    ROOT / ".build/release-media-noncommercial/mac-arm64/ffmpeg/ffmpeg"
                )
            },
        ):
            make_media(material / "媒体样片")
        make_documents(material / "字体与矢量")
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            not in {
                "SUCAIYU_MEDIA_LIBS",
                "SUCAIYU_FFMPEG",
                "IMAGEIO_FFMPEG_EXE",
                "SUCAIYU_TEST_MODE",
                "PYTHONPATH",
            }
        }
        child = subprocess.Popen(
            [
                "/usr/bin/arch",
                "-" + architecture,
                str(binary),
                "--no-browser",
                "--port",
                "0",
                "--ready-file",
                str(ready),
            ],
            env={**environment, "SUCAIYU_DATA_DIR": str(data)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 20
            while not ready.exists():
                if child.poll() is not None:
                    raise RuntimeError(child.communicate()[1].decode())
                if time.monotonic() > deadline:
                    raise RuntimeError("独立后端启动超时")
                time.sleep(0.1)
            address = urlparse(json.loads(ready.read_text())["url"])

            def request(method, path, body=None, headers=None):
                connection = http.client.HTTPConnection(
                    address.hostname, address.port, timeout=120
                )
                connection.request(
                    method,
                    path,
                    json.dumps(body) if body is not None else None,
                    headers or {},
                )
                response = connection.getresponse()
                status, payload = response.status, response.read()
                connection.close()
                return status, payload

            assert json.loads(request("GET", "/api/health")[1]) == {
                "app": "sucaiyu",
                "version": VERSION,
            }
            library = json.loads(request("GET", "/api/library")[1])
            assert not library["files"] and not library["roots"], "发行包不得带入个人索引"
            headers = {"X-Library-Token": library["token"]}
            assert (
                request("POST", "/api/scan", {"path": str(material)}, headers)[0] == 200
            )
            catalog = json.loads(request("GET", "/api/catalog")[1])
            assert catalog["total"] == 18 and "files" not in catalog, catalog["total"]
            page = json.loads(request("GET", "/api/items?recursive=1&limit=2")[1])
            assert len(page["files"]) == 2 and page["total"] == 18
            assert request("GET", "/catalog.js")[0] == 200
            library = json.loads(request("GET", "/api/library")[1])
            assert len(library["files"]) == 18
            assert not library["test_mode"]
            assert all(library["capabilities"].values()), library["capabilities"]
            assert any(row["folder"] == "空目录" for row in library["directories"])
            file = next(row for row in library["files"] if row["name"] == "片段.MP4")
            assert request(
                "GET", "/media/" + str(file["id"]), headers={"Range": "bytes=2-5"}
            ) == (206, b"2345")
            assert (
                request(
                    "POST", "/api/tags", {"ids": [file["id"]], "tags": ["验收"]}, headers
                )[0]
                == 200
            )
            assert (
                request("GET", "/app.js")[0] == 200
                and request("GET", "/library.js")[0] == 200
            )
            for asset in library["files"]:
                if asset["folder"] != "字体与矢量":
                    continue
                status, payload = request("GET", "/api/metadata/" + str(asset["id"]))
                assert status == 200, payload
                metadata = json.loads(payload)
                assert "error" not in metadata, metadata
                status, payload = request("GET", "/preview-image/" + str(asset["id"]))
                if asset["ext"] == "eps" or asset["name"] == "PostScript兼容矢量图.ai":
                    assert status != 200 and "内嵌预览" in payload.decode(), payload[:200]
                else:
                    assert status == 200 and payload.startswith(b"\xff\xd8"), payload[
                        :200
                    ]
            for asset in library["files"]:
                if asset["ext"] not in ("dng", "mts"):
                    continue
                status, payload = request("GET", "/api/metadata/" + str(asset["id"]))
                assert status == 200, payload
                metadata = json.loads(payload)
                assert metadata["width"] and metadata["height"], metadata
                status, payload = request("GET", "/preview-image/" + str(asset["id"]))
                assert status == 200 and payload.startswith(b"\xff\xd8"), payload[:200]
                if asset["ext"] == "mts":
                    status, payload = request(
                        "POST", "/api/prepare", {"id": asset["id"]}, headers
                    )
                    assert status == 200, payload
                    status, payload = request(
                        "POST", "/api/recycle", {"ids": [asset["id"]]}, headers
                    )
                    assert (
                        status == 200 and len(json.loads(payload)["processed"]) == 1
                    ), payload
                    entry = json.loads(request("GET", "/api/trash")[1])["items"][0]
                    base = f"/trash-preview/{entry['root']}/{entry['id']}/"
                    status, payload = request("GET", base + "frame?position=60")
                    assert status == 200 and payload.startswith(b"\xff\xd8"), payload[
                        :200
                    ]
                    assert (
                        request(
                            "POST",
                            "/api/restore",
                            {"items": [{"root": entry["root"], "id": entry["id"]}]},
                            headers,
                        )[0]
                        == 200
                    )
            for source in (
                "features.js",
                "selection.js",
                "preferences.js",
                "icon-light.png",
                "icon-dark.png",
            ):
                assert request("GET", "/" + source)[0] == 200
        finally:
            child.terminate()
            child.communicate(timeout=10)
    print(
        f"Mac {architecture} 独立后端：启动、空资料库、扫描、Unicode、标签、DNG、MTS、兼容视频、回收站抽帧/还原、字体与 AI/EPS/PDF/SVG 预览通过",
        flush=True,
    )


def windows_audit():
    archive = ROOT / f"releases/素材中心-{VERSION}-Windows-x64.zip"
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        names = z.namelist()
        assert not any(".sqlite" in name or "/.library/" in name for name in names)
        for name in [
            "素材中心/素材中心.exe",
            "素材中心/resources/python/python.exe",
            "素材中心/resources/python/_sqlite3.pyd",
        ]:
            content = z.read(name)
            assert content[:2] == b"MZ"
            offset = struct.unpack_from("<I", content, 0x3C)[0]
            assert (
                content[offset : offset + 4] == b"PE\0\0"
                and struct.unpack_from("<H", content, offset + 4)[0] == 0x8664
            )
        for relative in ["main.cjs", "preload.cjs", "package.json"]:
            assert (
                z.read("素材中心/resources/app/" + relative)
                == (ROOT / "desktop/windows" / relative).read_bytes()
            )
        assert (
            z.read("素材中心/resources/app/backend/server.py")
            == (ROOT / "server.py").read_bytes()
        )
        for module in (
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
            assert (
                z.read("素材中心/resources/app/backend/" + module)
                == (ROOT / module).read_bytes()
            )
        prefix = "素材中心/resources/app/backend/vendor/win-x64/"
        for package in (
            "numpy",
            "PIL",
            "rawpy",
            "pypdfium2",
            "pypdfium2_raw",
            "resvg_py",
            "fontTools",
            "pypinyin",
        ):
            assert any(
                name.startswith(prefix + package + "/") for name in names
            ), package
        assert prefix + "ffmpeg/ffmpeg.exe" in names
        assert not any(
            "/pymupdf/" in name or "/fitz/" in name or "/postscript/" in name
            for name in names
        )
        assert (
            json.loads(z.read("素材中心/resources/app/package.json"))["version"] == VERSION
        )
        assert z.read("素材中心/素材中心.ico") == (ROOT / "assets/app-icon.ico").read_bytes()
        assert (
            z.read(f"素材中心/素材中心-{VERSION}.ico")
            == (ROOT / "assets/app-icon.ico").read_bytes()
        )
        assert (
            z.read("素材中心/resources/app/icon.png")
            == (ROOT / "web/icon-dark.png").read_bytes()
        )
        for file in (ROOT / "web").iterdir():
            if file.is_file():
                assert (
                    z.read("素材中心/resources/app/backend/web/" + file.name)
                    == file.read_bytes()
                )
    print("Windows 包：ZIP 完整性、x64 PE、运行环境、源文件一致性与私人数据排除通过")


def installer_audit():
    installer = ROOT / f"releases/素材中心-{VERSION}-Windows-x64-安装程序.exe"
    archive = ROOT / f"releases/素材中心-{VERSION}-Windows-x64-安装包.zip"
    if not installer.exists():
        return
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert set(z.namelist()) == {installer.name, "安装说明.txt"}
        assert (
            hashlib.sha256(z.read(installer.name)).digest()
            == hashlib.sha256(installer.read_bytes()).digest()
        )
    script = (ROOT / ".build/material-center-installer.nsi").read_text(
        encoding="utf-8-sig"
    )
    uninstall = script.split('Section "Uninstall"')[1]
    assert (
        "RMDir /r" not in uninstall
        and "$APPDATA" not in uninstall
        and "$PROFILE" not in uninstall
    )
    assert "RequestExecutionLevel user" in script
    assert f"素材中心-{VERSION}.ico" in script
    assert "SHChangeNotify" in script
    print("Windows 安装 ZIP、EXE 一致性、当前用户安装及卸载文件范围检查通过")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", default="arm64", choices=["arm64"])
    parser.add_argument("--backend-only", action="store_true")
    args = parser.parse_args()
    backend_smoke(args.arch)
    if args.backend_only:
        sys.exit(0)
    if (ROOT / f"releases/素材中心-{VERSION}-Windows-x64.zip").exists():
        windows_audit()
    installer_audit()
