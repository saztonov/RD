# Reverse proxy для OpenRouter и ngrok (LM Studio)

Инструкция по настройке nginx reverse proxy на `pro3.fvds.ru`, чтобы весь OCR-трафик
(OpenRouter и Chandra/LM Studio через ngrok) шёл через ваш сервер с собственным
самоподписанным сертификатом, а клиент/воркер доверяли ему через CA.

## Архитектура

| Сервис | Клиентский env | Эндпоинт прокси | Upstream |
|--------|----------------|-----------------|----------|
| Supabase (REST/RPC) | `SUPABASE_URL` | `https://pro3.fvds.ru:8443/supabase-ziv` | `*.supabase.co:443` |
| OpenRouter (IMAGE) | `OPENROUTER_BASE_URL` | `https://pro3.fvds.ru:8443` | `openrouter.ai:443` |
| Chandra/LM Studio (TEXT) | `CHANDRA_BASE_URL` | `https://pro3.fvds.ru:8444` | `<ngrok-host>:443` |

> - Supabase и OpenRouter делят порт `8443`, разделяются по **пути** (`/supabase-ziv/...`
>   против `/api/v1/...`).
> - LM Studio вынесен на порт `8444`: у OpenRouter и LM Studio пересекается
>   `/api/v1/models`, по location их не развести.

### TLS и собственный CA

`OCR_CA_CERT` указывает на CA прокси. В коде он **объединяется с системным бандлом
certifi**, поэтому одновременно работают:
- прокси с самоподписанным CA (Supabase, OpenRouter, LM Studio);
- прямые соединения к публичным хостам (Datalab `datalab.to`, Cloudflare R2).

`SUPABASE_CA_CERT`/`SUPABASE_VERIFY_SSL` — опциональны: при отсутствии Supabase
использует общий `OCR_CA_CERT`/`OCR_VERIFY_SSL`.

---

## Шаг 0. Что проверить, если прокси уже частично настроен

```bash
# Порты слушаются?
sudo ss -tlnp | grep -E ':8443|:8444'

# nginx жив и конфиг валиден?
sudo nginx -t && sudo systemctl status nginx

# Реальные upstream-хосты доступны с прокси-сервера?
curl -sI https://openrouter.ai/api/v1/models | head -1
curl -sI https://<ngrok-host>/v1/models -H "ngrok-skip-browser-warning: true" | head -1
```

Если порт `8444` не слушается или нет server-блока для ngrok — выполните шаги ниже.

---

## Шаг 1. Сгенерировать CA и серверный сертификат

На прокси-сервере:

```bash
sudo mkdir -p /etc/nginx/certs && cd /etc/nginx/certs

# 1. Корневой CA (срок 10 лет)
# ВАЖНО: CA обязан содержать basicConstraints=CA:TRUE и keyUsage=keyCertSign,
# иначе OpenSSL/Python отвергнет его ("CA cert does not include key usage extension").
openssl genrsa -out proxy-ca.key 4096
openssl req -x509 -new -nodes -key proxy-ca.key -sha256 -days 3650 \
  -subj "/CN=RD OCR Proxy CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -out proxy-ca.pem

# 2. Ключ + CSR серверного сертификата
openssl genrsa -out proxy.key 2048
openssl req -new -key proxy.key -subj "/CN=pro3.fvds.ru" -out proxy.csr

# 3. SAN (обязательно, иначе современные клиенты не примут)
cat > proxy.ext <<'EOF'
subjectAltName = DNS:pro3.fvds.ru
extendedKeyUsage = serverAuth
EOF

# 4. Подписать серверный сертификат своим CA (срок 825 дней — лимит браузеров)
openssl x509 -req -in proxy.csr -CA proxy-ca.pem -CAkey proxy-ca.key \
  -CAcreateserial -days 825 -sha256 -extfile proxy.ext -out proxy.crt

# 5. fullchain = серверный сертификат + CA
cat proxy.crt proxy-ca.pem > proxy-fullchain.pem

chmod 600 proxy.key proxy-ca.key
```

Файл, который раздаём клиентам, — **только** `proxy-ca.pem` (приватные ключи не покидают сервер).

---

## Шаг 2. nginx: два server-блока

```bash
sudo nano /etc/nginx/sites-available/ocr-proxy
```

```nginx
# ── OpenRouter ──────────────────────────────────────────────
upstream openrouter_upstream {
    server openrouter.ai:443;
    keepalive 16;
}

server {
    listen 8443 ssl http2;
    listen [::]:8443 ssl http2;
    server_name pro3.fvds.ru;

    ssl_certificate     /etc/nginx/certs/proxy-fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/proxy.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    client_max_body_size 100m;
    proxy_read_timeout   300s;
    proxy_send_timeout   300s;
    proxy_buffering      off;

    location / {
        proxy_pass            https://openrouter_upstream;
        proxy_http_version    1.1;
        proxy_ssl_server_name on;
        proxy_ssl_name        openrouter.ai;
        proxy_set_header Host openrouter.ai;
        # Authorization: Bearer ... пробрасывается nginx по умолчанию
    }
}

# ── ngrok / LM Studio (Chandra) ─────────────────────────────
upstream ngrok_upstream {
    server <ngrok-host>:443;        # напр. louvred-madie-gigglier.ngrok-free.dev
    keepalive 8;
}

server {
    listen 8444 ssl http2;
    listen [::]:8444 ssl http2;
    server_name pro3.fvds.ru;

    ssl_certificate     /etc/nginx/certs/proxy-fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/proxy.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    client_max_body_size 100m;
    # OCR одного блока может идти минутами — таймауты с запасом
    proxy_read_timeout   600s;
    proxy_send_timeout   600s;
    proxy_buffering      off;

    location / {
        proxy_pass            https://ngrok_upstream;
        proxy_http_version    1.1;
        proxy_ssl_server_name on;
        proxy_ssl_name        <ngrok-host>;
        proxy_set_header Host <ngrok-host>;
        proxy_set_header ngrok-skip-browser-warning true;
        # Basic Auth (NGROK_AUTH_USER/PASS) пробрасывается клиентом как есть
    }
}
```

