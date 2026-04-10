"""
Core Structure - Сборка в исполняемый файл

Скрипт для сборки приложения Core Structure в .exe файл.
Файл .env вшивается в бинарник через datas — приложение загружает его
из sys._MEIPASS при старте (app/main.py).
"""
import os
import sys
from pathlib import Path

env_path = Path(".env")
if not env_path.exists():
    print("[ERROR] .env file not found in project root")
    sys.exit(1)

spec_content = r"""# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['app\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('.env', '.')],
    hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'scipy', 'pytest', 'unittest',
        'test', 'tests', '_pytest', 'py.test', 'tkinter', 'IPython', 'jupyter',
        'PyQt5', 'PyQt6', 'wx', 'alabaster', 'sphinx', 'docutils', 'jinja2',
        'pygments', 'setuptools', 'pip', 'wheel',
        'PIL.ImageQt', 'pytz'
    ],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CoreStructure',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"""

spec_file = Path("CoreStructure.spec")
with open(spec_file, "w", encoding="utf-8") as f:
    f.write(spec_content)

print("[OK] Spec updated (.env embedded via datas)")
print("\nRunning PyInstaller...")

os.system("pyinstaller CoreStructure.spec")

print("\n[OK] Build complete: dist\\CoreStructure.exe")
print("[INFO] .env is embedded — no external .env needed")
