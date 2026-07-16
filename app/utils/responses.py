from typing import Any

import orjson
from fastapi.responses import JSONResponse


class ORJSONCompatResponse(JSONResponse):
    """Serialize JSON with orjson while preserving non-string key behavior."""

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content, option=orjson.OPT_NON_STR_KEYS)
