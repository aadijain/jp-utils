"""Stateless text service router (/v1/text).

Pure functions over read-only reference data; no user state. Endpoints
(tokenize, spacing, furigana, conversions, meaning, frequency, normalize) are
added in later tasks. Must not import the vocab module.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/text", tags=["text"])
