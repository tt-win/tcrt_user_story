import os

from dotenv import load_dotenv


load_dotenv()


DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_TEXT_EMBEDDING_URL = "http://127.0.0.1:1234/v1/embeddings"
DEFAULT_APP_PUBLIC_BASE_URL = "http://localhost:9999"


def get_qdrant_url() -> str:
    return os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL).strip() or DEFAULT_QDRANT_URL


def get_text_embedding_url() -> str:
    value = os.getenv("TEXT_EMBEDDING_URL")
    if value and value.strip():
        return value.strip()
    value = os.getenv("EMBEDDING_API_URL")
    if value and value.strip():
        return value.strip()
    return DEFAULT_TEXT_EMBEDDING_URL


def get_public_base_url() -> str:
    value = os.getenv("PUBLIC_BASE_URL")
    if value and value.strip():
        return value.strip()
    value = os.getenv("APP_BASE_URL")
    if value and value.strip():
        return value.strip()
    return DEFAULT_APP_PUBLIC_BASE_URL
