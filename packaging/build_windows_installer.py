"""Create a per-user offline NSIS installer and a ZIP containing that installer."""
import os
from pathlib import Path
import subprocess
import zipfile
from build_release import BUILD, OUTPUT, ROOT, VERSION

stage = BUILD / "win-release"
installer = OUTPUT / f"素材中心-{VERSION}-Windows-x64-安装程序.exe"
bundle = BUILD / "nsis-toolset/nsis-bundle"


def quote(value):
    return str(value).replace("$", "$$").replace('"', '$\\"')


files = sorted(p for p in stage.rglob("*") if p.is_file())
directories = sorted(
    (p for p in stage.rglob("*") if p.is_dir()),
    key=lambda p: len(p.parts),
    reverse=True,
)
# Only delete files owned by this release; never recursively delete the user's selected directory.
deletions = "\n".join(
    '  Delete "$INSTDIR\\' + quote(str(p.relative_to(stage)).replace("/", "\\")) + '"'
    for p in files
)
remove_dirs = "\n".join(
    '  RMDir "$INSTDIR\\' + quote(str(p.relative_to(stage)).replace("/", "\\")) + '"'
    for p in directories
)
script = f"""
Unicode True
!include "MUI2.nsh"
!include "x64.nsh"
Name "素材中心"
OutFile "{quote(installer)}"
InstallDir "$LOCALAPPDATA\\Programs\\MaterialCenter"
InstallDirRegKey HKCU "Software\\MaterialCenter" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 32
CRCCheck on
VIProductVersion "{VERSION}.0"
VIAddVersionKey /LANG=2052 "ProductName" "素材中心"
VIAddVersionKey /LANG=2052 "FileDescription" "素材中心安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "{VERSION}"
VIAddVersionKey /LANG=2052 "ProductVersion" "{VERSION}"
VIAddVersionKey /LANG=2052 "LegalCopyright" ""
!define MUI_ICON "{quote(ROOT/'assets/app-icon.ico')}"
!define MUI_UNICON "{quote(ROOT/'assets/app-icon.ico')}"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "欢迎安装素材中心"
!define MUI_WELCOMEPAGE_TEXT "将为当前用户安装素材中心。请先退出旧版程序。原有资料库、收藏与标签会保留。"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\\素材中心.exe"
!define MUI_FINISHPAGE_RUN_NOTCHECKED
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Function .onInit
  ${{IfNot}} ${{RunningX64}}
    MessageBox MB_OK|MB_ICONSTOP "此版本需要 64 位 Windows 10 或 Windows 11。"
    Abort
  ${{EndIf}}
  SetShellVarContext current
FunctionEnd

Section "素材中心（必需）" Core
  SectionIn RO
  SetOutPath "$INSTDIR"
  SetOverwrite on
  File /r "{quote(stage)}/*"
  WriteUninstaller "$INSTDIR\\卸载素材中心.exe"
  CreateDirectory "$SMPROGRAMS\\素材中心"
  CreateShortCut "$SMPROGRAMS\\素材中心\\素材中心.lnk" "$INSTDIR\\素材中心.exe" "" "$INSTDIR\\素材中心-{VERSION}.ico"
  CreateShortCut "$SMPROGRAMS\\素材中心\\卸载素材中心.lnk" "$INSTDIR\\卸载素材中心.exe"
  WriteRegStr HKCU "Software\\MaterialCenter" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MaterialCenter" "DisplayName" "素材中心"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MaterialCenter" "DisplayVersion" "{VERSION}"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MaterialCenter" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MaterialCenter" "DisplayIcon" '$\\"$INSTDIR\\素材中心-{VERSION}.ico$\\",0'
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MaterialCenter" "UninstallString" '$\\"$INSTDIR\\卸载素材中心.exe$\\"'
  WriteRegDWORD HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MaterialCenter" "NoModify" 1
  WriteRegDWORD HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MaterialCenter" "NoRepair" 1
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd

Section "桌面快捷方式" DesktopShortcut
  CreateShortCut "$DESKTOP\\素材中心.lnk" "$INSTDIR\\素材中心.exe" "" "$INSTDIR\\素材中心-{VERSION}.ico"
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  MessageBox MB_OKCANCEL|MB_ICONINFORMATION "卸载前请退出素材中心。卸载仅移除程序，资料库、收藏和标签会保留。" IDOK +2
  Abort
  ClearErrors
  Delete "$INSTDIR\\素材中心.exe"
  IfErrors 0 +3
    MessageBox MB_OK|MB_ICONSTOP "无法移除正在使用的程序。请退出素材中心后重试。"
    Abort
{deletions}
{remove_dirs}
  Delete "$INSTDIR\\卸载素材中心.exe"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\\素材中心.lnk"
  Delete "$SMPROGRAMS\\素材中心\\素材中心.lnk"
  Delete "$SMPROGRAMS\\素材中心\\卸载素材中心.lnk"
  RMDir "$SMPROGRAMS\\素材中心"
  DeleteRegKey HKCU "Software\\MaterialCenter"
  DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MaterialCenter"
SectionEnd
"""
source = BUILD / "material-center-installer.nsi"
source.write_text(script, encoding="utf-8-sig")
environment = {**os.environ, "NSISDIR": str(bundle / "windows")}
subprocess.run(
    [str(bundle / "mac/arm64/makensis"), "-V3", str(source)],
    env=environment,
    check=True,
)
archive = OUTPUT / f"素材中心-{VERSION}-Windows-x64-安装包.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(installer, installer.name)
    z.write(ROOT / "packaging/安装说明-Windows.txt", "安装说明.txt")
print(archive)
