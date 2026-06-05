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

# Max glosses kept per headword, across all senses and their synonymous
# phrasings. Caps highly polysemous words so a field stays readable.
MAX_GLOSSES = 8

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
    glosses: list[str]
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
    """Plain text of a structured-content node, dropping rt (furigana) and links."""
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


def _parse_glossary(glossary: Any) -> list[str]:
    if not isinstance(glossary, list):
        return []
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
                glosses = _parse_glossary(row[5])
                if not glosses:
                    continue
                rows.append(
                    MeaningRow(
                        lemma=expression,
                        reading=row[1] or "",
                        glosses=glosses,
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
