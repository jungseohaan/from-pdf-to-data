# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

block_cipher = None

# 프로젝트 루트
project_root = os.path.dirname(os.path.abspath(SPEC))

# Poppler 바이너리 경로 (Homebrew)
poppler_bin = '/opt/homebrew/bin'
poppler_lib = '/opt/homebrew/lib'

# Poppler 바이너리
poppler_binaries = []
for binary in ['pdftoppm', 'pdfinfo', 'pdftotext']:
    bin_path = os.path.join(poppler_bin, binary)
    if os.path.exists(bin_path):
        poppler_binaries.append((bin_path, '.'))

# Poppler 라이브러리 (동적 링크)
poppler_libs = []
for lib in os.listdir(poppler_lib):
    if 'poppler' in lib and '.dylib' in lib:
        poppler_libs.append((os.path.join(poppler_lib, lib), '.'))
    elif any(dep in lib for dep in ['libjpeg', 'libpng', 'libtiff', 'libfreetype', 'libfontconfig', 'liblcms2', 'libopenjp2']) and '.dylib' in lib:
        lib_path = os.path.join(poppler_lib, lib)
        if os.path.exists(lib_path):
            poppler_libs.append((lib_path, '.'))

# 데이터 파일 (config 폴더, src 폴더)
datas = [
    (os.path.join(project_root, 'config', 'output_schema.json'), 'config'),
    (os.path.join(project_root, 'config', 'solution_schema.json'), 'config'),
    (os.path.join(project_root, 'src'), 'src'),
]

# .env.example 포함
env_example = os.path.join(project_root, '.env.example')
if os.path.exists(env_example):
    datas.append((env_example, '.'))

a = Analysis(
    ['run_labeler.py'],
    pathex=[project_root],
    binaries=poppler_binaries + poppler_libs,
    datas=datas,
    hiddenimports=[
        # PyQt5
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtNetwork',
        'PyQt5.sip',
        'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtWebEngineCore',
        'PyQt5.QtWebChannel',
        'PyQt5.QtPrintSupport',
        # PIL/Pillow
        'PIL',
        'PIL.Image',
        'PIL._imaging',
        # PDF
        'pdf2image',
        'pdf2image.pdf2image',
        # OpenAI / Gemini
        'openai',
        'google.genai',
        'google.generativeai',
        'google.ai.generativelanguage',
        # Google Auth
        'google.auth',
        'google.auth.transport',
        'google.auth.transport.requests',
        'google_auth_oauthlib',
        'google_auth_oauthlib.flow',
        'googleapiclient',
        'googleapiclient.discovery',
        # Supabase
        'supabase',
        'postgrest',
        'realtime',
        'storage3',
        # 기타
        'dotenv',
        'json',
        'httpx',
        'httpcore',
        'h11',
        'certifi',
        'charset_normalizer',
        'idna',
        'urllib3',
        'requests',
        # 내부 모듈
        'src',
        'src.models',
        'src.widgets',
        'src.canvas',
        'src.config',
        'src.dialogs',
        'src.settings_dialog',
        'src.ai_analyzer',
        'src.persistence',
        'src.theme_manager',
        'src.gemini_api',
        'src.google_auth',
        'src.embedding',
        'src.supabase_client',
        'src.supabase_sync',
        'src.labeler',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 불필요한 대용량 라이브러리 제외
        'numpy',
        'cv2',
        'opencv',
        'opencv-python',
        'opencv-python-headless',
        'torch',
        'torchvision',
        'tensorflow',
        'transformers',
        'timm',
        'onnxruntime',
        'pyarrow',
        'altair',
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'sphinx',
        'docutils',
        'jedi',
        'parso',
        'pytesseract',
    ],
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
    bundle_identifier='com.millisquare.pdflabeler',
    info_plist={
        'CFBundleName': 'PDF문항레이블러',
        'CFBundleDisplayName': 'PDF 문항 레이블러',
        'CFBundleVersion': '1.1.0',
        'CFBundleShortVersionString': '1.1.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15.0',
        'NSRequiresAquaSystemAppearance': False,
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'PDF Document',
                'CFBundleTypeRole': 'Viewer',
                'LSHandlerRank': 'Alternate',
                'LSItemContentTypes': ['com.adobe.pdf'],
            }
        ],
    },
)
