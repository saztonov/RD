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

# Обновляем spec файл
spec_content = f"""# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['app\\\\main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets'],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=['{hook_file}'],
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
    name='PDFAnnotationTool',
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

spec_file = Path("PDFAnnotationTool.spec")
with open(spec_file, 'w', encoding='utf-8') as f:
    f.write(spec_content)

print(f"✓ Spec обновлен с {len(env_vars)} переменными")
print(f"✓ Runtime hook создан: {hook_file}")
print("\nЗапуск PyInstaller...")

os.system("pyinstaller PDFAnnotationTool.spec")

# Очистка
if hook_file.exists():
    hook_file.unlink()
print("\n✓ Сборка завершена: dist\\PDFAnnotationTool.exe")

