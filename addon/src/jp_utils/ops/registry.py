"""The concrete operations the add-on offers.

Each operation lives in its own module; this list assembles them for the wiring
layer (runner, Pipelines tab) to iterate. Grows one operation at a time.
"""

from .base import Operation
from .frequency import FrequencyOperation
from .int_sort import IntSortOperation
from .sentence_furigana import SentenceFuriganaOperation
from .word_definition import WordDefinitionOperation
from .word_furigana import WordFuriganaOperation
from .word_reading import WordReadingOperation

ALL_OPERATIONS: list[Operation] = [
    WordReadingOperation(),
    WordFuriganaOperation(),
    SentenceFuriganaOperation(),
    WordDefinitionOperation(),
    FrequencyOperation(),
    IntSortOperation(),
]
