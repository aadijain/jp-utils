"""Highlight operation: wrap a word in ``<b>`` inside a sentence, in place.

Both fields are param-driven: the ``word`` param picks the alias holding the word
to find and the ``sentence`` param picks the alias it is highlighted within (in
place), defaulting to the mined ``word``/``sentence`` fields. The op overrides
:meth:`io_spec` so the framework validates and displays whichever fields the user
chose.

The backend (``POST /v1/text/locate``) does the hard part - finding the word by
*lemma* so inflections are matched (食べた for 食べる), not by literal substring -
but it only sees plain text. This op is responsible for the markup: it parses the
``sentence`` field into "atoms" (plain characters, whole furigana-ruby units, and
HTML tags), feeds the backend only the plain *base* text (ruby readings and tags
stripped), then maps the located span back onto the atoms and wraps the matching
atoms in ``<b>...</b>``.

Wrapping whole atoms is what keeps furigana intact: a ruby unit (HTML
``<ruby>漢字<rt>かんじ</rt></ruby>`` or Anki text-form ``漢字[かんじ]``) is one atom,
so the bold goes around it rather than splitting it. The op writes back into the
``sentence`` field in place, and is idempotent: it leaves the text unchanged when
the match is already wrapped in ``<b>`` (so re-running, or a word the mining tool
already bolded, is a no-op).

Only the first match is highlighted (mirrors the backend's first-match contract).
"""

import re
from dataclasses import dataclass

from ..client import BackendClient
from ..config import ALIASES
from .base import FieldOperation, IOSpec, ParamSpec

# Defaults when a step omits the params: the mined word and sentence fields.
_DEFAULT_WORD = "word"
_DEFAULT_SENTENCE = "sentence"

