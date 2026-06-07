"""Operations framework + the concrete operations built on it.

:mod:`base` holds the pure orchestration (the :class:`Operation` contract,
:func:`resolve_pipeline_steps`, :func:`plan_operations`); the concrete operations
and their registry are layered on top.
"""

from .base import (
    ONLY_IF_EMPTY,
    ConfiguredOp,
    FieldOperation,
    FieldUpdate,
    IOSpec,
    NoteFields,
    NotePlan,
    Operation,
    ParamSpec,
    plan_operations,
    resolve_params,
    resolve_pipeline_steps,
)
from .registry import ALL_OPERATIONS

__all__ = [
    "ALL_OPERATIONS",
    "ONLY_IF_EMPTY",
    "ConfiguredOp",
    "FieldOperation",
    "FieldUpdate",
    "IOSpec",
    "NoteFields",
    "NotePlan",
    "Operation",
    "ParamSpec",
    "plan_operations",
    "resolve_params",
    "resolve_pipeline_steps",
]
