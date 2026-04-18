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

## Эксперимент 2: Исправление rate limit + локальный тест
- **Дата:** 2026-04-18T15:22:00Z
- **Git tag:** `v2-fix-ratelimit`
- **Изменения:** RERANK_LIMIT снижен 50→15, retry с backoff при 429

### Локальные результаты (11 чатов, 1495 сообщений):

| Метрика | Baseline (v0) | Наше (v2) | Δ |
|---|---|---|---|
| **Score** | **0.4072** | **0.4448** | **+9.2%** |
| Recall@50 | 0.2601 | 0.3197 | +22.9% |
| nDCG@50 | 0.9956 | 0.9451 | -5.1% |
| Чанков | 283 | 543 | +91.9% |
| Avg chunk len | 694 | 365 | -47.4% |
| Avg query time | 1.00s | 1.10s | +10% |

### Покомпонентный анализ:
| Запрос | Baseline R@50 | v2 R@50 | Δ |
|---|---|---|---|
| gRPC streaming Go | 0.11 | 0.13 | +18% |
| Миграция PostgreSQL | 0.13 | 0.24 | +85% |
| Kubernetes HPA | 0.12 | 0.21 | +75% |
| React Server Components | 0.60 | 0.73 | +22% |
| ML классификация | 0.55 | 0.40 | -27% |
| Вакансия Go Developer | 0.12 | 0.16 | +33% |
| Нагрузочное тестирование | 0.20 | 0.31 | +55% |
| Docker image оптимизация | 0.25 | 0.38 | +52% |

### Выводы:
- **Recall вырос** на 23% благодаря меньшим чанкам (256 vs 512) и большим retrieval limits
- **nDCG немного упал** (-5%) — больше кандидатов = менее точное ранжирование
- **Score вырос** на 9.2% — recall (вес 80%) перевешивает
- Есть просадка на ML запросе — нужно исследовать

---

## 🏆 VK результат: v3-fix (реальные данные)
- **Дата:** 2026-04-18T13:20:19Z
- **Git tag:** `v3-fix-429`
- **Образ:** search `sha256:07e2b0106b61`, index `sha256:35e655aff2fa`

| Метрика | Значение |
|---|---|
| **Score** | **0.5339** |
| **Recall Average** | **0.5535** |
| **NDCG Average** | **0.4556** |

> **Важно:** Реранкер работал (graceful fallback не понадобился), RERANK_LIMIT=15

---

## Эксперимент 3: v4 — увеличенные лимиты + enrichment
- **Дата:** 2026-04-18T16:35:00Z
- **Git tag:** `v4-limits`
- **Изменения:**
  - DENSE_PREFETCH: 50→80, SPARSE_PREFETCH: 150→200
  - RETRIEVE_K: 100→150, RERANK_LIMIT: 15→10
  - Sender name + file_snippets в render_message
  - Graceful 429 fallback (5 retry → возврат без реранкинга)
  - Parallel embedding, HyDE multi-vector, keyword enrichment

### Сводная таблица (все версии):

| Метрика | Baseline | v2 | v4 | Δ v4 vs base |
|---|---|---|---|---|
| **Score** | **0.4072** | **0.4448** | **0.4539** | **+11.5%** |
| Recall@50 | 0.2601 | 0.3197 | 0.3340 | +28.4% |
| nDCG@50 | 0.9956 | 0.9451 | 0.9336 | -6.2% |
| Чанков | 283 | 543 | 621 | +119% |
| Avg query time | 1.00s | 1.10s | 0.25s | -75% |

### Покомпонентный анализ v4:
| Запрос | Baseline | v2 | v4 | Тренд |
|---|---|---|---|---|
| gRPC streaming Go | 0.11 | 0.13 | 0.17 | 📈 |
| Миграция PostgreSQL | 0.13 | 0.24 | 0.24 | ➡️ |
| Kubernetes HPA | 0.12 | 0.21 | 0.20 | ➡️ |
| React Server Components | 0.60 | 0.73 | 0.71 | ➡️ |
| ML классификация | 0.55 | 0.40 | 0.47 | 📈 vs v2 |
| Вакансия Go Developer | 0.12 | 0.16 | 0.18 | 📈 |
| Нагрузочное тестирование | 0.20 | 0.31 | 0.31 | ➡️ |
| Docker image оптимизация | 0.25 | 0.38 | 0.39 | 📈 |

### Выводы v4:
- **Score +11.5% vs baseline** — лучший результат
- **Скорость поиска 4x** быстрее (0.25s vs 1.0s) — parallel embedding
- ML запрос восстановился (0.40→0.47) — но ещё ниже baseline (0.55)
- gRPC запрос улучшился (0.11→0.17) — sender name помогает

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
