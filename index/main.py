import logging
import os
from functools import lru_cache
from typing import Any
import asyncio
import hashlib

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Ваш сервис должен считывать эти переменные из окружения (env), так как проверяющая система управляет ими
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8004"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("index-service")


# Модель данных, которую мы предоставляем и рассчитываем получать от вас
class Chat(BaseModel):
    id: str
    name: str
    sn: str
    type: str  # group, channel, private
    is_public: bool | None = None
    members_count: int | None = None
    members: list[dict[str, Any]] | None = None


class Message(BaseModel):
    id: str
    thread_sn: str | None = None
    time: int
    text: str
    sender_id: str
    file_snippets: str
    parts: list[dict[str, Any]] | None = None
    mentions: list[str] | None = None
    member_event: dict[str, Any] | None = None
    is_system: bool
    is_hidden: bool
    is_forward: bool
    is_quote: bool


class ChatData(BaseModel):
    chat: Chat
    overlap_messages: list[Message]
    new_messages: list[Message]


class IndexAPIRequest(BaseModel):
    data: ChatData


# dense_content будет передан в dense embedding модель для построения семантического вектора.
# sparse_content будет передан в sparse модель для построения разреженного индекса "по словам".
# Можно оставить dense_content и sparse_content равными page_content,
# а можно формировать для них разные версии текста.
class IndexAPIItem(BaseModel):
    page_content: str
    dense_content: str
    sparse_content: str
    message_ids: list[str]


class IndexAPIResponse(BaseModel):
    results: list[IndexAPIItem]


class SparseEmbeddingRequest(BaseModel):
    texts: list[str]


class SparseVector(BaseModel):
    indices: list[int]
    values: list[float]


class SparseEmbeddingResponse(BaseModel):
    vectors: list[SparseVector]


app = FastAPI(title="Index Service", version="0.1.0")

# Ваша внутренняя логика построения чанков. Можете делать всё, что посчитаете нужным.
# Текущий код – минимальный пример

CHUNK_SIZE = 384
OVERLAP_SIZE = 128
SPARSE_MODEL_NAME = "Qdrant/bm25"
FASTEMBED_CACHE_PATH = "/models/fastembed"

# Важная переманная, которая позволяет вычислять sparse вектор в несколько ядер. Не рекомендуется изменять.
UVICORN_WORKERS=8

def render_message(message: Message) -> str:
    parts_list: list[str] = []

    # Добавляем sender для контекста (имя до @)
    if message.sender_id:
        sender_name = message.sender_id.split("@")[0].replace(".", " ")
        parts_list.append(f"[{sender_name}]:")

    if message.text:
        parts_list.append(message.text)

    if message.parts:
        for part in message.parts:
            media_type = part.get("mediaType", "text")
            part_text = part.get("text")
            if isinstance(part_text, str) and part_text:
                if media_type == "forward":
                    parts_list.append(f"[Пересланное]: {part_text}")
                elif media_type == "quote":
                    parts_list.append(f"[Цитата]: {part_text}")
                else:
                    parts_list.append(part_text)

    if message.file_snippets:
        parts_list.append(f"[Файл]: {message.file_snippets}")

    return " ".join(parts_list).strip()


def build_chunks(
    chat: Chat,
    overlap_messages: list[Message],
    new_messages: list[Message],
) -> list[IndexAPIItem]:
    # Фильтруем системные и скрытые сообщения
    new_messages = [m for m in new_messages if not m.is_system and not m.is_hidden]
    overlap_messages = [m for m in overlap_messages if not m.is_system and not m.is_hidden]

    result: list[IndexAPIItem] = []

    # Рендерим все сообщения
    rendered_new = []
    for msg in new_messages:
        text = render_message(msg)
        if text:
            rendered_new.append((msg.id, text))

    if not rendered_new:
        return result

    # Message-based chunking: группируем по MSGS_PER_CHUNK сообщений
    # с overlap MSGS_OVERLAP сообщений между чанками
    MSGS_PER_CHUNK = 5
    MSGS_OVERLAP = 2

    # Рендерим overlap для контекста
    overlap_texts = []
    for msg in overlap_messages[-MSGS_OVERLAP:]:
        text = render_message(msg)
        if text:
            overlap_texts.append(text)
    overlap_context = "\n".join(overlap_texts)

    for start_idx in range(0, len(rendered_new), MSGS_PER_CHUNK - MSGS_OVERLAP):
        chunk_msgs = rendered_new[start_idx : start_idx + MSGS_PER_CHUNK]
        if not chunk_msgs:
            continue

        # Тело чанка из сообщений
        chunk_body = "\n".join(text for _, text in chunk_msgs)
        message_ids = [mid for mid, _ in chunk_msgs]

        # Добавляем overlap контекст (предыдущие сообщения)
        if start_idx == 0 and overlap_context:
            chunk_text = overlap_context + "\n" + chunk_body
        elif start_idx > 0:
            # Overlap из предыдущих сообщений в rendered_new
            prev_msgs = rendered_new[max(0, start_idx - MSGS_OVERLAP) : start_idx]
            prev_text = "\n".join(text for _, text in prev_msgs)
            chunk_text = prev_text + "\n" + chunk_body if prev_text else chunk_body
        else:
            chunk_text = chunk_body

        # dense_content обогащаем названием чата для лучшей семантики
        dense_text = f"[{chat.name}] {chunk_text}"
        # sparse_content — только тело чанка без overlap для точного BM25
        sparse_text = chunk_body

        result.append(
            IndexAPIItem(
                page_content=chunk_text,
                dense_content=dense_text,
                sparse_content=sparse_text,
                message_ids=message_ids,
            )
        )

    return result

# Ваш сервис должен имплементировать оба этих метода
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/index", response_model=IndexAPIResponse)
async def index(payload: IndexAPIRequest) -> IndexAPIResponse:
    return IndexAPIResponse(
        results=build_chunks(
            payload.data.chat,
            payload.data.overlap_messages,
            payload.data.new_messages,
        )
    )


@lru_cache(maxsize=1)
def get_sparse_model():
    from fastembed import SparseTextEmbedding

    # можете делать любой вектор, который будет совместим с вашим поиском в Qdrant
    # помните об ограничении времени выполнения вашей работы в тестирующей системе
    logger.info(
        "Loading sparse model %s from cache %s",
        SPARSE_MODEL_NAME,
        FASTEMBED_CACHE_PATH,
    )
    return SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)


def embed_sparse_texts(texts: list[str]) -> list[SparseVector]:
    model = get_sparse_model()
    vectors: list[dict[str, list[int] | list[float]]] = []

    for item in model.embed(texts):
        vectors.append(
            {
                "indices": item.indices.tolist(),
                "values": item.values.tolist(),
            }
        )

    return vectors


@app.post("/sparse_embedding")
async def sparse_embedding(payload: SparseEmbeddingRequest) -> dict[str, Any]:
    # Проверяющая система вызывает этот endpoint при создании коллекции
    vectors = await asyncio.to_thread(embed_sparse_texts, payload.texts)
    return {"vectors": vectors}

# красивая обработка ошибок
@app.exception_handler(Exception)
async def exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(exc)

    if isinstance(exc, RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    return JSONResponse(status_code=500, content={"detail": str(exc)})


def main() -> None:
    import uvicorn

    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False,
        workers=UVICORN_WORKERS,
    )


if __name__ == "__main__":
    main()
