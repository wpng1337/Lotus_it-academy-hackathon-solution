import logging
import os
import asyncio
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

import httpx
from fastembed import SparseTextEmbedding
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from qdrant_client import AsyncQdrantClient, models

EMBEDDINGS_DENSE_MODEL = "Qwen/Qwen3-Embedding-0.6B"

# Ваш сервис должен считывать эти переменные из окружения (env), так как проверяющая система управляет ими
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8003"))

API_KEY = os.getenv("API_KEY")
EMBEDDINGS_DENSE_URL = os.getenv("EMBEDDINGS_DENSE_URL")
QDRANT_DENSE_VECTOR_NAME = os.getenv("QDRANT_DENSE_VECTOR_NAME", "dense")
QDRANT_SPARSE_VECTOR_NAME = os.getenv("QDRANT_SPARSE_VECTOR_NAME", "sparse")
SPARSE_MODEL_NAME = "Qdrant/bm25"
RERANKER_MODEL = "nvidia/llama-nemotron-rerank-1b-v2"
RERANKER_URL = os.getenv("RERANKER_URL")
OPEN_API_LOGIN = os.getenv("OPEN_API_LOGIN")
OPEN_API_PASSWORD = os.getenv("OPEN_API_PASSWORD")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "evaluation")
REQUIRED_ENV_VARS = [
    "EMBEDDINGS_DENSE_URL",
    "RERANKER_URL",
    "QDRANT_URL",
]
 
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("search-service")


def validate_required_env() -> None:
    if bool(OPEN_API_LOGIN) != bool(OPEN_API_PASSWORD):
        raise RuntimeError("OPEN_API_LOGIN and OPEN_API_PASSWORD must be set together")

    if not API_KEY and not (OPEN_API_LOGIN and OPEN_API_PASSWORD):
        raise RuntimeError("Either API_KEY or OPEN_API_LOGIN and OPEN_API_PASSWORD must be set")

    missing_env_vars = [
        name for name in REQUIRED_ENV_VARS if os.getenv(name) is None or os.getenv(name) == ""
    ]
    if not missing_env_vars:
        return

    logger.error("Empty required env vars: %s", ", ".join(missing_env_vars))
    raise RuntimeError(f"Empty required env vars: {', '.join(missing_env_vars)}")


validate_required_env()


def get_upstream_request_kwargs() -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    kwargs: dict[str, Any] = {"headers": headers}

    if OPEN_API_LOGIN and OPEN_API_PASSWORD:
        kwargs["auth"] = (OPEN_API_LOGIN, OPEN_API_PASSWORD)
        return kwargs

    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    return kwargs


# Модель данных, которую мы предоставляем и рассчитываем получать от вас
class DateRange(BaseModel):
    from_: str = Field(alias="from")
    to: str


class Entities(BaseModel):
    people: list[str] | None = None
    emails: list[str] | None = None
    documents: list[str] | None = None
    names: list[str] | None = None
    links: list[str] | None = None


class Question(BaseModel):
    text: str
    asker: str = ""
    asked_on: str = ""
    variants: list[str] | None = None
    hyde: list[str] | None = None
    keywords: list[str] | None = None
    entities: Entities | None = None
    date_mentions: list[str] | None = None
    date_range: DateRange | None = None
    search_text: str = ""


class SearchAPIRequest(BaseModel):
    question: Question


class SearchAPIItem(BaseModel):
    message_ids: list[str]


class SearchAPIResponse(BaseModel):
    results: list[SearchAPIItem]


class DenseEmbeddingItem(BaseModel):
    index: int
    embedding: list[float]


class DenseEmbeddingResponse(BaseModel):
    data: list[DenseEmbeddingItem]


class SparseVector(BaseModel):
    indices: list[int] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)


class SparseEmbeddingResponse(BaseModel):
    vectors: list[SparseVector]

# Метадата чанков в Qdrant'e, по которой вы можете фильтровать
class ChunkMetadata(BaseModel):
    chat_name: str
    chat_type: str # channel, group, private, thread
    chat_id: str
    chat_sn: str
    thread_sn: str | None = None
    message_ids: list[str]
    start: str
    end: str
    participants: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    contains_forward: bool = False
    contains_quote: bool = False


@lru_cache(maxsize=1)
def get_sparse_model() -> SparseTextEmbedding:
    logger.info("Loading local sparse model %s", SPARSE_MODEL_NAME)
    return SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient()
    app.state.qdrant = AsyncQdrantClient(
        url=QDRANT_URL,
        api_key=API_KEY,
    )
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.qdrant.close()


app = FastAPI(title="Search Service", version="0.1.0", lifespan=lifespan)


