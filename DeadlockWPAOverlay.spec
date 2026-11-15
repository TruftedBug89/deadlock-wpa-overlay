# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys
sys.path.insert(0, str(Path(SPECPATH)))
from build_assets import create_artwork
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct,
)

# Read only the public, source-controlled version constant.
version_scope = {}
exec((Path(SPECPATH) / "version.py").read_text(encoding="utf-8"), version_scope)
version = version_scope["VERSION"]
version_tuple = tuple(int(part) for part in version.split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple,
                     mask=0x3f, flags=0, OS=0x40004, fileType=1,
                     subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable("040904B0", [
        StringStruct("FileDescription", "Deadlock WPA Overlay"),
        StringStruct("FileVersion", version),
        StringStruct("ProductName", "Deadlock WPA Overlay"),
        StringStruct("ProductVersion", version),
        StringStruct("OriginalFilename", "DeadlockWPAOverlay.exe"),
    ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
)
winrt_datas = collect_data_files('winrt')
winrt_subs = collect_submodules('winrt')

# No preferences, match data, caches or downloaded game icons in a build.
artwork_paths = create_artwork(Path(SPECPATH) / "build" / "public_assets")
public_artwork = [(str(path), 'assets') for path in artwork_paths]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=public_artwork + winrt_datas,
    hiddenimports=[
        'pystray',
        'pystray._win32',
        'PIL',
        'PIL.ImageTk',
        'ocr_engine',
        'ocr_matcher',
        'ui.drag_handler',
        'ui.hud_presentation',
        # Windows OCR (split WinRT wheels).
        'winrt',
        'winrt.runtime',
        'winrt.system',
        'winrt.windows.foundation',
        'winrt.windows.foundation.collections',
        'winrt.windows.graphics.imaging',
        'winrt.windows.media.ocr',
        'winrt.windows.storage',
        'winrt.windows.storage.streams',
    ] + winrt_subs,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Windows-only app: never ship the other tray backends or the
        # numpy test/fortran tooling the overlay never executes.
        'pystray._xorg',
        'pystray._gtk',
        'pystray._darwin',
        'pystray._appindicator',
        'pystray._util.notify_dbus',
        'pystray._util.gtk',
        'numpy.testing',
        'numpy.f2py',
        'numpy.distutils',
        # Ancient image formats the overlay never opens (.fpx/.mic).
        'PIL.FpxImagePlugin',
        'PIL.MicImagePlugin',
        'olefile',
        'defusedxml',
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DeadlockWPAOverlay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(artwork_paths[0])],
    version=version_info,
)
