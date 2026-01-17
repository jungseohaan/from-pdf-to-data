# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

# Poppler 바이너리 경로
poppler_bin = '/opt/homebrew/bin'
poppler_binaries = [
    (os.path.join(poppler_bin, 'pdftoppm'), '.'),
    (os.path.join(poppler_bin, 'pdfinfo'), '.'),
]

# Poppler 라이브러리 경로
poppler_lib = '/opt/homebrew/lib'
poppler_libs = []
for lib in os.listdir(poppler_lib):
    if lib.startswith('libpoppler') and '.dylib' in lib:
        poppler_libs.append((os.path.join(poppler_lib, lib), '.'))

a = Analysis(
    ['src/labeler.py'],
    pathex=[],
    binaries=poppler_binaries + poppler_libs,
    datas=[],
    hiddenimports=[
        'PIL',
        'PIL.Image',
        'pdf2image',
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PDF문항레이블러',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PDF문항레이블러',
)

app = BUNDLE(
    coll,
    name='PDF문항레이블러.app',
    icon=None,
    bundle_identifier='com.pdflabeler.app',
    info_plist={
        'CFBundleName': 'PDF문항레이블러',
        'CFBundleDisplayName': 'PDF 문항 레이블러',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.13.0',
    },
)