# Внутри шаблона dense и rerank берутся из внешних HTTP endpoint'ов,
# которые предоставляет проверяющая система.
# Текущий код ниже — минимальный пример search pipeline.
DENSE_PREFETCH_K = 50
SPARSE_PREFETCH_K = 150
RETRIEVE_K = 100
RERANK_LIMIT = 30

async def embed_dense(client: httpx.AsyncClient, text: str) -> list[float]:
    # Dense endpoint ожидает OpenAI-compatible body с input как списком строк.
    response = await client.post(
        EMBEDDINGS_DENSE_URL,
        **get_upstream_request_kwargs(),
        json={
            "model": os.getenv("EMBEDDINGS_DENSE_MODEL", EMBEDDINGS_DENSE_MODEL),
            "input": [text],
        },
    )
    response.raise_for_status()

    payload = DenseEmbeddingResponse.model_validate(response.json())
    if not payload.data:
        raise ValueError("Dense embedding response is empty")

    return payload.data[0].embedding


async def embed_dense_batch(client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
    """Батчевый dense embedding для HyDE/variants."""
    response = await client.post(
        EMBEDDINGS_DENSE_URL,
        **get_upstream_request_kwargs(),
        json={
            "model": os.getenv("EMBEDDINGS_DENSE_MODEL", EMBEDDINGS_DENSE_MODEL),
            "input": texts,
        },
    )
    response.raise_for_status()
    payload = DenseEmbeddingResponse.model_validate(response.json())
    payload.data.sort(key=lambda x: x.index)
    return [item.embedding for item in payload.data]


async def embed_sparse(text: str) -> SparseVector:
    vectors = list(get_sparse_model().embed([text]))
    if not vectors:
        raise ValueError("Sparse embedding response is empty")

    item = vectors[0]
    return SparseVector(
        indices=[int(index) for index in item.indices.tolist()],
        values=[float(value) for value in item.values.tolist()],
    )


def embed_sparse_sync(text: str) -> SparseVector:
    """Синхронная версия для asyncio.to_thread."""
    vectors = list(get_sparse_model().embed([text]))
    if not vectors:
        raise ValueError("Sparse embedding response is empty")

    item = vectors[0]
    return SparseVector(
        indices=[int(index) for index in item.indices.tolist()],
        values=[float(value) for value in item.values.tolist()],
    )


def build_dense_query(question: Question) -> str:
    """Формируем текст для dense embedding — семантический поиск.
    Используем search_text если есть — он уже оптимизирован."""
    if question.search_text:
        return question.search_text
    return question.text.strip()


def build_sparse_query(question: Question) -> str:
    """Формируем текст для sparse embedding — keyword matching."""
    parts = [question.text.strip()]
    if question.keywords:
        parts.extend(question.keywords)
    if question.search_text:
        parts = [question.search_text]
    return " ".join(parts)


async def qdrant_search(
    client: AsyncQdrantClient,
    dense_vectors: list[list[float]],
    sparse_vector: SparseVector,
    question: Question | None = None,
) -> Any | None:
    """Гибридный поиск с фильтрацией по метадате."""
    # Создаём prefetch для каждого dense вектора
    prefetch_list = []
    for dv in dense_vectors:
        prefetch_list.append(
            models.Prefetch(
                query=dv,
                using=QDRANT_DENSE_VECTOR_NAME,
                limit=DENSE_PREFETCH_K,
            )
        )
    # Sparse prefetch
    prefetch_list.append(
        models.Prefetch(
            query=models.SparseVector(
                indices=sparse_vector.indices,
                values=sparse_vector.values,
            ),
            using=QDRANT_SPARSE_VECTOR_NAME,
            limit=SPARSE_PREFETCH_K,
        )
    )

    # Формируем фильтры из метадаты вопроса
    must_conditions = []
    if question and question.date_range:
        try:
            must_conditions.append(
                models.FieldCondition(
                    key="metadata.end",
                    range=models.Range(gte=question.date_range.from_),
                )
            )
            must_conditions.append(
                models.FieldCondition(
                    key="metadata.start",
                    range=models.Range(lte=question.date_range.to),
                )
            )
        except Exception as e:
            logger.warning(f"Date filter failed: {e}")

    query_filter = models.Filter(must=must_conditions) if must_conditions else None

    response = await client.query_points(
        collection_name=QDRANT_COLLECTION_NAME,
        prefetch=prefetch_list,
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        query_filter=query_filter,
        limit=RETRIEVE_K,
        with_payload=True,
    )

    if not response.points:
        # Если с фильтром ничего не нашли — попробуем без фильтра
        if query_filter is not None:
            logger.info("No results with filter, retrying without")
            response = await client.query_points(
                collection_name=QDRANT_COLLECTION_NAME,
                prefetch=prefetch_list,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=RETRIEVE_K,
                with_payload=True,
            )

    if not response.points:
        return None

    return response.points


def extract_message_ids(point: Any) -> list[str]:
    payload = point.payload or {}
    metadata = payload.get("metadata") or {}
    message_ids = metadata.get("message_ids") or []

    return [str(message_id) for message_id in message_ids]


async def get_rerank_scores(
    client: httpx.AsyncClient,
    label: str,
    targets: list[str],
) -> list[float]:
    if not targets:
        return []

    # Retry с backoff при 429 (5 попыток, до 16 секунд ожидания)
    for attempt in range(5):
        try:
            response = await client.post(
                RERANKER_URL,
                **get_upstream_request_kwargs(),
                json={
                    "model": RERANKER_MODEL,
                    "encoding_format": "float",
                    "text_1": label,
                    "text_2": targets,
                },
            )
            if response.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"Rerank 429, retry {attempt+1}/5 in {wait}s")
                await asyncio.sleep(wait)
                continue
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") or []
            return [float(sample["score"]) for sample in data]
        except Exception as e:
            logger.warning(f"Rerank error attempt {attempt+1}/5: {e}")
            if attempt < 4:
                await asyncio.sleep(2 ** attempt)
                continue
            # Все попытки исчерпаны — возвращаем пустой список (fallback)
            logger.error(f"Rerank failed after 5 attempts, using fallback")
            return []

    # Все retry исчерпаны на 429 — возвращаем пустой список
    logger.error(f"Rerank 429 after 5 retries, using fallback")
    return []


