"""Convert the supplied dark PNG to native application icon containers."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".build/release-media-noncommercial/mac-arm64"))
from PIL import Image

source = ROOT / "web/icon-dark.png"
assets = ROOT / "assets"
image = Image.open(source).convert("RGBA")
image.save(
    assets / "app-icon.ico",
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
shutil.copy2(source, assets / "app-icon.png")
iconset = ROOT / ".build/MaterialCenter.iconset"
iconset.mkdir(exist_ok=True)
for size in [16, 32, 128, 256, 512]:
    for scale in [1, 2]:
        name = f"icon_{size}x{size}" + ("@2x" if scale == 2 else "") + ".png"
        image.resize((size * scale, size * scale), Image.Resampling.LANCZOS).save(
            iconset / name
        )
subprocess.run(
    ["iconutil", "-c", "icns", str(iconset), "-o", str(assets / "AppIcon.icns")],
    check=True,
)
print("Dark artwork converted to ICO and ICNS")
