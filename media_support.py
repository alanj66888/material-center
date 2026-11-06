"""On-demand metadata, RAW previews and compatible video proxies; originals stay intact."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import sys
import time
from functools import wraps
import cache_maintenance

from document_previews import (
    GRAPHICS,
    FONT_FORMATS,
    font_details,
    graphic_details,
    render_font,
    render_graphic,
)

DECODERS = threading.BoundedSemaphore(2)
PROXY_DECODER = threading.BoundedSemaphore(1)
RAW = set(
    "dng raw cr2 cr3 nef nrw arw srf sr2 raf orf rw2 pef srw x3f 3fr erf kdc mrw mos mef dcr iiq rwl k25 bay ptx cap gpr fff arq".split()
)
WEB_IMAGES = set("jpg jpeg png gif webp bmp avif svg ico".split())
WEB_VIDEO = set("mp4 m4v mov webm ogv".split())


def ffmpeg():
    configured = os.environ.get("SUCAIYU_FFMPEG")
    if configured and Path(configured).is_file():
        return configured
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    target = "win-x64" if sys.platform == "win32" else "mac-arm64"
    vendor = Path(os.environ.get("SUCAIYU_MEDIA_LIBS", str(base / "vendor" / target)))
    bundled = vendor / "ffmpeg" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if bundled.is_file():
        return str(bundled)
    binary = shutil.which("ffmpeg")
    if binary:
        return binary
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def video_encoder_args():
    if sys.platform == "darwin":
        return ["-c:v", "h264_videotoolbox", "-allow_sw", "1", "-b:v", "3M"]
    if os.name == "nt":
        return ["-c:v", "h264_mf", "-b:v", "3M"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "25"]


def capabilities():
    import importlib.util

    return {
        "ffmpeg": bool(ffmpeg()),
        "raw": importlib.util.find_spec("rawpy") is not None,
        "images": importlib.util.find_spec("PIL") is not None,
    }


PROCESSES = set()
PROCESS_LOCK = threading.Lock()


def stop_processes():
    with PROCESS_LOCK:
        processes = list(PROCESSES)
    for process in processes:
        try:
            process.kill()
        except OSError:
            pass


def run(arguments, timeout=60, cancelled=None):
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    with PROCESS_LOCK:
        PROCESSES.add(process)
    try:
        deadline = time.monotonic() + timeout
        while True:
            if cancelled and cancelled():
                process.kill()
                process.communicate()
                raise ValueError("预览已取消")
            try:
                stdout, stderr = process.communicate(
                    timeout=min(0.3, max(0.01, deadline - time.monotonic()))
                )
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    process.kill()
                    process.communicate()
                    raise
        return subprocess.CompletedProcess(
            arguments, process.returncode, stdout, stderr
        )
    finally:
        with PROCESS_LOCK:
            PROCESSES.discard(process)


def protected(method):
    @wraps(method)
    def execute(self, file, *args, **kwargs):
        folder = self.folder(file)
        with cache_maintenance.pin(folder):
            folder.mkdir(exist_ok=True)
            return method(self, file, *args, **kwargs)

    return execute


class MediaSupport:
    def __init__(self, data):
        self.cache = Path(data) / "preview-cache"
        self.cache.mkdir(parents=True, exist_ok=True)

    def folder(self, file):
        path = Path(file["path"])
        if "modified" in file.keys() and "size" in file.keys():
            generation = "index-v2:" + repr(file["modified"]) + ":" + str(file["size"])
        else:
            status = path.stat()
            generation = str(status.st_mtime_ns) + ":" + str(status.st_size)
        key = hashlib.sha256((str(path) + "\0" + generation).encode()).hexdigest()
        folder = self.cache / key
        folder.mkdir(exist_ok=True)
        cache_maintenance.touch(folder)
        return folder

    @protected
    def metadata(self, file):
        folder = self.folder(file)
        cache = folder / "metadata.json"
        if cache.is_file():
            return json.loads(cache.read_text())
        result = {"duration": None, "width": None, "height": None, "codec": None}
        with DECODERS:
            if cache.is_file():
                return json.loads(cache.read_text())
            try:
                if file["ext"] in FONT_FORMATS:
                    result.update(font_details(file))
                elif file["ext"] in GRAPHICS:
                    result.update(graphic_details(file, folder))
                elif file["kind"] == "image":
                    if file["ext"] in RAW:
                        import rawpy

                        with rawpy.imread(file["path"]) as image:
                            width, height = image.sizes.width, image.sizes.height
                            if image.sizes.flip in (5, 6):
                                width, height = height, width
                            result.update(width=width, height=height)
                    else:
                        from PIL import Image

                        with Image.open(file["path"]) as image:
                            width, height = image.size
                            if image.getexif().get(274) in (5, 6, 7, 8):
                                width, height = height, width
                            result.update(width=width, height=height)
                elif file["kind"] in ("video", "audio") and ffmpeg():
                    process = run(
                        [ffmpeg(), "-hide_banner", "-i", file["path"]], timeout=30
                    )
                    text = process.stderr.decode("utf-8", errors="replace")
                    duration = re.search(
                        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text
                    )
                    if duration:
                        result["duration"] = (
                            int(duration[1]) * 3600
                            + int(duration[2]) * 60
                            + float(duration[3])
                        )
                    video = re.search(
                        r"Video:\s*([^,\s]+).*?\b(\d{2,6})x(\d{2,6})\b", text
                    )
                    if video:
                        result.update(
                            codec=video[1], width=int(video[2]), height=int(video[3])
                        )
                    rotation = re.search(r"rotation of\s*(-?[\d.]+)", text)
                    if rotation and result["width"] and round(float(rotation[1])) % 180:
                        result["width"], result["height"] = (
                            result["height"],
                            result["width"],
                        )
            except (
                ImportError,
                OSError,
                ValueError,
                RuntimeError,
                subprocess.TimeoutExpired,
            ) as error:
                result["error"] = str(error)[:250]
            if result.get("error"):
                return result
            temporary = folder / (threading.current_thread().name + ".metadata.tmp")
            temporary.write_text(json.dumps(result), encoding="utf-8")
            os.replace(temporary, cache)
        return result

    @protected
    def poster(self, file):
        folder = self.folder(file)
        target = folder / "poster.jpg"
        if target.is_file():
            return target
        with DECODERS:
            if target.is_file():
                return target
            temporary = folder / (threading.current_thread().name + ".jpg")
            try:
                if file["ext"] in FONT_FORMATS:
                    render_font(file, temporary)
                elif file["ext"] in GRAPHICS:
                    render_graphic(file, folder, temporary)
                elif file["kind"] == "image":
                    from PIL import Image, ImageOps

                    if file["ext"] in RAW:
                        import rawpy

                        with rawpy.imread(file["path"]) as raw:
                            try:
                                thumb = raw.extract_thumb()
                                if thumb.format == rawpy.ThumbFormat.JPEG:
                                    image = Image.open(io.BytesIO(thumb.data))
                                else:
                                    image = Image.fromarray(thumb.data)
                            except (
                                rawpy.LibRawNoThumbnailError,
                                rawpy.LibRawUnsupportedThumbnailError,
                            ):
                                image = Image.fromarray(
                                    raw.postprocess(
                                        half_size=True, use_camera_wb=True, output_bps=8
                                    )
                                )
                            image = ImageOps.exif_transpose(image).convert("RGB")
                            image.thumbnail((1600, 1600))
                            image.save(temporary, "JPEG", quality=88)
                    else:
                        with Image.open(file["path"]) as image:
                            image = ImageOps.exif_transpose(image).convert("RGB")
                            image.thumbnail((1600, 1600))
                            image.save(temporary, "JPEG", quality=88)
                elif file["kind"] == "video" and ffmpeg():
                    process = run(
                        [
                            ffmpeg(),
                            "-nostdin",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-y",
                            "-i",
                            file["path"],
                            "-ss",
                            "0.1",
                            "-frames:v",
                            "1",
                            "-vf",
                            "scale='min(960,iw)':-2",
                            "-pix_fmt",
                            "yuvj420p",
                            "-threads",
                            "1",
                            "-q:v",
                            "3",
                            str(temporary),
                        ],
                        timeout=60,
                    )
                    if process.returncode:
                        raise ValueError(process.stderr.decode(errors="replace")[-500:])
                else:
                    raise ValueError("此格式暂无可用的预览解码器")
                if not temporary.is_file() or not temporary.stat().st_size:
                    raise ValueError("未能生成预览图")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return target

    @protected
    def frame(self, file, position):
        if not ffmpeg():
            raise ValueError("没有可用的视频解码器")
        position = max(0, min(80, int(position)))
        information = self.metadata(file)
        seconds = max(0, (information.get("duration") or 0) - 0.06) * position / 80
        folder = self.folder(file)
        target = folder / f"frame-{position}.jpg"
        if target.is_file():
            return target
        with DECODERS:
            if target.is_file():
                return target
            temporary = folder / (threading.current_thread().name + ".frame.jpg")
            try:
                process = run(
                    [
                        ffmpeg(),
                        "-nostdin",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-ss",
                        str(seconds),
                        "-i",
                        file["path"],
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale='min(960,iw)':-2",
                        "-pix_fmt",
                        "yuvj420p",
                        "-threads",
                        "1",
                        "-q:v",
                        "3",
                        str(temporary),
                    ],
                    timeout=45,
                )
                if process.returncode or not temporary.is_file():
                    process = run(
                        [
                            ffmpeg(),
                            "-nostdin",
                            "-hide_banner",
                            "-loglevel",
                            "error",
                            "-y",
                            "-i",
                            file["path"],
                            "-ss",
                            str(seconds),
                            "-frames:v",
                            "1",
                            "-vf",
                            "scale='min(960,iw)':-2",
                            "-pix_fmt",
                            "yuvj420p",
                            "-threads",
                            "1",
                            "-q:v",
                            "3",
                            str(temporary),
                        ],
                        timeout=45,
                    )
                if process.returncode or not temporary.is_file():
                    raise ValueError("未能读取该视频画面")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return target

    @protected
    def proxy(self, file, cancelled=None):
        if not ffmpeg():
            raise ValueError("当前运行环境没有 FFmpeg，无法生成兼容预览")
        folder = self.folder(file)
        target = folder / "compatible.mp4"
        if target.is_file():
            return target
        with PROXY_DECODER:
            if target.is_file():
                return target
            temporary = folder / (threading.current_thread().name + ".mp4")
            try:
                process = run(
                    [
                        ffmpeg(),
                        "-nostdin",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        file["path"],
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a:0?",
                        "-vf",
                        "scale='min(1280,iw)':-2",
                        *video_encoder_args(),
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-ac",
                        "2",
                        "-b:a",
                        "128k",
                        "-movflags",
                        "+faststart",
                        "-threads",
                        "2",
                        str(temporary),
                    ],
                    timeout=600,
                    cancelled=cancelled,
                )
                if process.returncode:
                    raise ValueError(
                        "兼容预览生成失败：" + process.stderr.decode(errors="replace")[-400:]
                    )
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return target