async def rerank_points(
    client: httpx.AsyncClient,
    query: str,
    points: list[Any],
) -> list[Any]:
    rerank_candidates = points[:RERANK_LIMIT]
    rerank_targets = [point.payload.get("page_content") for point in rerank_candidates]
    scores = await get_rerank_scores(client, query, rerank_targets)

    # Если реранкер недоступен — возвращаем в оригинальном порядке (RRF)
    if not scores:
        logger.warning("Reranker unavailable, returning RRF order")
        return rerank_candidates

    reranked_candidates = [
        point
        for _, point in sorted(
            zip(scores, rerank_candidates, strict=True),
            key=lambda item: item[0],
            reverse=True,
        )
    ]

    return reranked_candidates


# Ваш сервис должен имплементировать оба этих метода
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/search", response_model=SearchAPIResponse)
async def search(payload: SearchAPIRequest) -> SearchAPIResponse:
    question = payload.question
    query = question.text.strip()
    if not query:
        raise HTTPException(status_code=400, detail="question.text is required")

    client: httpx.AsyncClient = app.state.http
    qdrant: AsyncQdrantClient = app.state.qdrant

    # Формируем разные тексты для dense и sparse
    dense_query = build_dense_query(question)
    sparse_query = build_sparse_query(question)

    # Параллельный embedding: dense + sparse одновременно
    dense_task = embed_dense(client, dense_query)
    sparse_task = asyncio.to_thread(lambda: embed_sparse_sync(sparse_query))
    dense_vector, sparse_vector = await asyncio.gather(dense_task, sparse_task)

    # Собираем все dense векторы (основной + HyDE)
    dense_vectors = [dense_vector]
    if question.hyde and len(question.hyde) > 0:
        try:
            hyde_texts = question.hyde[:2]
            hyde_vectors = await embed_dense_batch(client, hyde_texts)
            dense_vectors.extend(hyde_vectors)
        except Exception as e:
            logger.warning(f"HyDE embedding failed: {e}")

    # Поиск в Qdrant (с фильтрацией по метадате)
    all_points = await qdrant_search(qdrant, dense_vectors, sparse_vector, question)

    if all_points is None:
        return SearchAPIResponse(results=[])

    all_points = list(all_points)

    # Rerank top кандидатов
    reranked = await rerank_points(client, query, all_points)

    # Добавляем оставшиеся (не-reranked) точки после reranked для лучшего recall
    reranked_ids = {id(p) for p in reranked}
    remaining = [p for p in all_points if id(p) not in reranked_ids]
    final_points = reranked + remaining

    # Дедупликация message_ids с сохранением порядка релевантности
    seen: set[str] = set()
    message_ids: list[str] = []
    for point in final_points:
        for mid in extract_message_ids(point):
            if mid not in seen:
                seen.add(mid)
                message_ids.append(mid)
    message_ids = message_ids[:50]  # K=50

    return SearchAPIResponse(
        results=[SearchAPIItem(message_ids=message_ids)]
    )


@app.exception_handler(Exception)
async def exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(exc)
    detail = str(exc) or repr(exc)

    if isinstance(exc, RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return JSONResponse(status_code=500, content={"detail": detail})


def main() -> None:
    import uvicorn

    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
