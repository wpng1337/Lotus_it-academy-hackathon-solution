"""
Генератор тестовых данных для локального тестирования.
Создаёт разнообразные чаты с сообщениями на русском языке.
"""
import json
import random
import os
from datetime import datetime, timedelta

random.seed(42)

# === Темы и контент ===

CHAT_TEMPLATES = [
    {"name": "Backend Dev", "type": "group", "topic": "backend",
     "members_count": 150, "is_public": True},
    {"name": "Frontend Squad", "type": "group", "topic": "frontend",
     "members_count": 80, "is_public": True},
    {"name": "DevOps & Infra", "type": "channel", "topic": "devops",
     "members_count": 200, "is_public": True},
    {"name": "ML Research", "type": "group", "topic": "ml",
     "members_count": 45, "is_public": False},
    {"name": "Продуктовый чат", "type": "group", "topic": "product",
     "members_count": 30, "is_public": False},
    {"name": "HR Новости", "type": "channel", "topic": "hr",
     "members_count": 500, "is_public": True},
    {"name": "QA Testing", "type": "group", "topic": "qa",
     "members_count": 60, "is_public": True},
    {"name": "Mobile Dev", "type": "group", "topic": "mobile",
     "members_count": 40, "is_public": True},
    {"name": "Data Engineering", "type": "group", "topic": "data",
     "members_count": 35, "is_public": False},
    {"name": "Security Team", "type": "group", "topic": "security",
     "members_count": 25, "is_public": False},
]

SENDERS = [
    "a.ivanov@corp.example", "b.petrov@corp.example", "c.sidorov@corp.example",
    "d.kuznetsova@corp.example", "e.popov@corp.example", "f.sokolova@corp.example",
    "g.lebedev@corp.example", "h.kozlova@corp.example", "i.novikov@corp.example",
    "j.morozov@corp.example", "k.volkov@corp.example", "l.alekseeva@corp.example",
    "m.fedorov@corp.example", "n.mikhailova@corp.example", "o.nikolaev@corp.example",
]

