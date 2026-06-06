from app.text.tokenizer import Tokenizer
from app.text.words import content_words, is_content


def _tok(tokenizer: Tokenizer, text: str):
    return tokenizer.tokenize(text)[0]


def test_keeps_nouns_and_verbs_drops_particles(tokenizer: Tokenizer) -> None:
    # 猫 (noun) and 食べる (verb, deinflected) survive; を/た (particle/aux) drop.
    assert content_words(tokenizer, "猫が魚を食べた") == ["猫", "魚", "食べる"]


def test_deinflects_to_dictionary_form(tokenizer: Tokenizer) -> None:
    # Inflected verb -> lemma, not the surface form.
    assert "行く" in content_words(tokenizer, "学校に行きました")


def test_dedupes_preserving_order(tokenizer: Tokenizer) -> None:
    lemmas = content_words(tokenizer, "猫と猫")
    assert lemmas == ["猫"]


def test_drops_proper_nouns_and_numerals(tokenizer: Tokenizer) -> None:
    # 固有名詞 (names) + 数詞 (numerals) are excluded even though top-level is 名詞.
    assert is_content(_tok(tokenizer, "田中")) is False
    assert is_content(_tok(tokenizer, "三")) is False


def test_empty_text(tokenizer: Tokenizer) -> None:
    assert content_words(tokenizer, "") == []
    assert content_words(tokenizer, "。、！") == []
