"""
Core Structure - Сборка в исполняемый файл

Скрипт для сборки приложения Core Structure в .exe файл
с внедрением переменных окружения из .env файла.
"""
import os
import sys
from pathlib import Path

# Читаем .env (ТОЛЬКО безопасные переменные для внедрения)
SAFE_ENV_VARS = {
    "REMOTE_OCR_BASE_URL",  # Публичный URL сервера
}

env_vars = {}
env_file = Path(".env")
if env_file.exists():
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                # Внедряем ТОЛЬКО безопасные переменные
                if key in SAFE_ENV_VARS:
                    env_vars[key] = value.strip().strip('"').strip("'")

# Генерируем код внедрения переменных
env_code = "import os\n"
env_code += "# ВНИМАНИЕ: Секретные ключи НЕ внедрены в exe!\n"
env_code += "# Создайте .env файл рядом с CoreStructure.exe:\n"
env_code += "# REMOTE_OCR_API_KEY=your_key\n\n"
for key, value in env_vars.items():
    env_code += f'os.environ["{key}"] = """{value}"""\n'

# Создаем runtime hook
hook_file = Path("_pyi_env_hook.py")
with open(hook_file, "w", encoding="utf-8") as f:
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

print(f"[OK] Spec updated with {len(env_vars)} safe vars (secrets excluded)")
print(f"[OK] Runtime hook: {hook_file}")
print("\n⚠️  ВАЖНО: Секретные ключи НЕ внедрены в exe!")
print("Создайте .env файл рядом с CoreStructure.exe с содержимым:")
print("  REMOTE_OCR_API_KEY=your_key_here")
print("\nRunning PyInstaller...")

os.system("pyinstaller CoreStructure.spec")

# Очистка
if hook_file.exists():
    hook_file.unlink()
print("\n[OK] Build complete: dist\\CoreStructure.exe")
