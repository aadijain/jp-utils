"""Stateless text-processing internals (tokenizer adapter, furigana,
conversions, deinflection). Endpoints live in `app/api/v1/text.py`; this package
holds the logic they call. Reaches reference data only via `app.dicts`."""
