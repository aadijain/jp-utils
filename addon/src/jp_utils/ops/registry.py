"""The concrete operations the add-on offers.

Each operation lives in its own module and appends itself here; the wiring layer
(runner, Pipelines tab) reads this list.
"""

from .base import Operation

ALL_OPERATIONS: list[Operation] = []
