"""Replace PE icon/version resources while preserving executable code and imports."""
from pathlib import Path
import hashlib
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".build/packaging-libs"))
import lief

from build_release import VERSION


def pad(value):
    return value + b"\0" * ((-len(value)) % 4)


def block(key, value=b"", children=(), kind=1, length=None):
    if length is None:
        length = len(value) // 2 if kind else len(value)
    data = pad(b"\0" * 6 + (key + "\0").encode("utf-16le")) + value
    if children:
        data = pad(data) + b"".join(pad(child) for child in children)
    return struct.pack("<HHH", len(data), length, kind) + data[6:]


def version_resource():
    fields = {
        "ProductName": "素材中心",
        "FileDescription": "素材中心",
        "InternalName": "MaterialCenter",
        "OriginalFilename": "素材中心.exe",
        "FileVersion": VERSION,
        "ProductVersion": VERSION,
    }
    strings = [
        block(key, (value + "\0").encode("utf-16le")) for key, value in fields.items()
    ]
    major, minor, patch = map(int, VERSION.split("."))
    high, low = (major << 16) | minor, patch << 16
    fixed = struct.pack(
        "<13I", 0xFEEF04BD, 0x10000, high, low, high, low, 0x3F, 0, 0x40004, 1, 0, 0, 0
    )
    return block(
        "VS_VERSION_INFO",
        fixed,
        [
            block("StringFileInfo", children=[block("040904B0", children=strings)]),
            block(
                "VarFileInfo",
                children=[block("Translation", struct.pack("<HH", 1033, 1200), kind=0)],
            ),
        ],
        kind=0,
    )


def directory(identifier, children):
    node = lief.PE.ResourceDirectory()
    node.id = identifier
    for child in children:
        node.add_child(child)
    return node


def data(identifier, content):
    node = lief.PE.ResourceData(list(content), 0)
    node.id = identifier
    return node


def apply(filename):
    binary = lief.PE.parse(str(filename))
    original_text = hashlib.sha256(
        bytes(binary.get_section(".text").content)
    ).hexdigest()
    entrypoint = binary.optional_header.addressof_entrypoint
    imports = [item.name for item in binary.imports]
    ico = (ROOT / "assets/app-icon.ico").read_bytes()
    _, kind, count = struct.unpack_from("<HHH", ico)
    assert kind == 1
    images = []
    group = struct.pack("<HHH", 0, 1, count)
    for index in range(count):
        (
            width,
            height,
            colors,
            reserved,
            planes,
            bits,
            size,
            offset,
        ) = struct.unpack_from("<BBBBHHII", ico, 6 + 16 * index)
        content = ico[offset : offset + size]
        images.append(directory(index + 1, [data(1033, content)]))
        group += struct.pack(
            "<BBBBHHIH", width, height, colors, reserved, planes, bits, size, index + 1
        )
    root = binary.resources
    for identifier in [3, 14, 16]:
        root.delete_child(identifier)
    root.add_child(directory(3, images))
    root.add_child(directory(14, [directory(1, [data(1033, group)])]))
    root.add_child(directory(16, [directory(1, [data(1033, version_resource())])]))
    # Resource changes invalidate any original Authenticode signature.
    certificate = binary.data_directory(lief.PE.DataDirectory.TYPES.CERTIFICATE_TABLE)
    certificate.rva = 0
    certificate.size = 0
    config = lief.PE.Builder.config_t()
    config.resources = True
    builder = lief.PE.Builder(binary, config)
    builder.build()
    temporary = filename.with_suffix(".branded.exe")
    builder.write(str(temporary))
    result = lief.PE.parse(str(temporary))
    assert (
        hashlib.sha256(bytes(result.get_section(".text").content)).hexdigest()
        == original_text
    )
    assert result.optional_header.addressof_entrypoint == entrypoint
    assert [item.name for item in result.imports] == imports
    icons = next(child for child in result.resources.childs if child.id == 3)
    assert len(icons.childs) == count
    version = next(child for child in result.resources.childs if child.id == 16)
    assert "素材中心".encode("utf-16le") in bytes(version.childs[0].childs[0].content)
    temporary.replace(filename)
    print("Windows 程序图标与名称已更新；代码段、入口点和导入库保持一致")


if __name__ == "__main__":
    apply(Path(sys.argv[1]))
