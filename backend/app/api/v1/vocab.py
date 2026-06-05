"""Stateful vocabulary store router (/v1/vocab).

Personal vocabulary knowledge base, keyed on lemma+reading. Endpoints (event
ledger, projection, status, sync, export) are added in later tasks. Must not
import the text module.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/vocab", tags=["vocab"])
