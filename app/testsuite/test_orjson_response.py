from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.main import app


_test_router = APIRouter(prefix="/test/orjson")


@_test_router.get("/int-key")
async def _int_key_response():
    return {1: "a"}


app.include_router(_test_router)


def test_default_orjson_response_preserves_int_key_semantics():
    response = TestClient(app).get("/test/orjson/int-key")

    assert response.status_code == 200
    assert response.json() == {"1": "a"}