MESSAGES_BY_TOPIC = {
    "backend": [
        "Коллеги, кто работал с gRPC streaming в Go? Нужно реализовать bidirectional stream для real-time нотификаций",
        "Мы перешли на Go 1.22 и заметили улучшение производительности GC на ~15%. Рекомендую обновиться",
        "Вопрос по архитектуре: стоит ли использовать CQRS для нашего сервиса заказов? Нагрузка ~10k rps",
        "Нашёл баг в обработке контекстов. При таймауте горутина не завершается корректно, утечка памяти",
        "Предлагаю перейти с REST на gRPC для межсервисного взаимодействия. Профит: типизация, скорость, streaming",
        "Миграция БД прошла успешно. PostgreSQL 16 показывает на 20% лучше на наших запросах",
        "Кто-нибудь использовал sqlc для генерации Go кода из SQL? Хочу попробовать вместо GORM",
        "Релиз v2.5 запланирован на пятницу. Прошу всех проверить свои MR до четверга",
        "Обнаружил проблему с пулом коннектов к Redis. При пиковой нагрузке получаем таймауты",
        "Написал библиотеку для graceful shutdown. Корректно завершает HTTP сервер, gRPC, воркеры и очереди",
        "Нужен code review для PR #1234 — рефакторинг middleware аутентификации",
        "Добавил кеширование в сервис профилей. Latency p99 упала с 200ms до 15ms",
        "Вопрос: как правильно обрабатывать partial failures в saga паттерне?",
        "Написал нагрузочный тест на k6. При 5000 rps сервис держит стабильно, CPU ~60%",
        "Предлагаю добавить distributed tracing через OpenTelemetry. Без него дебаг микросервисов — боль",
        "Обновил зависимости в go.mod. Protobuf обновился до v1.33, есть breaking changes",
        "Кто знает как настроить connection pooling для PostgreSQL в Kubernetes?",
        "Деплой нового сервиса прошёл без даунтайма. Canary на 5% трафика — всё стабильно",
        "Переписал обработку ошибок на новые errors в Go 1.22. Стало намного чище",
        "Нужна помощь с настройкой rate limiter. Как правильно реализовать sliding window?",
    ],
    "frontend": [
        "Перешли на React 19 — Server Components работают отлично. Bundle уменьшился на 30%",
        "Кто-нибудь работал с Tanstack Router? Хочу заменить React Router",
        "Дизайн-система обновлена. Новые компоненты: DatePicker, ComboBox, DataTable",
        "Обнаружил проблему с гидратацией в Next.js 15. При SSR получаем мисматч",
        "Написал кастомный хук useDebounce для поиска. Уменьшает количество запросов на 80%",
        "Предлагаю внедрить Storybook для документации компонентов",
        "Lighthouse score упал до 65. Нужно оптимизировать LCP и CLS",
        "TypeScript 5.5 вышел. Кто уже обновился? Есть проблемы с совместимостью?",
        "Реализовал виртуализированный список на 100k элементов. Скролл плавный",
        "Нужен фидбек по новому UI для дашборда аналитики. Скриншоты в тикете",
        "Миграция с Webpack на Vite завершена. Время сборки сократилось с 2 мин до 8 сек",
        "Как правильно организовать state management в большом приложении? Redux vs Zustand?",
        "Добавил поддержку темной темы. Используем CSS custom properties",
        "Проблема с CORS при запросах к API из dev-окружения. Кто знает как починить?",
        "Написал E2E тесты на Playwright. Покрытие основных сценариев — 85%",
    ],
    "devops": [
        "Kubernetes кластер обновлён до 1.30. Прошу проверить свои деплойменты",
        "Настроил автоскейлинг на основе custom metrics. HPA теперь реагирует на длину очереди",
        "CI/CD pipeline ускорен на 40% за счёт параллельных стейджей и кеширования Docker layers",
        "Внимание: плановое обслуживание prod кластера в субботу 03:00-05:00 MSK",
        "Мигрировали с Jenkins на GitHub Actions. Конфигурация стала в 3 раза проще",
        "Prometheus показывает рост latency на API Gateway. Проверяю, в чём дело",
        "Terraform state переехал в S3 backend с DynamoDB lock. Больше не будет конфликтов",
        "Grafana дашборд для нового сервиса готов: CPU, Memory, RPS, Error Rate, Latency percentiles",
        "Обнаружена уязвимость CVE-2024-XXXX в базовом образе. Нужно срочно обновить все сервисы",
        "Настроил centralized logging через ELK stack. Все логи доступны в Kibana",
        "ArgoCD синхронизация сломалась после обновления Helm чарта. Откатил",
        "Реализовал blue-green deployment для критичных сервисов",
        "Docker images оптимизированы. Средний размер уменьшился с 800MB до 150MB",
        "Vault интегрирован со всеми сервисами. Секреты больше не хранятся в env vars",
        "Мониторинг алертов настроен в PagerDuty. On-call расписание обновлено",
    ],
    "ml": [
        "Обучили новую модель для классификации тикетов. F1 score вырос с 0.82 до 0.91",
        "Нужна помощь с feature engineering для рекомендательной системы",
        "Эксперимент с LoRA fine-tuning на Llama 3 показал хорошие результаты для нашего домена",
        "GPU кластер обновлён. Теперь доступны A100 80GB. Время обучения сократилось в 3 раза",
        "Реализовал RAG pipeline для внутренней базы знаний. Качество ответов значительно улучшилось",
        "Вопрос: как правильно делать A/B тест для ML моделей в проде?",
        "MLflow эксперименты показывают что XGBoost всё ещё лучше нейросетей на табличных данных",
        "Датасет для обучения расширен до 500к примеров. Нужна помощь с разметкой",
        "Встроили модель в API. Latency inference — 50ms на CPU, 5ms на GPU",
        "Проблема с data drift в продакшене. Модель деградирует через 2 недели",
        "Написал пайплайн автоматического переобучения по расписанию через Airflow",
        "Hugging Face Transformers обновили до 4.40. Есть поддержка Flash Attention 2",
        "Нужен совет: ONNX Runtime vs TensorRT для инференса в продакшене?",
        "Векторная БД Qdrant показала себя лучше Pinecone по latency и стоимости",
        "Провели evaluation нашего чатбота. BLEU score 0.45, ROUGE-L 0.62",
    ],
    "product": [
        "Результаты A/B теста: новый онбординг увеличил конверсию на 12%",
        "Приоритеты на Q3: мобильное приложение, интеграция с CRM, аналитический дашборд",
        "Пользователи жалуются на сложность настройки уведомлений. Нужно упростить UI",
        "NPS вырос с 42 до 58 после релиза новых фич. Хорошая динамика",
        "Конкурент запустил аналогичную функцию. Нужно ускорить наш релиз",
        "Провели 15 custdev интервью. Главная боль — отсутствие интеграции с Jira",
        "Ретро спринта: закрыли 85% запланированных задач. Блокер — зависимость от API команды",
        "Дорожная карта на H2 утверждена. Фокус на enterprise клиентов",
        "Метрики DAU/MAU: 45k/120k. Retention 30d — 35%. Нужно улучшать",
        "Запускаем бета-тест новой фичи. Нужны 50 добровольцев из команды",
    ],
    "hr": [
        "Открыта вакансия Senior Go Developer. Зарплатная вилка 300-450к. Реферальный бонус 100к",
        "Напоминаю: дедлайн по заполнению OKR до пятницы",
        "Корпоратив в честь дня рождения компании — 25 мая в офисе на Арбате",
        "Запускаем программу менторства. Менторы и менти — регистрация до конца недели",
        "Новый ДМС провайдер с 1 июля. Стоматология включена",
        "Результаты опроса удовлетворённости: 4.2/5.0. Основная жалоба — шумный опенспейс",
        "Команде Backend нужен тимлид. Рассматриваем внутренних кандидатов",
        "Обучение по Kubernetes — запись на курс до конца месяца",
        "Поздравляем Алексея Иванова с 5-летним юбилеем в компании!",
        "Хакатон VK IT Academy — набираем участников. Призовой фонд 500к",
    ],
    "qa": [
        "Регрессионное тестирование v2.5 завершено. Найдено 3 критических бага",
        "Автотесты на API падают после изменения схемы ответа. Нужно обновить контракты",
        "Нагрузочное тестирование показало деградацию при >3000 rps. Bottleneck в БД",
        "Написал тест-план для нового модуля аналитики. 47 тест-кейсов",
        "Selenium тесты мигрированы на Playwright. Стабильность выросла с 70% до 95%",
        "Баг в корзине: при добавлении >99 товаров цена считается некорректно",
        "Тестовое окружение обновлено. Данные синхронизированы с продом (анонимизированы)",
        "Code coverage backend: 73%. Цель — 80% к концу квартала",
        "Интеграционные тесты с внешними API переведены на моки. Больше не зависим от доступности",
        "Найден security баг: XSS через поле комментариев. Приоритет — Critical",
    ],
    "mobile": [
        "iOS приложение прошло review в App Store. Релиз завтра",
        "Android: crash rate снизился с 2% до 0.3% после оптимизации памяти",
        "Новая версия Kotlin 2.0 — кто уже мигрировал? Какие впечатления?",
        "SwiftUI vs UIKit: для нового экрана рекомендую SwiftUI, меньше кода",
        "Push-уведомления не доходят на Xiaomi. Проблема с MIUI оптимизацией батареи",
        "Compose Multiplatform позволит шарить UI между Android и iOS. Стоит попробовать?",
        "Размер APK вырос до 80MB. Нужно оптимизировать ресурсы",
        "Deep linking настроен. Universal Links (iOS) и App Links (Android) работают",
        "Firebase Analytics интегрирован. Отслеживаем все ключевые события",
        "Тёмная тема для мобилки готова. Тестируйте на своих устройствах",
    ],
    "data": [
        "ETL pipeline на Spark обрабатывает 500GB данных за 2 часа. Нужно оптимизировать",
        "Миграция с Hadoop на Databricks завершена. Стоимость снизилась на 40%",
        "Новый источник данных подключён: CRM Salesforce. Синхронизация каждые 15 минут",
        "Data Quality проверки выявили 5% дубликатов в таблице заказов",
        "ClickHouse кластер масштабирован до 6 нод. Запросы по агрегатам ускорились в 10 раз",
        "dbt модели обновлены. Документация сгенерирована автоматически",
        "Airflow DAG для ежедневного отчёта падает. Причина — timeout на запрос к API",
        "Партиционирование таблицы events по дате дало прирост скорости запросов в 50 раз",
        "Data catalog готов. Все таблицы описаны с бизнес-контекстом",
        "Real-time стриминг через Kafka Connect подключён к 12 источникам",
    ],
    "security": [
        "Penetration test завершён. Найдено 2 High, 5 Medium уязвимостей. Отчёт в Jira",
        "Внедрили 2FA для всех сервисов. Обязательно до конца недели",
        "Обнаружена утечка API ключей в публичном репозитории. Ключи отозваны, ротация завершена",
        "WAF правила обновлены. Блокируем новые паттерны SQL injection",
        "SOC2 аудит запланирован на сентябрь. Нужно подготовить документацию",
        "Зависимость log4j обнаружена в 3 сервисах. Патч применён",
        "VPN конфигурация обновлена. Новый профиль в корпоративном портале",
        "Фишинговая атака на сотрудников. Напоминаю: не открывайте подозрительные ссылки",
        "SAST сканирование показало 12 потенциальных уязвимостей в новом коде",
        "Сертификаты TLS обновлены. Срок действия — до декабря 2025",
    ],
}

