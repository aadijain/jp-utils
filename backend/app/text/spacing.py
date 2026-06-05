"""Word-boundary spacing.

Inserts a separator at token boundaries so learners can see where words split -
the boundaries are exactly the tokenizer's, so granularity follows the split
mode. Punctuation and particles get spaced too (token-boundary spacing, not a
content-word heuristic).
"""

from app.text.tokenizer import Tokenizer
from shared.text import SplitMode


def space_text(
    tokenizer: Tokenizer,
    text: str,
    separator: str = " ",
    mode: SplitMode = SplitMode.C,
) -> str:
    return separator.join(token.surface for token in tokenizer.tokenize(text, mode))
