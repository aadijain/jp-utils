"""Parse the three reference-dictionary zip formats into plain rows.

Each parser yields normalized rows; turning rows into the SQLite cache is
`cache.py`'s job. The Yomitan structured-content glossary, the JPDB frequency
shapes, and the JmdictFurigana BOM are each handled per their published format.
"""

import json
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

from app.text.convert import kata_to_hira

# Max glosses kept per sense (synonymous phrasings of one meaning). Caps a
# pathologically long sense; the plain-string fallback path also uses it as a
# total cap across the lone synthesised sense.
MAX_GLOSSES = 8

# Max senses kept per headword and max example sentences kept per sense. Bound
# the stored structure so a definition field stays renderable; the add-on's
# formatter shows one example per sense, so one is all that's stored.
MAX_SENSES = 12
MAX_EXAMPLES_PER_SENSE = 1

# jitendex priority floor for the meanings catalog (see _drop_low_score). score
# is jitendex's own per-entry priority: ~200/99 = common primary sense, 0 = the
# default (a mix of obscure AND very common colloquial forms), <0 = penalized.
MIN_SCORE = 1

_TERM_BANK_RE = re.compile(r"(^|/)term_bank_\d+\.json$")
_TERM_META_BANK_RE = re.compile(r"(^|/)term_meta_bank_\d+\.json$")
_FURIGANA_JSON_RE = re.compile(r"(^|/)JmdictFurigana\.json$")
_JLPT_RE = re.compile(r"jlpt[\s-]?n?([1-5])\b", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


class MeaningRow(NamedTuple):
    lemma: str
    reading: str
    senses: list[dict]  # [{"pos": [str], "glosses": [str], "examples": [{"ja","en"}]}]
    score: int
    seq: int
    jlpt: int | None


class FreqRow(NamedTuple):
    term: str
    reading: str  # hiragana; for kana-form rows the term itself is the reading
    rank: int
    is_kana_form: bool


class FuriganaRow(NamedTuple):
    text: str
    reading: str
    segments: list[dict[str, str]]  # [{"ruby": ..., "rt": ...}], rt="" for kana chunks


# ── jitendex (meanings) ──────────────────────────────────────────────────────


def _clean_text(s: str) -> str:
    return _WS_RE.sub(" ", s.replace("​", "")).strip()


def _jlpt_from_tags(tags: str) -> int | None:
    m = _JLPT_RE.search(tags)
    return int(m.group(1)) if m else None


def _plain_text(node: Any) -> str:
    """Plain text of a structured-content node, dropping rt (furigana), links and
    attribution footnotes (the ``[1]`` example-source markers)."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_plain_text(n) for n in node)
    if isinstance(node, dict):
        if node.get("type") == "image":
            return ""
        if node.get("tag") in ("rt", "a"):
            return ""
        data = node.get("data")
        if isinstance(data, dict) and data.get("content") == "attribution-footnote":
            return ""
        if isinstance(node.get("text"), str):
            return node["text"]
        if "content" in node:
            return _plain_text(node["content"])
    return ""


def _collect_glosses(node: Any, out: list[str]) -> None:
    """Whitelist walk: only `data.content == "glossary"` blocks contribute text.

    Keeps every item in a glossary block (items within a block are the
    synonymous phrasings of one sense, e.g. "great", "huge", "enormous").
    """
    if node is None or isinstance(node, str):
        return
    if isinstance(node, list):
        for n in node:
            _collect_glosses(n, out)
        return
    if isinstance(node, dict):
        data = node.get("data")
        if isinstance(data, dict) and data.get("content") == "glossary":
            content = node.get("content")
            items = content if isinstance(content, list) else ([content] if content else [])
            for item in items:
                text = _clean_text(_plain_text(item))
                if text:
                    out.append(text)
            return
        if "content" in node:
            _collect_glosses(node["content"], out)


def _data_role(node: Any) -> str | None:
    """The jitendex structured-content role tag (`data.content`) of a node."""
    data = node.get("data") if isinstance(node, dict) else None
    return data.get("content") if isinstance(data, dict) else None


def _collect_pos(node: Any, out: list[str]) -> None:
    """Collect part-of-speech labels (`part-of-speech-info` spans) in a subtree.

    POS spans live at the `sense-group` level (not inside `sense` blocks), so a
    plain subtree walk over one sense-group picks up only that group's tags.
    """
    if isinstance(node, list):
        for n in node:
            _collect_pos(n, out)
    elif isinstance(node, dict):
        if _data_role(node) == "part-of-speech-info":
            text = _clean_text(_plain_text(node.get("content")))
            if text and text not in out:
                out.append(text)
            return
        if "content" in node:
            _collect_pos(node["content"], out)


def _collect_examples(node: Any, out: list[dict[str, str]]) -> None:
    """Collect example sentences (`example-sentence` blocks) in a sense subtree.

    Each block carries a Japanese line (`example-sentence-a`) and an English
    translation (`example-sentence-b`); ruby is dropped, leaving plain text.
    """
    if isinstance(node, list):
        for n in node:
            _collect_examples(n, out)
        return
    if not isinstance(node, dict):
        return
    if _data_role(node) == "example-sentence":
        ja = en = ""
        content = node.get("content")
        for child in content if isinstance(content, list) else [content]:
            if not isinstance(child, dict):
                continue
            role = _data_role(child)
            if role == "example-sentence-a":
                ja = _clean_text(_plain_text(child.get("content")))
            elif role == "example-sentence-b":
                en = _clean_text(_plain_text(child.get("content")))
        if ja and len(out) < MAX_EXAMPLES_PER_SENSE:
            out.append({"ja": ja, "en": en})
        return
    if "content" in node:
        _collect_examples(node["content"], out)


def _collect_senses(node: Any, pos: list[str], out: list[dict]) -> None:
    """Walk the structured content into a flat list of senses.

    A `sense-group` carries the POS shared by its senses; each `sense` block
    becomes one entry of ``out`` (its synonymous glosses + up to N examples),
    inheriting the enclosing group's POS.
    """
    if isinstance(node, list):
        for n in node:
            _collect_senses(n, pos, out)
        return
    if not isinstance(node, dict):
        return
    role = _data_role(node)
    if role == "sense-group":
        group_pos: list[str] = []
        _collect_pos(node, group_pos)
        _collect_senses(node.get("content"), group_pos, out)
        return
    if role == "sense":
        glosses: list[str] = []
        _collect_glosses(node, glosses)
        if glosses:
            examples: list[dict[str, str]] = []
            _collect_examples(node, examples)
            out.append({"pos": list(pos), "glosses": glosses[:MAX_GLOSSES], "examples": examples})
        return
    if "content" in node:
        _collect_senses(node["content"], pos, out)


def _parse_senses(glossary: Any) -> list[dict]:
    """Parse a jitendex glossary into a list of senses (best-effort).

    Prefers the structured `sense-group`/`sense` shape; falls back to a single
    synthesised sense from any plain-string / loosely-structured glossary items
    (no POS, no examples), so simple entries still produce one usable sense.
    """
    if not isinstance(glossary, list):
        return []
    senses: list[dict] = []
    _collect_senses(glossary, [], senses)
    if senses:
        return senses[:MAX_SENSES]
    flat = _parse_flat_glosses(glossary)
    return [{"pos": [], "glosses": flat, "examples": []}] if flat else []


def _parse_flat_glosses(glossary: list) -> list[str]:
    """Flatten plain-string / unstructured glossary items (fallback path)."""
    out: list[str] = []
    for item in glossary:
        if len(out) >= MAX_GLOSSES:
            break
        if isinstance(item, str):
            text = _clean_text(item)
            if text:
                out.append(text)
        elif isinstance(item, dict):
            if item.get("type") == "image":
                continue
            if item.get("type") == "structured-content":
                _collect_glosses(item.get("content"), out)
            elif isinstance(item.get("text"), str):
                text = _clean_text(item["text"])
                if text:
                    out.append(text)
            else:
                text = _clean_text(_plain_text(item.get("content")))
                if text:
                    out.append(text)
    return out[:MAX_GLOSSES]


def _drop_low_score(rows: list[MeaningRow]) -> list[MeaningRow]:
    """Filter out low-priority jitendex entries (see MIN_SCORE).

    - score < 0: always dropped (jitendex-penalized / incorrect entries).
    - 0 <= score < MIN_SCORE: dropped only when the lemma has another entry at
      score >= MIN_SCORE, so a word whose only senses are score 0 (e.g. common
      colloquial forms like お客さん) stays lookupable rather than vanishing.
    """
    has_primary = {r.lemma for r in rows if r.score >= MIN_SCORE}
    out: list[MeaningRow] = []
    for r in rows:
        if r.score < 0:
            continue
        if r.score < MIN_SCORE and r.lemma in has_primary:
            continue
        out.append(r)
    return out


def parse_jitendex(zip_path: Path) -> Iterator[MeaningRow]:
    """Yield MeaningRows per term-bank headword that has at least one gloss.

    Low-priority entries are dropped by score (`_drop_low_score`), so the rows
    are buffered and filtered before yielding (a lemma's entries can span banks).

    Term-bank row layout (Yomitan v3):
        [expression, reading, defTags, rules, score, glossary, sequence, termTags]
    """
    rows: list[MeaningRow] = []
    with zipfile.ZipFile(zip_path) as zf:
        banks = sorted(n for n in zf.namelist() if _TERM_BANK_RE.search(n))
        if not banks:
            raise ValueError("jitendex zip has no term_bank_*.json (not a Yomitan dict?)")
        for bank in banks:
            for row in json.loads(zf.read(bank)):
                expression = row[0]
                if not expression:
                    continue
                senses = _parse_senses(row[5])
                if not senses:
                    continue
                rows.append(
                    MeaningRow(
                        lemma=expression,
                        reading=row[1] or "",
                        senses=senses,
                        score=row[4] if isinstance(row[4], int) else 0,
                        seq=row[6] if isinstance(row[6], int) else 0,
                        jlpt=_jlpt_from_tags(row[7] if isinstance(row[7], str) else ""),
                    )
                )
    yield from _drop_low_score(rows)


# ── JPDB (frequency) ─────────────────────────────────────────────────────────

# displayValue carrying ㋕ marks a kana-form rank; kanji-form ranks are preferred.
_KANA_MARK = "㋕"


def _extract_freq(data: Any) -> tuple[int, str | None, bool] | None:
    """Return (rank, reading, is_kana_form) from a JPDB freq value, or None.

    `reading` is the kanji entry's reading; it is None for the bare kana value
    form (where the term itself is the reading - the caller fills it in).
    """
    if isinstance(data, dict):
        if isinstance(data.get("value"), int):
            display = data.get("displayValue") or ""
            return data["value"], None, _KANA_MARK in display
        freq = data.get("frequency")
        if isinstance(freq, dict) and isinstance(freq.get("value"), int):
            display = freq.get("displayValue") or ""
            reading = data.get("reading") if isinstance(data.get("reading"), str) else None
            return freq["value"], reading, _KANA_MARK in display
    return None


def parse_jpdb_freq(zip_path: Path) -> Iterator[FreqRow]:
    """Yield FreqRow per frequency entry.

    Row layout: [term, "freq", data] where data is {value, displayValue} (kana
    terms) or {reading, frequency: {value, displayValue}} (kanji terms).
    """
    with zipfile.ZipFile(zip_path) as zf:
        banks = sorted(n for n in zf.namelist() if _TERM_META_BANK_RE.search(n))
        if not banks:
            raise ValueError("JPDB zip has no term_meta_bank_*.json files")
        for bank in banks:
            rows = json.loads(zf.read(bank))
            for row in rows:
                term, kind, data = row[0], row[1], row[2]
                if kind != "freq" or not term:
                    continue
                parsed = _extract_freq(data)
                if parsed is None:
                    continue
                rank, reading, is_kana = parsed
                # Kana value form carries no reading: the term is the reading.
                # Normalize to hiragana so lookups compare in one space.
                yield FreqRow(
                    term=term,
                    reading=kata_to_hira(reading or term),
                    rank=rank,
                    is_kana_form=is_kana,
                )


# ── JmdictFurigana ───────────────────────────────────────────────────────────


def parse_jmdict_furigana(zip_path: Path) -> Iterator[FuriganaRow]:
    """Yield FuriganaRow per entry with the full segmentation.

    Entry shape: {text, reading, furigana: [{ruby, rt?}]}. Kana-only segments
    omit `rt`; they're kept with rt="" so the whole word can be reconstructed.
    The JSON file is UTF-8 with a BOM.
    """
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if _FURIGANA_JSON_RE.search(n)]
        if not names:
            raise ValueError("zip has no JmdictFurigana.json")
        raw = zf.read(names[0]).decode("utf-8-sig")  # -sig strips the BOM
        rows = json.loads(raw)
        for row in rows:
            text = row.get("text")
            reading = row.get("reading")
            furigana = row.get("furigana")
            if not text or not reading or not isinstance(furigana, list):
                continue
            # Keep the FULL segmentation (kana chunks too, with rt=""), so the
            # furigana endpoint can reconstruct the whole word for rendering.
            segments = [
                {"ruby": s["ruby"], "rt": s.get("rt") or ""} for s in furigana if s.get("ruby")
            ]
            yield FuriganaRow(text=text, reading=reading, segments=segments)
