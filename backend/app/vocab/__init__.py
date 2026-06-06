"""Stateful personal vocabulary store. Must not import the text module."""

from app.vocab.store import VocabStore, default_db_path

__all__ = ["VocabStore", "default_db_path"]
