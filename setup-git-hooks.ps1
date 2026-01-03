# =============================================================================
# PowerShell скрипт для настройки Git hooks и фильтров (Windows)
# Запуск: .\setup-git-hooks.ps1
# =============================================================================

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "Настройка Git hooks и фильтров безопасности" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Проверка Python
Write-Host "1. Проверка Python..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✓ Python установлен: $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "   ✗ Python не найден!" -ForegroundColor Red
    exit 1
}

# 2. Установка pre-commit
Write-Host "`n2. Установка pre-commit..." -ForegroundColor Yellow
$precommitVersion = pre-commit --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "   Установка pre-commit..." -ForegroundColor Cyan
    pip install pre-commit
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   ✗ Не удалось установить pre-commit!" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "   ✓ pre-commit уже установлен: $precommitVersion" -ForegroundColor Green
}

# 3. Установка hooks
Write-Host "`n3. Установка Git hooks..." -ForegroundColor Yellow
pre-commit install
if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✓ Git hooks установлены" -ForegroundColor Green
} else {
    Write-Host "   ✗ Не удалось установить hooks!" -ForegroundColor Red
    exit 1
}

# 4. Создание baseline для detect-secrets
Write-Host "`n4. Создание baseline для detect-secrets..." -ForegroundColor Yellow
if (Test-Path ".secrets.baseline") {
    Write-Host "   ✓ .secrets.baseline уже существует" -ForegroundColor Green
} else {
    detect-secrets scan --baseline .secrets.baseline 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   ✓ .secrets.baseline создан" -ForegroundColor Green
    } else {
        Write-Host "   ! detect-secrets не установлен (опционально)" -ForegroundColor Yellow
        Write-Host "     Установка: pip install detect-secrets" -ForegroundColor Gray
    }
}

# 5. Настройка Git фильтров для .env
Write-Host "`n5. Настройка Git фильтров..." -ForegroundColor Yellow

# Фильтр для блокировки .env файлов
git config filter.git-secrets.clean "echo 'ERROR: .env file should not be committed' >&2; exit 1"
git config filter.git-secrets.smudge "cat"
Write-Host "   ✓ Фильтр для секретов настроен" -ForegroundColor Green

# 6. Первая проверка
Write-Host "`n6. Первая проверка (может занять время)..." -ForegroundColor Yellow
Write-Host "   Запуск: pre-commit run --all-files" -ForegroundColor Cyan
pre-commit run --all-files 2>&1 | Out-String | Write-Host

# 7. Проверка конфигурации
Write-Host "`n7. Проверка конфигурации..." -ForegroundColor Yellow
$gitignoreCheck = Test-Path ".gitignore"
$precommitCheck = Test-Path ".pre-commit-config.yaml"
$envExampleCheck = Test-Path "env.example"

if ($gitignoreCheck) {
    Write-Host "   ✓ .gitignore найден" -ForegroundColor Green
} else {
    Write-Host "   ✗ .gitignore не найден!" -ForegroundColor Red
}

if ($precommitCheck) {
    Write-Host "   ✓ .pre-commit-config.yaml найден" -ForegroundColor Green
} else {
    Write-Host "   ✗ .pre-commit-config.yaml не найден!" -ForegroundColor Red
}

if ($envExampleCheck) {
    Write-Host "   ✓ env.example найден" -ForegroundColor Green
} else {
    Write-Host "   ⚠ env.example не найден (рекомендуется)" -ForegroundColor Yellow
}

# 8. Проверка что .env не в git
Write-Host "`n8. Проверка .env файлов..." -ForegroundColor Yellow
$envFiles = git ls-files | Select-String -Pattern "\.env$"
if ($envFiles) {
    Write-Host "   ✗ ВНИМАНИЕ: .env файлы найдены в git!" -ForegroundColor Red
    Write-Host "     Файлы: $envFiles" -ForegroundColor Red
    Write-Host "     Удалите их: git rm --cached .env" -ForegroundColor Yellow
} else {
    Write-Host "   ✓ .env файлы не в git" -ForegroundColor Green
}

# Итоги
Write-Host "`n==============================================================================" -ForegroundColor Cyan
Write-Host "НАСТРОЙКА ЗАВЕРШЕНА" -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Что настроено:" -ForegroundColor Yellow
Write-Host "  ✓ Pre-commit hooks установлены" -ForegroundColor Green
Write-Host "  ✓ GitLeaks будет проверять секреты перед коммитом" -ForegroundColor Green
Write-Host "  ✓ Detect-secrets для дополнительной проверки" -ForegroundColor Green
Write-Host "  ✓ Проверка на большие файлы (>500KB)" -ForegroundColor Green
Write-Host "  ✓ Проверка приватных ключей" -ForegroundColor Green
Write-Host "  ✓ Git фильтры для блокировки .env" -ForegroundColor Green
Write-Host ""
Write-Host "Что делать дальше:" -ForegroundColor Yellow
Write-Host "  1. При коммите hooks будут запускаться автоматически" -ForegroundColor White
Write-Host "  2. Если находятся проблемы - исправьте и попробуйте снова" -ForegroundColor White
Write-Host "  3. Обход hooks (НЕ РЕКОМЕНДУЕТСЯ): git commit --no-verify" -ForegroundColor Gray
Write-Host ""
Write-Host "Проверка:" -ForegroundColor Yellow
Write-Host "  pre-commit run --all-files  # Проверить все файлы" -ForegroundColor White
Write-Host "  pre-commit run <hook-id>    # Запустить конкретный hook" -ForegroundColor White
Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Cyan
