# 📊 Журнал экспериментов — Команда Lotus (team_id: 35250)

## Формула оценки
```
score = recall_avg × 0.8 + ndcg_avg × 0.2    (K = 50)
```

---

## Эксперимент 0: Чистый baseline от VK
- **Дата:** не отправлялся
- **Git tag:** `v0-baseline`
- **Описание:** Оригинальное решение из репозитория VK без изменений
- **Параметры:**
  - index: CHUNK_SIZE=512, OVERLAP_SIZE=256, без фильтрации
  - search: DENSE_PREFETCH_K=10, SPARSE_PREFETCH_K=30, RETRIEVE_K=20, RERANK_LIMIT=10
- **Результат:** Не тестировался на сервере VK

---

## Эксперимент 1: Quick Wins v1
- **Дата:** 2026-04-18T10:28:44Z
- **Git tag:** `v1-quickwins`
- **Статус:** ❌ **error** — 429 Too Many Requests на реранкере
- **Ошибка:** `Client error '429 Too Many Requests' for url '.../Inference/score'`

### Что изменили:
**search/main.py:**
| Параметр | Было | Стало |
|---|---|---|
| DENSE_PREFETCH_K | 10 | 50 |
| SPARSE_PREFETCH_K | 30 | 150 |
| RETRIEVE_K | 20 | 100 |
| RERANK_LIMIT | 10 | **50 ← причина ошибки!** |

Также: дедупликация message_ids, ограничение до 50

**index/main.py:**
| Параметр | Было | Стало |
|---|---|---|
| CHUNK_SIZE | 512 | 256 |
| OVERLAP_SIZE | 256 | 128 |
| Фильтрация is_system | нет | да |
| dense_content | = page_content | [chat.name] + chunk |
| sparse_content | = page_content | только chunk_body |
| render_message | все parts одинаково | [Пересланное]/[Цитата] |

### Анализ ошибки:
RERANK_LIMIT=50 отправляет 50 текстов чанков на реранкер за один запрос.
API организаторов имеет rate limit — слишком много символов за раз = 429.

### Исправление:
- Уменьшить RERANK_LIMIT до 15-20
- Добавить retry с backoff на случай 429

---

## Эксперимент 2: Исправление rate limit
- **Дата:** TBD
- **Git tag:** `v2-fix-ratelimit`
- **Изменения:** RERANK_LIMIT снижен, добавлен retry
- **Результат:** TBD

---

# 🔧 Процесс отправки решения на сервер VK

### 1. Сборка Docker-образов
```bash
sg docker -c "docker build --platform linux/amd64 \
  -t 83.166.249.64:5000/35250/index-service:latest ./index"

sg docker -c "docker build --platform linux/amd64 \
  -t 83.166.249.64:5000/35250/search-service:latest ./search"
```

### 2. Авторизация в реестре VK
```bash
sg docker -c "docker login 83.166.249.64:5000 \
  -u e6cc1293dd184149 -p f22df6739ce0b034c63ee982b9539534"
```

### 3. Отправка образов
```bash
sg docker -c "docker push 83.166.249.64:5000/35250/index-service:latest"
sg docker -c "docker push 83.166.249.64:5000/35250/search-service:latest"
```

### 4. Запуск проверки
На странице https://... → кнопка **«Новая проверка»**

### Важно:
- Реестр VK работает через HTTP (insecure), поэтому нужен `/etc/docker/daemon.json`:
  ```json
  {"insecure-registries": ["83.166.249.64:5000"]}
  ```
- После изменения `daemon.json` → `sudo systemctl restart docker`
- `sg docker -c "..."` — нужен для активации группы docker в текущей сессии