# An HTML ``<ruby>`` block, any other HTML tag, or Anki text-form ruby
# ``base[reading]`` - tried in that order at each position.
_ATOM_RE = re.compile(
    r"(?P<ruby_html><ruby\b[^>]*>.*?</ruby>)"
    r"|(?P<tag><[^>]+>)"
    r"|(?P<text_ruby>[^\s\[\]<>]+\[[^\]]*\])",
    re.IGNORECASE | re.DOTALL,
)
_RT_RP_RE = re.compile(r"<r[tp]\b[^>]*>.*?</r[tp]>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_OPEN_B_RE = re.compile(r"<b(\s[^>]*)?>\Z", re.IGNORECASE)
_CLOSE_B_RE = re.compile(r"</b\s*>\Z", re.IGNORECASE)


@dataclass
class Atom:
    """One piece of the sentence: its source text and its plain-text contribution.

    ``raw`` is emitted verbatim; ``base`` is what the piece contributes to the
    plain text sent to the backend. Tags and ruby readings have ``base == ""`` so
    the backend never sees them, while their offsets still line up because base
    lengths sum to the plain text the backend tokenizes.
    """

    raw: str
    base: str


def _ruby_base(ruby_html: str) -> str:
    """The base text of an HTML ``<ruby>`` block (readings and tags removed)."""
    inner = re.sub(r"</?ruby\b[^>]*>", "", ruby_html, flags=re.IGNORECASE)
    inner = _RT_RP_RE.sub("", inner)
    return _TAG_RE.sub("", inner)


def parse_atoms(text: str) -> list[Atom]:
    """Split ``text`` into atoms (plain chars, ruby units, HTML tags)."""
    atoms: list[Atom] = []
    pos = 0
    for m in _ATOM_RE.finditer(text):
        atoms.extend(Atom(ch, ch) for ch in text[pos : m.start()])
        group = m.lastgroup
        if group == "ruby_html":
            atoms.append(Atom(m.group(), _ruby_base(m.group())))
        elif group == "tag":
            atoms.append(Atom(m.group(), ""))
        else:  # text_ruby: base is the part before the "[reading]"
            raw = m.group()
            atoms.append(Atom(raw, raw[: raw.index("[")]))
        pos = m.end()
    atoms.extend(Atom(ch, ch) for ch in text[pos:])
    return atoms


def plain_text(text: str) -> str:
    """The markup-stripped base text the backend tokenizes."""
    return "".join(a.base for a in parse_atoms(text))


def _match_span(segments: list[dict]) -> tuple[int, int] | None:
    """The first match's ``[start, end)`` offset into the base text, or None."""
    offset = 0
    for seg in segments:
        text = seg.get("text", "")
        if seg.get("match"):
            return offset, offset + len(text)
        offset += len(text)
    return None


def highlight(text: str, segments: list[dict]) -> str | None:
    """Wrap the located span in ``<b>``; None if nothing to do (no match / already bold)."""
    span = _match_span(segments)
    if span is None:
        return None
    start, end = span

    atoms = parse_atoms(text)
    matched: list[int] = []
    offset = 0
    for i, atom in enumerate(atoms):
        atom_end = offset + len(atom.base)
        if atom.base and offset < end and atom_end > start:  # base overlaps the span
            matched.append(i)
        offset = atom_end
    if not matched:
        return None

    first, last = matched[0], matched[-1]
    # Idempotent: skip if the match is already wrapped in <b> (re-run, or the
    # mining tool already bolded the word).
    if (
        first > 0
        and _OPEN_B_RE.search(atoms[first - 1].raw)
        and last + 1 < len(atoms)
        and _CLOSE_B_RE.search(atoms[last + 1].raw)
    ):
        return None

    prefix = "".join(a.raw for a in atoms[:first])
    middle = "".join(a.raw for a in atoms[first : last + 1])
    suffix = "".join(a.raw for a in atoms[last + 1 :])
    return f"{prefix}<b>{middle}</b>{suffix}"


class HighlightOperation(FieldOperation):
    key = "highlight"
    label = "Highlight word in sentence"
    description = (
        "Wraps the mined word in bold tags inside the sentence field, in place. "
        "Finds the word even when inflected in the sentence, and preserves "
        "existing furigana."
    )
    # No static input/output aliases: both the word to find and the sentence it is
    # highlighted in (in place) are param-driven (see io_spec). No only_if_empty
    # either - highlighting in place must see (and may rewrite) the value.
    params_spec = (
        ParamSpec(
            "word",
            "Word field",
            "choice",
            default=_DEFAULT_WORD,
            choices=ALIASES,
            description="The field holding the word to find (matched by lemma, inflection-aware).",
        ),
        ParamSpec(
            "sentence",
            "Sentence field",
            "choice",
            default=_DEFAULT_SENTENCE,
            choices=ALIASES,
            description="The field the word is wrapped in <b> within, in place.",
        ),
    )

    def io_spec(self, params: dict | None = None) -> IOSpec:
        params = params or {}
        word = params.get("word") or _DEFAULT_WORD
        sentence = params.get("sentence") or _DEFAULT_SENTENCE
        return IOSpec(required_inputs=(word, sentence), outputs=(sentence,))

    def compute(
        self, client: BackendClient, sources: list[dict[str, str]], params: dict | None = None
    ) -> list[str | None]:
        params = params or {}
        word_alias = params.get("word") or _DEFAULT_WORD
        sentence_alias = params.get("sentence") or _DEFAULT_SENTENCE

        queries = [
            {
                "text": plain_text(s.get(sentence_alias, "")),
                "word": plain_text(s.get(word_alias, "")),
            }
            for s in sources
        ]
        resp = client.post("/v1/text/locate", {"queries": queries})
        results = resp.get("results", [])

        out: list[str | None] = []
        for i, s in enumerate(sources):
            text = s.get(sentence_alias, "")
            segments = results[i].get("segments", []) if i < len(results) else []
            new = highlight(text, segments)
            out.append(new if new is not None and new != text else None)
        return out
