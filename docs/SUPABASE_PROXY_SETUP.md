# Reverse proxy для Supabase

Инструкция по настройке собственного nginx reverse proxy перед Supabase, чтобы
весь трафик десктопного клиента и Remote OCR сервера шёл через ваш домен,
а не напрямую на `*.supabase.co`.

## Зачем это нужно

- **Скрытие реального адреса** проекта Supabase от клиентских машин.
- **Обход блокировок** Supabase в корпоративных и региональных сетях.
- **Централизованное логирование** и rate-limiting всех обращений к БД.
- **Упрощение миграции** между проектами Supabase — меняется только
  upstream в одном конфиге, клиенты не пересобираются.

## Что проксируется и что нет

| Сервис | Через прокси | Причина |
|--------|--------------|---------|
| Supabase REST (`/rest/v1/...`) | **Да** | Tree, jobs, annotations |
| Supabase RPC (`/rest/v1/rpc/...`) | **Да** | `update_pdf_status` |
| Supabase Auth (`/auth/v1/...`) | **Да** | Если будет добавлен в будущем |
| Cloudflare R2 | **Нет** | Отдельный S3-совместимый сервис |
| Remote OCR API (`REMOTE_OCR_BASE_URL`) | **Нет** | Свой публичный API |
| Supabase Realtime (WebSocket) | **Нет** | В проекте не используется |
| Supabase Storage | **Нет** | В проекте не используется (всё в R2) |

Поэтому конфиг ниже проксирует только HTTPS-запросы, без специальных правил
для WebSocket.

---

## Предварительные требования

- Сервер с Linux (примеры даны для Ubuntu 22.04 / 24.04).
- Открытые наружу порты `80/tcp` (для ACME-челленджа Let's Encrypt) и
  `443/tcp` (для HTTPS-трафика).
- Доменное имя, направленное A-записью на IP сервера. Например —
  `sb.example.com`.
- Реальный хост проекта Supabase. Возьмите его из Dashboard:
  Project Settings → API → Project URL. Выглядит как
  `https://abcd1234.supabase.co` (далее — `<SUPABASE_HOST>`).
- root или sudo на сервере.

---

## Шаг 1. Установка nginx и certbot

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

Проверка:

```bash
nginx -v
sudo systemctl status nginx
```

## Шаг 2. Открытие портов в firewall

Если используется UFW:

```bash
sudo ufw allow 'Nginx Full'
sudo ufw reload
```

Если используется облачный провайдер (AWS/Hetzner/DO) — открыть `80` и `443`
в Security Group / Cloud Firewall.

## Шаг 3. Базовый HTTP-конфиг для получения сертификата

Создаём временный конфиг **без TLS**, чтобы certbot смог пройти HTTP-челлендж.

```bash
sudo nano /etc/nginx/sites-available/supabase-proxy
```

Содержимое:

```nginx
server {
    listen 80;
    server_name sb.example.com;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 200 "ok";
        add_header Content-Type text/plain;
    }
}
```

Активируем:

```bash
sudo ln -s /etc/nginx/sites-available/supabase-proxy /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Проверка с другой машины:

```bash
curl http://sb.example.com/
# ok
```

## Шаг 4. Получение TLS-сертификата Let's Encrypt

```bash
sudo certbot --nginx -d sb.example.com --agree-tos -m admin@example.com --redirect
```

После выполнения certbot:

- сгенерирует сертификат в `/etc/letsencrypt/live/sb.example.com/`,
- автоматически добавит `listen 443 ssl` и редирект 80→443 в наш конфиг.

Проверка автообновления (cron уже создан certbot-ом):

```bash
sudo certbot renew --dry-run
```

## Шаг 5. Финальный конфиг прокси

Откройте `/etc/nginx/sites-available/supabase-proxy` и замените содержимое на
рабочий конфиг ниже. Замените `sb.example.com` на свой домен и
`abcd1234.supabase.co` на свой `<SUPABASE_HOST>`.

```nginx
upstream supabase_upstream {
    server abcd1234.supabase.co:443;
    keepalive 16;
}

# HTTP -> HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name sb.example.com;
    return 301 https://$host$request_uri;
}