FORWARD_MESSAGES = [
    "Важное объявление от руководства: с нового года переходим на гибридный формат работы",
    "Инструкция по настройке VPN для удалённой работы",
    "Результаты квартального ревью. Бонусы выплачиваются в следующую зарплату",
    "Обновлённый регламент code review. Все MR должны иметь минимум 2 апрува",
    "Расписание митингов на следующую неделю",
]

QUOTE_REPLIES = [
    "Полностью согласен, давайте обсудим на стендапе",
    "Не уверен что это правильный подход. Предлагаю альтернативу",
    "Спасибо за информацию! Передам команде",
    "Уже начал работу над этим. Будет готово к завтрашнему дню",
    "Хороший поинт. Создал тикет в Jira",
    "Можно подробнее? Не совсем понял контекст",
    "Отличная идея! Давайте включим в бэклог",
    "У меня был похожий опыт, могу помочь",
]

SYSTEM_EVENTS = [
    {"type": "addMembers", "members": ["new.user@corp.example"]},
    {"type": "removeMember", "members": ["old.user@corp.example"]},
    {"type": "changeName", "members": []},
]


def generate_message(msg_id: int, timestamp: int, topic: str, senders: list[str]) -> dict:
    """Генерирует одно сообщение."""
    sender = random.choice(senders)
    
    # 5% системных
    if random.random() < 0.05:
        return {
            "id": str(msg_id),
            "thread_sn": None,
            "time": timestamp,
            "text": "",
            "sender_id": sender,
            "file_snippets": "",
            "parts": [],
            "mentions": [],
            "member_event": random.choice(SYSTEM_EVENTS),
            "is_system": True,
            "is_hidden": False,
            "is_forward": False,
            "is_quote": False,
        }
    
    messages = MESSAGES_BY_TOPIC.get(topic, MESSAGES_BY_TOPIC["backend"])
    
    # 10% forward
    if random.random() < 0.10:
        fwd_text = random.choice(FORWARD_MESSAGES)
        return {
            "id": str(msg_id),
            "thread_sn": None,
            "time": timestamp,
            "text": "",
            "sender_id": sender,
            "file_snippets": "",
            "parts": [{"mediaType": "forward", "sn": random.choice(senders), 
                       "time": timestamp - random.randint(3600, 86400), "text": fwd_text}],
            "mentions": [],
            "member_event": None,
            "is_system": False,
            "is_hidden": False,
            "is_forward": True,
            "is_quote": False,
        }
    
    # 15% quote (ответ на предыдущее)
    if random.random() < 0.15:
        quote_text = random.choice(messages)
        reply_text = random.choice(QUOTE_REPLIES)
        mentioned = random.choice(senders)
        return {
            "id": str(msg_id),
            "thread_sn": None,
            "time": timestamp,
            "text": "",
            "sender_id": sender,
            "file_snippets": "",
            "parts": [
                {"mediaType": "quote", "sn": mentioned, "text": quote_text},
                {"mediaType": "text", "text": reply_text}
            ],
            "mentions": [mentioned],
            "member_event": None,
            "is_system": False,
            "is_hidden": False,
            "is_forward": False,
            "is_quote": True,
        }
    
    # Обычное сообщение
    text = random.choice(messages)
    mentions = []
    if random.random() < 0.2:
        mentioned = random.choice(senders)
        mentions = [mentioned]
        text += f"\n@{mentioned.split('@')[0]}"
    
    return {
        "id": str(msg_id),
        "thread_sn": None,
        "time": timestamp,
        "text": text,
        "sender_id": sender,
        "file_snippets": "",
        "parts": [],
        "mentions": mentions,
        "member_event": None,
        "is_system": False,
        "is_hidden": random.random() < 0.02,  # 2% hidden
        "is_forward": False,
        "is_quote": False,
    }


