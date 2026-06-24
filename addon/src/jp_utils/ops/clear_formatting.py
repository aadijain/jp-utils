"""Clear-formatting operation: strip HTML/markup from a chosen field, in place.

A purely local :class:`FieldOperation` (the only one that makes no backend call):
it reads the alias chosen by its ``target`` param and rewrites it with its markup
removed (input and output are the SAME alias, so it cleans in place). The target is
a param-driven alias - the op overrides :meth:`io_spec` so the framework validates
and displays whichever field the user picked (default ``sentence``).

The strip (see :func:`strip_formatting`) is deliberately gentle: ``<br>`` becomes a
newline, HTML ``<ruby>`` is folded back to Anki's ``base[reading]`` text form so
furigana survives, any remaining tags are dropped, and entities are unescaped.
Whitespace is left as-is (no collapsing), and Anki text-form ruby ``漢字[かんじ]``
passes through untouched since it carries no tags. Re-running is a no-op (a field
already free of markup compares equal, so nothing is rewritten).
"""

import html
import re

from ..client import BackendClient
from ..config import ALIASES
from .base import FieldOperation, IOSpec, ParamSpec

# Default target when a step omits the param: the mined sentence field.
_DEFAULT_TARGET = "sentence"

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_RUBY_RE = re.compile(r"<ruby\b[^>]*>(.*?)</ruby>", re.IGNORECASE | re.DOTALL)
_RT_RE = re.compile(r"<rt\b[^>]*>(.*?)</rt>", re.IGNORECASE | re.DOTALL)
_RP_RE = re.compile(r"<rp\b[^>]*>.*?</rp>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _ruby_to_text(match: re.Match) -> str:
    """Fold one HTML ``<ruby>`` element into Anki ``base[reading]`` text form."""
    inner = match.group(1)
    reading = _TAG_RE.sub("", "".join(_RT_RE.findall(inner))).strip()
    base = _TAG_RE.sub("", _RT_RE.sub("", _RP_RE.sub("", inner))).strip()
    if base and reading:
        return f"{base}[{reading}]"
    return base or reading


def strip_formatting(text: str) -> str:
    """Remove HTML markup from ``text`` while preserving readings and line breaks.

    ``<br>`` -> newline, HTML ruby -> ``base[reading]``, remaining tags dropped,
    entities unescaped. Tags are handled before unescaping so escaped angle
    brackets (literal ``&lt;br&gt;``) stay literal text.
    """
    text = _BR_RE.sub("\n", text)
    text = _RUBY_RE.sub(_ruby_to_text, text)
    text = _TAG_RE.sub("", text)
    return html.unescape(text)


class ClearFormattingOperation(FieldOperation):
    key = "clear-formatting"
    label = "Clear formatting"
    # No static input/output aliases: the target is param-driven (see io_spec).
    # No only_if_empty either - stripping in place must see (and may rewrite) the value.
    params_spec = (
        ParamSpec(
            "target",
            "Target field",
            "choice",
            default=_DEFAULT_TARGET,
            choices=ALIASES,
            description="The field to strip markup from, in place (read and rewritten).",
        ),
    )

    def io_spec(self, params: dict | None = None) -> IOSpec:
        target = (params or {}).get("target") or _DEFAULT_TARGET
        return IOSpec(required_inputs=(target,), outputs=(target,))

    def compute(
        self, client: BackendClient, sources: list[dict[str, str]], params: dict | None = None
    ) -> list[str | None]:
        target = (params or {}).get("target") or _DEFAULT_TARGET
        out: list[str | None] = []
        for s in sources:
            raw = s.get(target, "")
            cleaned = strip_formatting(raw)
            out.append(cleaned if cleaned != raw else None)
        return out
