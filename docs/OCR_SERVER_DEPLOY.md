# Применение proxy/CA-схемы на OCR-сервере

Чеклист для сервера, где крутится Remote OCR (`docker compose`: `web` + `worker` + `redis`).
Цель: трафик к Supabase/OpenRouter/LM Studio идёт через `pro3.fvds.ru`, TLS проверяется
по CA прокси, прямого ngrok-URL нет.

## 0. Предпосылки

- Прокси `pro3.fvds.ru` уже настроен (порты 8443/8444, см. `OCR_PROXY_SETUP.md`).
- На сервере установлены `docker` и `docker compose`.
- Есть доступ к репозиторию проекта на сервере (там лежит `docker-compose.yml`).

## 1. Положить CA прокси

```bash
cd /path/to/RD                      # каталог с docker-compose.yml
mkdir -p certs
scp root@pro3.fvds.ru:/etc/nginx/certs/proxy-ca.pem ./certs/proxy-ca.pem
ls -l certs/proxy-ca.pem            # файл должен существовать
```

> Приватные ключи (`proxy.key`, `proxy-ca.key`) на OCR-сервер копировать НЕ нужно —
> только публичный `proxy-ca.pem`.

## 2. Проверить `.env` сервера

В `.env` рядом с `docker-compose.yml` должно быть:

```bash
SUPABASE_URL=https://pro3.fvds.ru:8443/supabase-ziv
OPENROUTER_BASE_URL=https://pro3.fvds.ru:8443
CHANDRA_BASE_URL=https://pro3.fvds.ru:8444
OCR_CA_CERT=/certs/proxy-ca.pem
# ключи без изменений:
SUPABASE_KEY=...
OPENROUTER_API_KEY=...
NGROK_AUTH_USER=...
NGROK_AUTH_PASS=...
```

Не должно остаться:
- прямого `*.ngrok-free.dev` в `CHANDRA_BASE_URL`;
- `OCR_VERIFY_SSL=false` (только для временной диагностики);
- `NGROK_PROXY_URL` / `OCR_PROXY_URL` (нужны только для forward-proxy).

## 3. Убедиться, что CA смонтирован в контейнеры

В `docker-compose.yml` у `web` и `worker` уже есть:

```yaml
    environment:
      - OCR_CA_CERT=/certs/proxy-ca.pem
    volumes:
      - ./certs/proxy-ca.pem:/certs/proxy-ca.pem:ro
```

## 4. Пересобрать и поднять

```bash
git pull                              # подтянуть изменения кода (TLS/proxy)
docker compose down
docker compose up --build -d
docker compose logs -f --tail=100
```

В логах старта `web` должно быть:
- `"Server starting with configuration"` со значением `supabase_url` = адрес прокси;
- `"Supabase: подключение установлено"` (без TLS-ошибок).

## 5. Smoke-тесты из контейнера

```bash
# health приложения
curl -s http://localhost:8000/health/ready
# {"ready": true, "checks": {"redis": true, "supabase": true, ...}}

# Supabase через прокси
docker compose exec worker curl --cacert /certs/proxy-ca.pem -sI \
  "https://pro3.fvds.ru:8443/supabase-ziv/rest/v1/" -H "apikey: $SUPABASE_KEY"

# OpenRouter через прокси
docker compose exec worker curl --cacert /certs/proxy-ca.pem -sI \
  "https://pro3.fvds.ru:8443/api/v1/models" -H "Authorization: Bearer $OPENROUTER_API_KEY"

# LM Studio / Chandra через прокси (порт 8444)
docker compose exec worker curl --cacert /certs/proxy-ca.pem -sI \
  "https://pro3.fvds.ru:8444/v1/models" \
  -u "$NGROK_AUTH_USER:$NGROK_AUTH_PASS" -H "ngrok-skip-browser-warning: true"
```

Все должны вернуть `200` (или `404/409` на невалидных данных), но не `5xx`/TLS-ошибку.

## 6. Проверить реальную задачу

Запустить OCR небольшого PDF из клиента и в логах воркера убедиться, что нет:
- `CERTIFICATE_VERIFY_FAILED` (TLS до прокси);
- `Max retries ... ngrok-free.dev` (прямой ngrok);
- `Read timed out` к LM Studio дольше обычного.

## Troubleshooting

| Симптом | Действие |
|---------|----------|
| `CERTIFICATE_VERIFY_FAILED` | проверить, что `certs/proxy-ca.pem` смонтирован и `OCR_CA_CERT` задан |
| `supabase: false` в `/health/ready` | проверить `SUPABASE_URL` (путь `/supabase-ziv`) и доступность 8443 |
| `chandra reachable: false` | проверить 8444, Basic Auth, что LM Studio/ngrok живы |
| контейнер видит старый `.env` | `docker compose down && up --build -d` (без down env кэшируется) |

## Связанные документы

- [OCR_PROXY_SETUP.md](OCR_PROXY_SETUP.md) — настройка самого nginx-прокси и CA.
- [REMOTE_OCR_SERVER.md](REMOTE_OCR_SERVER.md) — API и конфигурация сервера.
