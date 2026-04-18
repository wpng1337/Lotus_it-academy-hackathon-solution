"""
Локальный тест: имитирует проверяющую систему VK.
1. POST /index → получаем чанки
2. POST /sparse_embedding → sparse векторы
3. GET dense embeddings → dense векторы
4. Вставляем в Qdrant
5. POST /search → получаем message_ids
6. Считаем recall@50, ndcg@50
"""
import json
import httpx
import time
import sys
import os
import math
from pathlib import Path

INDEX_URL = "http://localhost:8001"
SEARCH_URL = "http://localhost:8002"
QDRANT_URL = "http://localhost:6333"
DENSE_URL = os.getenv("EMBEDDINGS_DENSE_URL", "http://83.166.249.64:18001/embeddings")
DENSE_MODEL = "Qwen/Qwen3-Embedding-0.6B"
LOGIN = os.getenv("OPEN_API_LOGIN", "e6cc1293dd184149")
PASSWORD = os.getenv("OPEN_API_PASSWORD", "f22df6739ce0b034c63ee982b9539534")
COLLECTION = "evaluation"
BATCH_SIZE = 20  # сообщений на батч (имитация проверяющей системы)


def check_health():
    """Проверяем что все сервисы живы."""
    for name, url in [("index", INDEX_URL), ("search", SEARCH_URL)]:
        try:
            r = httpx.get(f"{url}/health", timeout=5)
            if r.status_code == 200:
                print(f"  ✅ {name}: OK")
            else:
                print(f"  ❌ {name}: {r.status_code}")
                return False
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            return False
    # Qdrant health
    try:
        r = httpx.get(f"{QDRANT_URL}/collections", timeout=5)
        if r.status_code == 200:
            print(f"  ✅ qdrant: OK")
        else:
            print(f"  ❌ qdrant: {r.status_code}")
            return False
    except Exception as e:
        print(f"  ❌ qdrant: {e}")
        return False
    return True


def reset_qdrant():
    """Пересоздаём коллекцию."""
    # Удаляем
    httpx.delete(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=10)
    # Создаём
    r = httpx.put(
        f"{QDRANT_URL}/collections/{COLLECTION}",
        json={
            "vectors": {
                "dense": {"size": 1024, "distance": "Cosine"}
            },
            "sparse_vectors": {
                "sparse": {"modifier": "idf"}
            }
        },
        timeout=10,
    )
    if r.status_code != 200:
        print(f"  ❌ Qdrant create collection: {r.text}")
        return False
    print(f"  ✅ Qdrant: коллекция {COLLECTION} пересоздана")
    return True


def load_chat(filepath: str) -> dict:
    """Загружаем чат."""
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def index_chat(chat_data: dict) -> list[dict]:
    """Отправляем чат на индексацию батчами, как это делает VK."""
    chat = chat_data["chat"]
    messages = chat_data["messages"]
    all_chunks = []
    
    for i in range(0, len(messages), BATCH_SIZE):
        overlap = messages[max(0, i-5):i]  # 5 overlap сообщений
        new = messages[i:i+BATCH_SIZE]
        
        payload = {
            "data": {
                "chat": chat,
                "overlap_messages": overlap,
                "new_messages": new,
            }
        }
        
        r = httpx.post(f"{INDEX_URL}/index", json=payload, timeout=30)
        if r.status_code != 200:
            print(f"  ❌ Index error: {r.text[:200]}")
            continue
        
        results = r.json().get("results", [])
        for chunk in results:
            chunk["_chat_name"] = chat["name"]
            chunk["_chat_id"] = chat["id"]
            chunk["_chat_type"] = chat["type"]
        all_chunks.extend(results)
    
    return all_chunks


