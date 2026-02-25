from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class DraftPayloadAdapter:
    """Wrap/unwrap helper drafts with a unified envelope contract."""

    SCHEMA_VERSION = "helper-draft.v2"

    def wrap(
        self,
        *,
        phase: str,
        data: Any,
        quality: Optional[Dict[str, Any]] = None,
        trace: Optional[Dict[str, Any]] = None,
        schema_version: Optional[str] = None,
    ) -> Any:
        if data is None:
            return None
        if self.is_envelope(data):
            return data
        payload_trace = deepcopy(trace) if isinstance(trace, dict) else {}
        payload_trace.setdefault("wrapped_at", datetime.now(timezone.utc).isoformat())
        payload_trace.setdefault("phase", str(phase or ""))
        envelope = {
            "schema_version": schema_version or self.SCHEMA_VERSION,
            "phase": str(phase or ""),
            "data": deepcopy(data),
            "quality": deepcopy(quality) if isinstance(quality, dict) else {},
            "trace": payload_trace,
        }
        return envelope

    def unwrap(self, payload: Any) -> Any:
        if not self.is_envelope(payload):
            return payload
        return deepcopy(payload.get("data"))

    @staticmethod
    def is_envelope(payload: Any) -> bool:
        return isinstance(payload, dict) and {
            "schema_version",
            "phase",
            "data",
        }.issubset(set(payload.keys()))

    def extract_meta(self, payload: Any) -> Dict[str, Any]:
        if not self.is_envelope(payload):
            return {}
        return {
            "schema_version": payload.get("schema_version"),
            "phase": payload.get("phase"),
            "quality": payload.get("quality") if isinstance(payload.get("quality"), dict) else {},
            "trace": payload.get("trace") if isinstance(payload.get("trace"), dict) else {},
        }
