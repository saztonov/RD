#!/bin/bash
# =============================================================================
# Bash скрипт для настройки Git hooks и фильтров (Linux/Mac)
# Запуск: chmod +x setup-git-hooks.sh && ./setup-git-hooks.sh
# =============================================================================

set -e

echo "=============================================================================="
echo "Настройка Git hooks и фильтров безопасности"
echo "=============================================================================="
echo ""

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 1. Проверка Python
echo -e "${YELLOW}1. Проверка Python...${NC}"
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo -e "${GREEN}   ✓ Python установлен: $PYTHON_VERSION${NC}"
    PYTHON_CMD=python3
elif command -v python &> /dev/null; then
    PYTHON_VERSION=$(python --version)
    echo -e "${GREEN}   ✓ Python установлен: $PYTHON_VERSION${NC}"
    PYTHON_CMD=python
else
    echo -e "${RED}   ✗ Python не найден!${NC}"
    exit 1
fi

# 2. Установка pre-commit
echo -e "\n${YELLOW}2. Установка pre-commit...${NC}"
if command -v pre-commit &> /dev/null; then
    PRECOMMIT_VERSION=$(pre-commit --version)
    echo -e "${GREEN}   ✓ pre-commit уже установлен: $PRECOMMIT_VERSION${NC}"
else
    echo -e "${CYAN}   Установка pre-commit...${NC}"
    $PYTHON_CMD -m pip install pre-commit
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}   ✓ pre-commit установлен${NC}"
    else
        echo -e "${RED}   ✗ Не удалось установить pre-commit!${NC}"
        exit 1
    fi
fi

# 3. Установка hooks
echo -e "\n${YELLOW}3. Установка Git hooks...${NC}"
pre-commit install
if [ $? -eq 0 ]; then
    echo -e "${GREEN}   ✓ Git hooks установлены${NC}"
else
    echo -e "${RED}   ✗ Не удалось установить hooks!${NC}"
    exit 1
fi

# 4. Создание baseline для detect-secrets
echo -e "\n${YELLOW}4. Создание baseline для detect-secrets...${NC}"
if [ -f ".secrets.baseline" ]; then
    echo -e "${GREEN}   ✓ .secrets.baseline уже существует${NC}"
else
    if command -v detect-secrets &> /dev/null; then
        detect-secrets scan --baseline .secrets.baseline 2>/dev/null
        echo -e "${GREEN}   ✓ .secrets.baseline создан${NC}"
    else
        echo -e "${YELLOW}   ! detect-secrets не установлен (опционально)${NC}"
        echo -e "     Установка: pip install detect-secrets"
    fi
fi

# 5. Настройка Git фильтров
echo -e "\n${YELLOW}5. Настройка Git фильтров...${NC}"

# Фильтр для блокировки .env файлов
git config filter.git-secrets.clean "echo 'ERROR: .env file should not be committed' >&2; exit 1"
git config filter.git-secrets.smudge "cat"
echo -e "${GREEN}   ✓ Фильтр для секретов настроен${NC}"

# 6. Первая проверка
echo -e "\n${YELLOW}6. Первая проверка (может занять время)...${NC}"
echo -e "${CYAN}   Запуск: pre-commit run --all-files${NC}"
pre-commit run --all-files || true

# 7. Проверка конфигурации
echo -e "\n${YELLOW}7. Проверка конфигурации...${NC}"
if [ -f ".gitignore" ]; then
    echo -e "${GREEN}   ✓ .gitignore найден${NC}"
else
    echo -e "${RED}   ✗ .gitignore не найден!${NC}"
fi

if [ -f ".pre-commit-config.yaml" ]; then
    echo -e "${GREEN}   ✓ .pre-commit-config.yaml найден${NC}"
else
    echo -e "${RED}   ✗ .pre-commit-config.yaml не найден!${NC}"
fi

if [ -f "env.example" ]; then
    echo -e "${GREEN}   ✓ env.example найден${NC}"
else
    echo -e "${YELLOW}   ⚠ env.example не найден (рекомендуется)${NC}"
fi

# 8. Проверка что .env не в git
echo -e "\n${YELLOW}8. Проверка .env файлов...${NC}"
ENV_FILES=$(git ls-files | grep "\.env$" || true)
if [ -n "$ENV_FILES" ]; then
    echo -e "${RED}   ✗ ВНИМАНИЕ: .env файлы найдены в git!${NC}"
    echo -e "${RED}     Файлы: $ENV_FILES${NC}"
    echo -e "${YELLOW}     Удалите их: git rm --cached .env${NC}"
else
    echo -e "${GREEN}   ✓ .env файлы не в git${NC}"
fi

# Итоги
echo -e "\n${CYAN}==============================================================================${NC}"
echo -e "${GREEN}НАСТРОЙКА ЗАВЕРШЕНА${NC}"
echo -e "${CYAN}==============================================================================${NC}"
echo ""
echo -e "${YELLOW}Что настроено:${NC}"
echo -e "${GREEN}  ✓ Pre-commit hooks установлены${NC}"
echo -e "${GREEN}  ✓ GitLeaks будет проверять секреты перед коммитом${NC}"
echo -e "${GREEN}  ✓ Detect-secrets для дополнительной проверки${NC}"
echo -e "${GREEN}  ✓ Проверка на большие файлы (>500KB)${NC}"
echo -e "${GREEN}  ✓ Проверка приватных ключей${NC}"
echo -e "${GREEN}  ✓ Git фильтры для блокировки .env${NC}"
echo ""
echo -e "${YELLOW}Что делать дальше:${NC}"
echo "  1. При коммите hooks будут запускаться автоматически"
echo "  2. Если находятся проблемы - исправьте и попробуйте снова"
echo "  3. Обход hooks (НЕ РЕКОМЕНДУЕТСЯ): git commit --no-verify"
echo ""
echo -e "${YELLOW}Проверка:${NC}"
echo "  pre-commit run --all-files  # Проверить все файлы"
echo "  pre-commit run <hook-id>    # Запустить конкретный hook"
echo ""
echo -e "${CYAN}==============================================================================${NC}"