def get_dense_embeddings(texts: list[str]) -> list[list[float]]:
    """Получаем dense эмбеддинги от VK API."""
    r = httpx.post(
        DENSE_URL,
        json={"model": DENSE_MODEL, "input": texts},
        auth=(LOGIN, PASSWORD),
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()["data"]
    # Сортируем по index
    data.sort(key=lambda x: x["index"])
    return [item["embedding"] for item in data]


def get_sparse_embeddings(texts: list[str]) -> list[dict]:
    """Получаем sparse эмбеддинги от нашего сервиса."""
    r = httpx.post(
        f"{INDEX_URL}/sparse_embedding",
        json={"texts": texts},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["vectors"]


def insert_into_qdrant(chunks: list[dict]):
    """Вставляем чанки в Qdrant (как делает проверяющая система)."""
    if not chunks:
        return 0
    
    # Dense эмбеддинги (батчами по 10)
    dense_texts = [c["dense_content"] for c in chunks]
    sparse_texts = [c["sparse_content"] for c in chunks]
    
    all_dense = []
    for i in range(0, len(dense_texts), 10):
        batch = dense_texts[i:i+10]
        try:
            embeddings = get_dense_embeddings(batch)
            all_dense.extend(embeddings)
        except Exception as e:
            print(f"  ⚠️ Dense embedding error (batch {i}): {e}")
            # Заглушка
            all_dense.extend([[0.0] * 1024] * len(batch))
        time.sleep(0.5)  # rate limit
    
    # Sparse эмбеддинги (батчами по 20)
    all_sparse = []
    for i in range(0, len(sparse_texts), 20):
        batch = sparse_texts[i:i+20]
        try:
            vectors = get_sparse_embeddings(batch)
            all_sparse.extend(vectors)
        except Exception as e:
            print(f"  ⚠️ Sparse embedding error (batch {i}): {e}")
            all_sparse.extend([{"indices": [], "values": []}] * len(batch))
    
    # Вставляем в Qdrant
    points = []
    for idx, chunk in enumerate(chunks):
        point = {
            "id": idx + 1,
            "vector": {
                "dense": all_dense[idx],
                "sparse": {
                    "indices": all_sparse[idx]["indices"],
                    "values": all_sparse[idx]["values"],
                },
            },
            "payload": {
                "page_content": chunk["page_content"],
                "metadata": {
                    "chat_name": chunk.get("_chat_name", ""),
                    "chat_type": chunk.get("_chat_type", ""),
                    "chat_id": chunk.get("_chat_id", ""),
                    "chat_sn": chunk.get("_chat_id", ""),
                    "message_ids": chunk["message_ids"],
                    "start": "",
                    "end": "",
                    "participants": [],
                    "mentions": [],
                    "contains_forward": False,
                    "contains_quote": False,
                },
            },
        }
        points.append(point)
    
    # Вставляем батчами по 50
    for i in range(0, len(points), 50):
        batch = points[i:i+50]
        r = httpx.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/points",
            json={"points": batch},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"  ❌ Qdrant upsert error: {r.text[:200]}")
    
    return len(points)


def search_query(query: str) -> list[str]:
    """Выполняем поиск."""
    r = httpx.post(
        f"{SEARCH_URL}/search",
        json={"question": {"text": query}},
        timeout=60,
    )
    if r.status_code != 200:
        print(f"  ❌ Search error: {r.text[:200]}")
        return []
    
    results = r.json().get("results", [])
    if not results:
        return []
    return results[0].get("message_ids", [])


def recall_at_k(predicted: list[str], relevant: set[str], k: int = 50) -> float:
    """Recall@K."""
    predicted_k = predicted[:k]
    if not relevant:
        return 0.0
    found = sum(1 for p in predicted_k if p in relevant)
    return found / len(relevant)


def ndcg_at_k(predicted: list[str], relevant: set[str], k: int = 50) -> float:
    """nDCG@K."""
    predicted_k = predicted[:k]
    if not relevant:
        return 0.0
    
    # DCG
    dcg = 0.0
    for i, p in enumerate(predicted_k):
        if p in relevant:
            dcg += 1.0 / math.log2(i + 2)  # i+2 потому что позиция 1-indexed
    
    # Ideal DCG
    idcg = 0.0
    for i in range(min(len(relevant), k)):
        idcg += 1.0 / math.log2(i + 2)
    
    return dcg / idcg if idcg > 0 else 0.0


# Тестовые запросы с ожидаемыми релевантными message_ids
# Мы знаем содержание наших сгенерированных данных, поэтому можем составить запросы
TEST_QUERIES = [
    {
        "text": "gRPC streaming в Go для нотификаций",
        "keywords": ["gRPC", "streaming", "Go", "нотификации"],
    },
    {
        "text": "Миграция базы данных PostgreSQL",
        "keywords": ["миграция", "PostgreSQL", "БД"],
    },
    {
        "text": "Kubernetes автоскейлинг HPA",
        "keywords": ["Kubernetes", "автоскейлинг", "HPA"],
    },
    {
        "text": "React Server Components",
        "keywords": ["React", "Server Components"],
    },
    {
        "text": "Обучение ML модели классификация тикетов",
        "keywords": ["ML", "модель", "классификация"],
    },
    {
        "text": "Вакансия Go Developer зарплата",
        "keywords": ["вакансия", "Go", "Developer"],
    },
    {
        "text": "Нагрузочное тестирование деградация rps",
        "keywords": ["нагрузочное", "тестирование", "rps"],
    },
    {
        "text": "Docker image оптимизация размер",
        "keywords": ["Docker", "image", "оптимизация"],
    },
]


def run_test(label: str):
    """Полный цикл тестирования."""
    print(f"\n{'='*60}")
    print(f"  🧪 ТЕСТ: {label}")
    print(f"{'='*60}")
    
    # 1. Health check
    print("\n1. Health check...")
    if not check_health():
        print("❌ Сервисы не готовы!")
        return None
    
    # 2. Reset Qdrant
    print("\n2. Пересоздание коллекции Qdrant...")
    if not reset_qdrant():
        return None
    
    # 3. Индексация
    print("\n3. Индексация чатов...")
    data_dir = Path("/home/wpng1337/poisk/solution/data")
    all_chunks = []
    
    for json_file in sorted(data_dir.glob("*.json")):
        if json_file.name == "generate_test_data.py":
            continue
        chat_data = load_chat(str(json_file))
        t0 = time.time()
        chunks = index_chat(chat_data)
        dt = time.time() - t0
        print(f"  📄 {json_file.name}: {len(chat_data['messages'])} msgs → {len(chunks)} чанков ({dt:.1f}s)")
        all_chunks.extend(chunks)
    
    print(f"\n  📊 Итого чанков: {len(all_chunks)}")
    
    # Статистика по чанкам
    total_msg_ids = sum(len(c["message_ids"]) for c in all_chunks)
    unique_msg_ids = len(set(mid for c in all_chunks for mid in c["message_ids"]))
    avg_chunk_len = sum(len(c["page_content"]) for c in all_chunks) / max(len(all_chunks), 1)
    print(f"  📊 Всего message_ids в чанках: {total_msg_ids}")
    print(f"  📊 Уникальных message_ids: {unique_msg_ids}")
    print(f"  📊 Средняя длина чанка: {avg_chunk_len:.0f} символов")
    
    # 4. Вставка в Qdrant
    print("\n4. Получение эмбеддингов и вставка в Qdrant...")
    t0 = time.time()
    inserted = insert_into_qdrant(all_chunks)
    dt = time.time() - t0
    print(f"  ✅ Вставлено {inserted} точек за {dt:.1f}s")
    
    # Ждём индексацию
    time.sleep(2)
    
    # Проверяем количество точек
    r = httpx.get(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=10)
    info = r.json()
    points_count = info["result"]["points_count"]
    print(f"  📊 Точек в Qdrant: {points_count}")
    
    # 5. Поиск
    print("\n5. Тестовые запросы...")
    
    # Собираем все message_ids по содержанию чанков
    # Для простоты: ищем ключевые слова в чанках и определяем "релевантные" message_ids
    search_results = []
    
    for q in TEST_QUERIES:
        t0 = time.time()
        found_ids = search_query(q["text"])
        dt = time.time() - t0
        
        # Определяем "релевантные" через keyword matching в чанках
        relevant_ids = set()
        for chunk in all_chunks:
            content = chunk["page_content"].lower()
            if any(kw.lower() in content for kw in q["keywords"]):
                relevant_ids.update(chunk["message_ids"])
        
        recall = recall_at_k(found_ids, relevant_ids)
        ndcg = ndcg_at_k(found_ids, relevant_ids)
        
        search_results.append({
            "query": q["text"],
            "found": len(found_ids),
            "relevant": len(relevant_ids),
            "recall": recall,
            "ndcg": ndcg,
            "time": dt,
        })
        
        status = "✅" if recall > 0.5 else "⚠️" if recall > 0 else "❌"
        print(f"  {status} \"{q['text'][:40]}...\" → {len(found_ids)} ids, "
              f"rel={len(relevant_ids)}, R@50={recall:.2f}, nDCG={ndcg:.2f} ({dt:.2f}s)")
    
    # 6. Итоговые метрики
    avg_recall = sum(r["recall"] for r in search_results) / len(search_results)
    avg_ndcg = sum(r["ndcg"] for r in search_results) / len(search_results)
    score = avg_recall * 0.8 + avg_ndcg * 0.2
    avg_time = sum(r["time"] for r in search_results) / len(search_results)
    
    print(f"\n{'='*60}")
    print(f"  📊 РЕЗУЛЬТАТ: {label}")
    print(f"{'='*60}")
    print(f"  Recall@50 avg:  {avg_recall:.4f}")
    print(f"  nDCG@50 avg:    {avg_ndcg:.4f}")
    print(f"  Score:          {score:.4f}")
    print(f"  Avg query time: {avg_time:.2f}s")
    print(f"  Total chunks:   {len(all_chunks)}")
    print(f"{'='*60}")
    
    return {
        "label": label,
        "recall": avg_recall,
        "ndcg": avg_ndcg,
        "score": score,
        "chunks": len(all_chunks),
        "avg_time": avg_time,
    }


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "test"
    result = run_test(label)
    if result:
        print(f"\n✅ Тест завершён: score={result['score']:.4f}")
    else:
        print("\n❌ Тест не пройден")
