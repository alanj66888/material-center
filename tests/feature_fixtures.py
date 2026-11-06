"""Small generated fixtures: no private NAS media are changed or redistributed."""
from pathlib import Path
import struct


def make_dng(path, width=128, height=96):
    entries = []

    def tag(number, kind, values):
        if kind == 2:
            payload = values.encode() + b"\0"
            count = len(payload)
        elif kind == 1:
            payload = bytes(values)
            count = len(values)
        elif kind == 3:
            payload = struct.pack("<" + "H" * len(values), *values)
            count = len(values)
        elif kind == 4:
            payload = struct.pack("<" + "I" * len(values), *values)
            count = len(values)
        elif kind in (5, 10):
            payload = struct.pack(
                "<" + ("I" if kind == 5 else "i") * len(values), *values
            )
            count = len(values) // 2
        entries.append((number, kind, count, payload))

    for number, kind, values in [
        (254, 4, [0]),
        (256, 4, [width]),
        (257, 4, [height]),
        (258, 3, [16]),
        (259, 3, [1]),
        (262, 3, [32803]),
        (271, 2, "Material Center"),
        (272, 2, "Test Camera"),
        (273, 4, [0]),
        (274, 3, [1]),
        (277, 3, [1]),
        (278, 4, [height]),
        (279, 4, [width * height * 2]),
        (284, 3, [1]),
        (33421, 3, [2, 2]),
        (33422, 1, [0, 1, 1, 2]),
        (50706, 1, [1, 4, 0, 0]),
        (50707, 1, [1, 1, 0, 0]),
        (50708, 2, "Material Center Test Camera"),
        (50710, 1, [0, 1, 2]),
        (50711, 3, [1]),
        (50713, 3, [1, 1]),
        (50714, 5, [0, 1]),
        (50717, 4, [65535]),
        (50719, 5, [0, 1, 0, 1]),
        (50720, 5, [width, 1, height, 1]),
        (50721, 10, [1, 1, 0, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1, 1, 1]),
        (50728, 5, [1, 1, 1, 1, 1, 1]),
        (50778, 3, [21]),
    ]:
        tag(number, kind, values)
    entries.sort()
    offset = 8 + 2 + len(entries) * 12 + 4
    extra = bytearray()
    records = []
    for number, kind, count, payload in entries:
        if len(payload) <= 4:
            value = payload.ljust(4, b"\0")
        else:
            value = struct.pack("<I", offset + len(extra))
            extra.extend(payload)
            if len(extra) % 2:
                extra.append(0)
        records.append([number, kind, count, value])
    pixels_offset = offset + len(extra)
    for record in records:
        if record[0] == 273:
            record[3] = struct.pack("<I", pixels_offset)
    pixels = []
    for y in range(height):
        for x in range(width):
            value = 12000 + int(
                35000
                * (
                    x / width
                    if y % 2 == 0 and x % 2 == 0
                    else y / height
                    if (x + y) % 2
                    else 0.7
                )
            )
            pixels.append(value)
    data = b"II" + struct.pack("<HIH", 42, 8, len(records))
    data += (
        b"".join(struct.pack("<HHI", *record[:3]) + record[3] for record in records)
        + b"\0" * 4
        + extra
        + struct.pack("<" + "H" * len(pixels), *pixels)
    )
    Path(path).write_bytes(data)


def make_media(folder):
    from PIL import Image, ImageDraw
    from media_support import ffmpeg, run, video_encoder_args

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (800, 450), (39, 65, 95))
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((80, 90, 710, 360), fill=(77, 139, 185))
    drawing.text((110, 170), "MATERIAL CENTER / PREVIEW TEST", fill="white")
    image.save(folder / "01_图片预览.jpg")
    image.save(folder / "02_TIFF图片.tiff")
    make_dng(folder / "03_RAW原片.DNG")
    if ffmpeg():
        output = run(
            [
                ffmpeg(),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=25",
                "-t",
                "2",
                *video_encoder_args(),
                "-pix_fmt",
                "yuv420p",
                "-f",
                "mpegts",
                str(folder / "04_相机素材.MTS"),
            ]
        )
        if output.returncode:
            raise RuntimeError(output.stderr.decode(errors="replace"))
        output = run(
            [
                ffmpeg(),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(folder / "04_相机素材.MTS"),
                "-c:v",
                "copy",
                "-movflags",
                "+faststart",
                str(folder / "05_常规视频.mp4"),
            ]
        )
        if output.returncode:
            raise RuntimeError(output.stderr.decode(errors="replace"))
    (folder / "06_可测试删除还原.txt").write_text(
        "这是生成的测试素材。可用于验证回收站和还原，不是 NAS 原始素材。", encoding="utf-8"
    )
    (folder / "A_按字母分类").mkdir(exist_ok=True)
    (folder / "B_项目分类").mkdir(exist_ok=True)
    (folder / "中文目录").mkdir(exist_ok=True)
