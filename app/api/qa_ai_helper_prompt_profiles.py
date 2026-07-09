"""Retired QA AI Helper prompt profile API.

The custom style / prompt profile feature is no longer mounted.  Keep an empty
router module so stale imports fail closed without exposing endpoints.
"""

from fastapi import APIRouter

router = APIRouter()
