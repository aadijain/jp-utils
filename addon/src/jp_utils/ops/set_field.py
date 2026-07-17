"""Set-field operation: write a fixed literal value into a chosen field.

A purely local :class:`FieldOperation` (no backend call) that sets one alias to a
constant the user types. It is deliberately datatype-agnostic - it sets *any*
field with a plain string, so the same op covers Lapis' boolean toggle flags
(``'true'`` / empty for ``IsClickCard`` etc.), a category label, or any
other fixed value; there is no separate "boolean" kind.

Both halves come from params: ``target`` picks the alias to write (param-driven,
so :meth:`io_spec` validates and displays whichever field is chosen) and ``value``
is the literal to write. Neither has a default - the op does nothing useful until
the user configures both. An *explicit* empty ``value`` clears the target (needed
to unset a boolean flag); a ``value`` that was never set (``None``) writes nothing.
The shared ``only_if_empty`` toggle still applies (skip notes whose target is
already populated). Reading no input alias, it applies to every note in the deck.
"""

from ..client import BackendClient
from ..config import ALIASES
from .base import ONLY_IF_EMPTY, FieldOperation, IOSpec, ParamSpec


class SetFieldOperation(FieldOperation):
    key = "set-field"
    label = "Set field"
    description = (
        "Writes a fixed literal value into a chosen field. Purely local (no "
        "backend call); useful for stamping a constant onto every note in the "
        "deck."
    )
    # No static input/output aliases: the target is param-driven (see io_spec), and
    # the op reads no field so it applies to every note.
    params_spec = (
        ParamSpec(
            "target",
            "Target field",
            "choice",
            choices=ALIASES,
            description="The field to write the value into.",
        ),
        ParamSpec(
            "value",
            "Value",
            "text",
            description="The literal value to set. Leave empty to clear the field.",
        ),
        ONLY_IF_EMPTY,
    )

    def io_spec(self, params: dict | None = None) -> IOSpec:
        target = (params or {}).get("target")
        return IOSpec(outputs=(target,) if target else ())

    def io_display(self, params: dict | None = None) -> str:
        params = params or {}
        target = params.get("target")
        out = "{" + target + "}" if target else "{}"
        value = params.get("value")
        literal = "(unset)" if value is None else f'"{value}"'
        return f"{out} ← {literal}"

    def compute(
        self, client: BackendClient, sources: list[dict[str, str]], params: dict | None = None
    ) -> list[str | None]:
        value = (params or {}).get("value")
        # An unconfigured value (never set) writes nothing; an explicit "" clears.
        return [value] * len(sources)
