"""Load optional, architecture-matched media decoders from offline packages."""
import os
from pathlib import Path
import sys


def configure_media_libraries():
    configured = os.environ.get("SUCAIYU_MEDIA_LIBS")
    if configured:
        directory = Path(configured)
    else:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        target = "win-x64" if sys.platform == "win32" else "mac-arm64"
        directory = base / "vendor" / target
    if directory.is_dir():
        sys.path.insert(0, str(directory))
