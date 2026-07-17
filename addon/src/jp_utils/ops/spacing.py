"""Spacing operation: insert spaces at word boundaries in a chosen field, in place.

A :class:`FieldOperation` for **non-Lapis** note types, whose sentences are plain
text (no furigana ruby): it reads the alias chosen by its ``target`` param and
rewrites it with a ``separator`` (default a single space) inserted at every token
boundary, so a learner can see where the words split. Input and output are the
SAME alias, so it spaces in place. The target is a param-driven alias - the op
overrides :meth:`io_spec` so the framework validates and displays whichever field
the user picked (default ``sentence``).

The boundaries are the backend tokenizer's (``POST /v1/text/space``), so the
granularity follows its split mode; punctuation and particles are spaced too
(token-boundary spacing, not a content-word heuristic). Unlike the
markup-preserving :mod:`highlight` / :mod:`sentence_furigana` ops, this one treats
the field as plain text - it is meant for fields that carry none - so any HTML or
Anki text-form ruby would be tokenized rather than kept whole. Re-running is a
no-op: the tokenizer drops whitespace, so re-spacing already-spaced text produces
the same string and nothing is rewritten.
"""

from ..client import BackendClient
from ..config import ALIASES
from .base import FieldOperation, IOSpec, ParamSpec

# Default target when a step omits the param: the mined sentence field.
_DEFAULT_TARGET = "sentence"
# Default word-boundary separator: a single space.
_DEFAULT_SEPARATOR = " "


class SpacingOperation(FieldOperation):
    key = "spacing"
    label = "Space words in sentence"
    description = (
        "Inserts spaces at word boundaries in a chosen plain-text field, in "
        "place, using the backend tokenizer."
    )
    # No static input/output aliases: the target is param-driven (see io_spec).
    # No only_if_empty either - spacing in place must see (and may rewrite) the value.
    params_spec = (
        ParamSpec(
            "target",
            "Target field",
            "choice",
            default=_DEFAULT_TARGET,
            choices=ALIASES,
            description="The plain-text field to insert word-boundary spaces into, in place.",
        ),
        ParamSpec(
            "separator",
            "Separator",
            "text",
            default=_DEFAULT_SEPARATOR,
            description="Inserted at each word (token) boundary (default a single space).",
        ),
    )

    def io_spec(self, params: dict | None = None) -> IOSpec:
        target = (params or {}).get("target") or _DEFAULT_TARGET
        return IOSpec(required_inputs=(target,), outputs=(target,))

    def compute(
        self, client: BackendClient, sources: list[dict[str, str]], params: dict | None = None
    ) -> list[str | None]:
        params = params or {}
        target = params.get("target") or _DEFAULT_TARGET
        separator = params.get("separator")
        if separator is None:
            separator = _DEFAULT_SEPARATOR

        texts = [s.get(target, "") for s in sources]
        resp = client.post("/v1/text/space", {"texts": texts, "separator": separator})
        results = resp.get("results", [])

        out: list[str | None] = []
        for i, raw in enumerate(texts):
            spaced = results[i] if i < len(results) else raw
            out.append(spaced if spaced != raw else None)
        return out
