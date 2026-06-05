"""Stateful vocabulary store router (/v1/vocab).

Personal vocabulary knowledge base, keyed on lemma+reading. Must not
import the text module.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/vocab", tags=["vocab"])