Активировать:

```bash
sudo ln -s /etc/nginx/sites-available/ocr-proxy /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# firewall
sudo ufw allow 8443/tcp
sudo ufw allow 8444/tcp
```

---

## Шаг 3. Smoke-тест (с любой машины)

```bash
# OpenRouter через прокси
curl --cacert proxy-ca.pem "https://pro3.fvds.ru:8443/api/v1/models" \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" | head -c 200

# ngrok/LM Studio через прокси
curl --cacert proxy-ca.pem "https://pro3.fvds.ru:8444/v1/models" \
  -u "$NGROK_AUTH_USER:$NGROK_AUTH_PASS" \
  -H "ngrok-skip-browser-warning: true" | head -c 200

# Supabase через прокси (путь-префикс /supabase-ziv)
curl --cacert proxy-ca.pem "https://pro3.fvds.ru:8443/supabase-ziv/rest/v1/" \
  -H "apikey: $SUPABASE_KEY" | head -c 200
```

Из контейнера CA уже лежит в `/certs/proxy-ca.pem`:

```bash
docker compose exec worker curl --cacert /certs/proxy-ca.pem -sI \
  https://pro3.fvds.ru:8444/v1/models -u "$NGROK_AUTH_USER:$NGROK_AUTH_PASS" \
  -H "ngrok-skip-browser-warning: true"
```

Оба должны вернуть `200` и JSON. Если `SSL certificate problem` — неверный `--cacert`
или SAN. Если `502/504` — недоступен upstream или мал таймаут.

---

## Шаг 4. Подключить клиент и сервер

### `.env`

```diff
- SUPABASE_URL=https://zivbesacbxfmwzervmcy.supabase.co
+ SUPABASE_URL=https://pro3.fvds.ru:8443/supabase-ziv
  OPENROUTER_BASE_URL=https://pro3.fvds.ru:8443
- CHANDRA_BASE_URL=https://louvred-madie-gigglier.ngrok-free.dev
+ CHANDRA_BASE_URL=https://pro3.fvds.ru:8444
- OCR_VERIFY_SSL=false
+ OCR_CA_CERT=/certs/proxy-ca.pem
```

- `OCR_CA_CERT` (предпочтительно) — путь к `proxy-ca.pem`, проверка TLS включена.
- `OCR_VERIFY_SSL=false` — только как временный обход (TLS не проверяется).
- `NGROK_PROXY_URL` больше **не нужен** (это для forward-прокси, см. Вариант B).
- На **десктопе** путь `/certs/proxy-ca.pem` нужно заменить на локальный абсолютный
  (напр. `C:\certs\proxy-ca.pem`), т.к. `.env` встраивается в `.exe`.

### Доставка CA в Docker-контейнер

Скопируйте `proxy-ca.pem` рядом с `docker-compose.yml` (например `./certs/proxy-ca.pem`)
и смонтируйте в `web` и `worker`:

```yaml
    volumes:
      - ocr_data:/data
      - ./certs/proxy-ca.pem:/certs/proxy-ca.pem:ro
```

Пересборка:

```bash
docker compose down && docker compose up --build -d
```

### Десктоп-клиент

Положите `proxy-ca.pem` на машину и укажите абсолютный путь в `OCR_CA_CERT`.
Для собранного `.exe` пересоберите: `python build.py` (`.env` встраивается в бинарник).

---

## Вариант B (альтернатива): forward-прокси (squid)

Если вместо reverse-proxy используется forward-прокси (HTTP CONNECT), код уже это
поддерживает через env (без правок nginx upstream):

```bash
NGROK_PROXY_URL=http://proxy-host:3128   # forward-прокси для запросов к ngrok
OCR_PROXY_URL=http://proxy-host:3128     # общий forward-прокси для всех OCR-запросов
```

`CHANDRA_BASE_URL`/`OPENROUTER_BASE_URL` при этом остаются оригинальными
(`ngrok-free.dev` / `openrouter.ai`). CA для squid с ssl-bump генерируется аналогично
Шагу 1 и кладётся в `OCR_CA_CERT`.

---

## Troubleshooting

| Симптом | Причина / решение |
|---------|-------------------|
| `CERTIFICATE_VERIFY_FAILED self-signed` | `OCR_CA_CERT` не задан/неверный путь, либо CA не смонтирован в контейнер |
| `502 Bad Gateway` | upstream-хост недоступен с прокси, либо неверный `proxy_ssl_name`/`Host` |
| `504 Gateway Timeout` | поднять `proxy_read_timeout`/`proxy_send_timeout` (LM Studio отвечает долго) |
| ngrok `401/403` | не дошёл Basic Auth или заголовок `ngrok-skip-browser-warning` |
| OpenRouter `/api/v1/models` ↔ LM Studio конфликт | использовать **разные порты** (8443/8444), не один |

---

## Связанные документы

- [SUPABASE_PROXY_SETUP.md](SUPABASE_PROXY_SETUP.md) — reverse proxy для Supabase.
- [ARCHITECTURE.md](ARCHITECTURE.md) — список env-переменных.