def generate_chat(chat_template: dict, msg_count: int, start_id: int) -> dict:
    """Генерирует полный чат с сообщениями."""
    chat_id = f"{random.randint(10000, 99999)}@chat.example"
    chat = {
        "id": chat_id,
        "name": chat_template["name"],
        "sn": chat_id,
        "type": chat_template["type"],
        "is_public": chat_template["is_public"],
        "members_count": chat_template["members_count"],
        "members": None,
    }
    
    # Берём подмножество отправителей для этого чата
    num_senders = random.randint(5, len(SENDERS))
    chat_senders = random.sample(SENDERS, num_senders)
    
    # Генерируем сообщения с нарастающим временем
    start_time = int(datetime(2023, 1, 1).timestamp())
    messages = []
    current_time = start_time
    
    for i in range(msg_count):
        current_time += random.randint(60, 7200)  # 1 мин - 2 часа между сообщениями
        msg = generate_message(
            msg_id=start_id + i,
            timestamp=current_time,
            topic=chat_template["topic"],
            senders=chat_senders,
        )
        messages.append(msg)
    
    return {"chat": chat, "messages": messages}


def main():
    output_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Генерируем чаты разных размеров
    configs = [
        (CHAT_TEMPLATES[0], 200),   # Backend Dev — 200 сообщений
        (CHAT_TEMPLATES[1], 150),   # Frontend Squad — 150
        (CHAT_TEMPLATES[2], 300),   # DevOps & Infra — 300
        (CHAT_TEMPLATES[3], 100),   # ML Research — 100
        (CHAT_TEMPLATES[4], 80),    # Продуктовый чат — 80
        (CHAT_TEMPLATES[5], 250),   # HR Новости — 250
        (CHAT_TEMPLATES[6], 120),   # QA Testing — 120
        (CHAT_TEMPLATES[7], 90),    # Mobile Dev — 90
        (CHAT_TEMPLATES[8], 110),   # Data Engineering — 110
        (CHAT_TEMPLATES[9], 70),    # Security Team — 70
    ]
    
    msg_id_counter = 1000000000
    total_messages = 0
    
    for template, count in configs:
        chat_data = generate_chat(template, count, msg_id_counter)
        filename = f"{template['name']}.json"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(chat_data, f, ensure_ascii=False, indent=2)
        
        msg_id_counter += count + 1000
        total_messages += count
        
        sys_count = sum(1 for m in chat_data["messages"] if m["is_system"])
        fwd_count = sum(1 for m in chat_data["messages"] if m["is_forward"])
        quote_count = sum(1 for m in chat_data["messages"] if m["is_quote"])
        
        print(f"✅ {filename}: {count} сообщений "
              f"(sys:{sys_count}, fwd:{fwd_count}, quote:{quote_count})")
    
    print(f"\n📊 Итого: {len(configs)} чатов, {total_messages} сообщений")
    print(f"📁 Файлы в: {output_dir}")


if __name__ == "__main__":
    main()