# HTTPS reverse proxy
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name sb.example.com;

    ssl_certificate     /etc/letsencrypt/live/sb.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sb.example.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;

    # PostgREST может возвращать большие JSON (OCR-результаты до 30 МБ)
    client_max_body_size 100m;

    # Длинные batch-запросы к /rest/v1/* и долгие RPC-вызовы
    proxy_read_timeout    300s;
    proxy_send_timeout    300s;
    proxy_connect_timeout 30s;

    # Не буферизуем — ответы могут быть стримом
    proxy_buffering         off;
    proxy_request_buffering off;

    # Стандартные заголовки apikey / Authorization / Prefer / Content-Type /
    # Range / Range-Unit передаются nginx-ом по умолчанию. Не фильтруем.

    location / {
        proxy_pass https://supabase_upstream;
        proxy_http_version 1.1;

        # SNI к Supabase (он сидит за CDN, без SNI вернёт 526/cert error)
        proxy_ssl_server_name on;
        proxy_ssl_name        abcd1234.supabase.co;

        # Host upstream-а должен быть оригинальный *.supabase.co,
        # иначе CDN ответит 503/526
        proxy_set_header Host              abcd1234.supabase.co;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Применяем:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## Шаг 6. Smoke-тест прокси

С любой машины (не с самого прокси-сервера):

```bash
# 1. PostgREST root — должен вернуть JSON-описание API
curl -i "https://sb.example.com/rest/v1/" \
  -H "apikey: $SUPABASE_KEY"

# 2. Чтение таблицы tree_nodes
curl -i "https://sb.example.com/rest/v1/tree_nodes?limit=1" \
  -H "apikey: $SUPABASE_KEY" \
  -H "Authorization: Bearer $SUPABASE_KEY"

# 3. RPC-вызов update_pdf_status (с реальным node_id)
curl -i -X POST "https://sb.example.com/rest/v1/rpc/update_pdf_status" \
  -H "apikey: $SUPABASE_KEY" \
  -H "Authorization: Bearer $SUPABASE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"p_node_id":"00000000-0000-0000-0000-000000000000","p_status":"queued"}'
```

Все три должны вернуть `200 OK` (или `404`/`409` при невалидных данных,
но не `502`/`503`/`526`).

---

## Шаг 7. Подключение клиента и сервера

### `.env` (корень проекта)

```diff
- SUPABASE_URL=https://abcd1234.supabase.co
+ SUPABASE_URL=https://sb.example.com
  SUPABASE_KEY=eyJhbGciOi...   # не меняется
```

`SUPABASE_KEY` — тот же anon-ключ. Прокси передаёт его как `apikey`-заголовок,
Supabase валидирует JWT по своей подписи, прокси в этом не участвует.

### Сервер Remote OCR

```bash
docker compose down
docker compose up --build -d
docker compose logs web | head -20
```

В логах при старте будет строка `"Server starting with configuration"` со
значением `supabase_url`. Убедитесь, что там адрес прокси.

Проверка readiness:

```bash
curl http://localhost:8000/health/ready
# {"ready": true, "checks": {"redis": true, "supabase": true, ...}}
```

### Десктопный клиент

Если запускаете из исходников:

```bash
python app/main.py
```

В лог-файле должно появиться сообщение `"Supabase URL configured: ..."` с
адресом прокси.

Если используете собранный `.exe`, пересоберите его:

```bash
python build.py
```

`build.py` встраивает текущий `.env` в `dist/CoreStructure.exe`
(см. [build.py](../build.py): `datas=[('.env', '.')]`). Без пересборки старый
`.exe` будет ходить на прежний URL.

---

## Troubleshooting

### `502 Bad Gateway` или `526 Invalid SSL Certificate`

Не передан правильный `Host` или SNI. Проверьте, что в конфиге:

- `proxy_set_header Host abcd1234.supabase.co;` (с реальным хостом, не с
  вашим доменом).
- `proxy_ssl_server_name on;`
- `proxy_ssl_name abcd1234.supabase.co;`

### `503 Service Unavailable` со страницей Cloudflare

Скорее всего, в `proxy_set_header Host` указан `$host` или ваш домен. Должен
стоять оригинальный `*.supabase.co`.

### `401 Unauthorized` на всех запросах

Заголовок `apikey` или `Authorization` не доходит до Supabase. Проверьте, что
в конфиге **нет** строк вида `proxy_set_header apikey ""` или
`proxy_hide_header`. nginx по умолчанию пробрасывает все клиентские
заголовки — дополнительно их прописывать не нужно.

### `413 Request Entity Too Large`

Поднимите `client_max_body_size` (по умолчанию в конфиге 100m). Большие
OCR-результаты при upsert в `/rest/v1/annotations` могут достигать десятков
мегабайт.

### `504 Gateway Timeout` на RPC или batch-запросах

Поднимите `proxy_read_timeout` и `proxy_send_timeout`. По умолчанию nginx —
60 секунд, чего может не хватить для больших batch-апдейтов в Supabase.

### Клиент ходит на старый URL

- Десктоп: проверьте, что `.env` рядом с `.exe` обновлён И что `.exe` был
  пересобран (`.env` встроен в бинарник через PyInstaller).
- Сервер: `docker compose down && docker compose up --build -d` — без
  пересборки контейнеры могут держать старые env-переменные.

### Проверка, что трафик действительно идёт через прокси

На прокси-сервере:

```bash
sudo tail -f /var/log/nginx/access.log
```

При работе клиента/сервера должны быть видны строки вида:

```
1.2.3.4 - - [29/Apr/2026:12:34:56 +0000] "GET /rest/v1/tree_nodes?... HTTP/1.1" 200 ...
```

---

## Безопасность

- Прокси **не** добавляет авторизации поверх Supabase — кто угодно с
  валидным `SUPABASE_KEY` может сделать запрос. Защита остаётся на уровне
  RLS и JWT.
- При желании можно ограничить доступ по IP клиентов через
  `allow ... ; deny all;` в блоке `location /`.
- Логи nginx содержат заголовки `apikey` **в URL не попадают**, но при
  расширенных лог-форматах с `$http_*` могут логироваться. Не включайте
  логирование заголовков `apikey` и `authorization`.
- Сертификат Let's Encrypt обновляется автоматически (systemd-таймер
  `certbot.timer`). Раз в квартал стоит руками выполнять `certbot renew
  --dry-run`, чтобы убедиться в работоспособности.

---

## Связанные документы

- [ARCHITECTURE.md](ARCHITECTURE.md) — общая архитектура и список env-переменных.
- [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) — быстрый старт.
- [REMOTE_OCR_SERVER.md](REMOTE_OCR_SERVER.md) — конфигурация сервера.
