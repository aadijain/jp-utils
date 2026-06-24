"""The concrete operations the add-on offers.

Each operation lives in its own module; this list assembles them for the wiring
layer (runner, Pipelines tab) to iterate. Grows one operation at a time.
"""

from .base import Operation
from .clear_formatting import ClearFormattingOperation
from .frequency import FrequencyOperation
from .generate import GenerateVocabOperation
from .int_sort import IntSortOperation
from .nplus1 import Nplus1SequenceOperation
from .sentence_furigana import SentenceFuriganaOperation
from .sync_status import SyncWordStatusOperation
from .word_audio import WordAudioOperation
from .word_definition import WordDefinitionOperation
from .word_furigana import WordFuriganaOperation
from .word_reading import WordReadingOperation

ALL_OPERATIONS: list[Operation] = [
    WordReadingOperation(),
    WordFuriganaOperation(),
    SentenceFuriganaOperation(),
    WordDefinitionOperation(),
    FrequencyOperation(),
    WordAudioOperation(),
    Nplus1SequenceOperation(),
    IntSortOperation(),
    GenerateVocabOperation(),
    SyncWordStatusOperation(),
    ClearFormattingOperation(),
]
