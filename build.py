"""Сборка exe с внедрением ключей из .env"""
import os
import sys
from pathlib import Path

# Читаем .env
env_vars = {}
env_file = Path(".env")
if env_file.exists():
    with open(env_file, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip().strip('"').strip("'")

# Генерируем код внедрения переменных
env_code = "import os\n"
for key, value in env_vars.items():
    env_code += f'os.environ["{key}"] = """{value}"""\n'

# Создаем runtime hook
hook_file = Path("_pyi_env_hook.py")
with open(hook_file, 'w', encoding='utf-8') as f:
    f.write(env_code)

# Обновляем spec файл с агрессивными excludes
spec_content = f"""# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['app\\\\main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'PySide6.QtNetwork', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineCore'],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=['{hook_file}'],
    excludes=[
        # Test/dev
        'matplotlib', 'numpy', 'pandas', 'scipy', 'pytest', 'unittest',
        'test', 'tests', '_pytest', 'py.test', 'IPython', 'jupyter', 'notebook',
        # Other GUI
        'tkinter', 'PyQt5', 'PyQt6', 'wx',
        # Docs
        'alabaster', 'sphinx', 'docutils', 'jinja2', 'pygments',
        # Build
        'setuptools', 'pip', 'wheel', 'lib2to3',
        # Unused
        'PIL.ImageQt', 'pytz', 'pydoc', 'xmlrpc',
        # PySide6 unused modules
        'PySide6.Qt3DAnimation', 'PySide6.Qt3DCore', 'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DRender',
        'PySide6.QtBluetooth', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtLocation',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtNfc',
        'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtPositioning',
        'PySide6.QtPrintSupport', 'PySide6.QtQml', 'PySide6.QtQuick',
        'PySide6.QtQuickControls2', 'PySide6.QtQuickWidgets', 'PySide6.QtRemoteObjects',
        'PySide6.QtScxml', 'PySide6.QtSensors', 'PySide6.QtSerialPort',
        'PySide6.QtSql', 'PySide6.QtStateMachine', 'PySide6.QtSvg', 'PySide6.QtSvgWidgets',
        'PySide6.QtTest', 'PySide6.QtTextToSpeech',
        'PySide6.QtWebSockets',
        'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        'PySide6.QtShaderTools', 'PySide6.QtSpatialAudio', 'PySide6.QtVirtualKeyboard',
        'PySide6.QtNetworkAuth',
    ],
    noarchive=False,
    optimize=2,
)

# Удаляем ненужные Qt DLL
exclude_binaries = [
    'Qt6Quick', 'Qt6Qml', 'Qt6Pdf', 'Qt6Charts',
    'Qt6DataVisualization', 'Qt63D', 'Qt6Bluetooth', 'Qt6Location',
    'Qt6Multimedia', 'Qt6Nfc', 'Qt6OpenGL', 'Qt6Positioning',
    'Qt6RemoteObjects', 'Qt6Scxml', 'Qt6Sensors', 'Qt6SerialPort',
    'Qt6Sql', 'Qt6StateMachine', 'Qt6Svg', 'Qt6Test', 'Qt6TextToSpeech',
    'Qt6VirtualKeyboard', 'Qt6WebSockets',
    'opengl32sw',
]
a.binaries = [b for b in a.binaries if not any(ex in b[0] for ex in exclude_binaries)]

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PDFAnnotationTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=['vcruntime140.dll', 'python*.dll', 'Qt6*.dll', 'icu*.dll'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"""

spec_file = Path("PDFAnnotationTool.spec")
with open(spec_file, 'w', encoding='utf-8') as f:
    f.write(spec_content)

print(f"[OK] Spec updated with {len(env_vars)} vars")
print(f"[OK] Runtime hook: {hook_file}")
print("\nRunning PyInstaller...")

os.system("pyinstaller PDFAnnotationTool.spec --clean")

# Очистка
if hook_file.exists():
    hook_file.unlink()
print("\n[OK] Build complete: dist\\PDFAnnotationTool.exe")
