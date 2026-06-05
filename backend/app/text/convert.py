"""Kana, romaji, and width conversions (jaconv).

Width conversions cover kana, ASCII, and digits, so `to_fullwidth` /
`to_halfwidth` are complete width normalizations. `kana_to_romaji` accepts either
kana. `kata_to_hira` is exported for reuse (e.g. furigana reading normalization).
"""

from collections.abc import Callable

import jaconv

from shared.text import Conversion


def hira_to_kata(text: str) -> str:
    return jaconv.hira2kata(text)


def kata_to_hira(text: str) -> str:
    return jaconv.kata2hira(text)


def kana_to_romaji(text: str) -> str:
    # kana2alphabet only handles hiragana, so fold katakana down first.
    return jaconv.kana2alphabet(kata_to_hira(text))


def romaji_to_kana(text: str) -> str:
    return jaconv.alphabet2kana(text)


def to_fullwidth(text: str) -> str:
    return jaconv.h2z(text, kana=True, ascii=True, digit=True)


def to_halfwidth(text: str) -> str:
    return jaconv.z2h(text, kana=True, ascii=True, digit=True)


# Each Conversion maps to the like-named function above.
_CONVERTERS: dict[Conversion, Callable[[str], str]] = {
    Conversion.HIRA_TO_KATA: hira_to_kata,
    Conversion.KATA_TO_HIRA: kata_to_hira,
    Conversion.KANA_TO_ROMAJI: kana_to_romaji,
    Conversion.ROMAJI_TO_KANA: romaji_to_kana,
    Conversion.TO_FULLWIDTH: to_fullwidth,
    Conversion.TO_HALFWIDTH: to_halfwidth,
}


def convert(text: str, conversion: Conversion) -> str:
    return _CONVERTERS[conversion](text)
