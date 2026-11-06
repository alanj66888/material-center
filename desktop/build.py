#!/usr/bin/env python3
import plistlib
import subprocess
from pathlib import Path

base = Path(__file__).resolve().parents[1]
app = base / '素材屿桌面版.app'
contents = app / 'Contents'
(contents / 'MacOS').mkdir(parents=True, exist_ok=True)
info = {'CFBundleName': '素材中心', 'CFBundleDisplayName': '素材中心', 'CFBundleIdentifier': 'local.sucaiyu.desktop', 'CFBundleExecutable': 'Sucaiyu', 'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1', 'CFBundleShortVersionString': '0.1', 'NSHighResolutionCapable': True, 'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True}, 'LibraryProjectPath': str(base)}
with (contents / 'Info.plist').open('wb') as f:
    plistlib.dump(info, f)
subprocess.run(['swiftc', '-parse-as-library', '-module-cache-path', '/tmp/sucaiyu-swift-cache', str(base / 'desktop/main.swift'), '-o', str(contents / 'MacOS/Sucaiyu'), '-framework', 'Cocoa', '-framework', 'WebKit'], check=True)
subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
print(app)
