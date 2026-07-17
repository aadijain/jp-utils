"""Apply queued AI translations to tagged sentence notes.

The add-on half of the async translation flow. A note tagged ``jp::translate``
wants its sentence translated; while tagged, its translation field still holds
the pre-translation content (a native subtitle line, or nothing). One batched
queue lookup answers finished sentences and enqueues first-seen ones - an
out-of-process worker fills the queue on its own schedule, so a pending note
simply stays tagged until a later run. When a translation lands, the wiring
layer writes it over the translation field, renders the learner notes, archives
the replaced content into the misc-info field, and removes the tag.

The backend contract is spoken as plain string/dict literals (the vendored
``shared`` package is not importable inside Anki).
"""

from ..client import BackendClient
from .base import IOSpec, ParamSpec, TranslateOperation
from .nplus1 import strip_markup

# Fixed whitelist tag (see `TranslateOperation.tag`). Deliberately flat -
# a nested `jp::translate::x` child would match `tag:jp::translate` searches.
TRANSLATE_TAG = "jp::translate"

SEND_CONTEXT = ParamSpec(
    "send_context",
    "Send existing text as context",
    "bool",
    default=True,
    description=(
        "Pass the translation field's current content (e.g. a native subtitle line) "
        "to the translator as reference."
    ),
)

PRESERVE_RAW = ParamSpec(
    "preserve_raw",
    "Preserve replaced text in misc info",
    "bool",
    default=True,
    description=(
        "Archive the translation field's previous content into the misc-info field "
        "(as a 'Raw:' line) before overwriting it."
    ),
)


def render_notes(notes: str) -> str:
    """Display-ready HTML for the translator's notes: bullet lines joined by <br>.

    The translator emits plain text, one ``- `` item per line; the deck styles
    note items as ``•`` bullets separated by ``<br>``. Inner dashes (the
    word/gloss separator) are untouched.
    """
    lines = [line.strip() for line in notes.splitlines() if line.strip()]
    return "<br>".join("• " + line[2:] if line.startswith("- ") else line for line in lines)


def append_raw(misc: str, replaced: str) -> str | None:
    """The misc-info value archiving ``replaced``, or ``None`` when there is
    nothing to archive. Appends a ``<b>Raw:</b>`` line, separated from existing
    content by a blank line (bare when the field is empty)."""
    replaced = replaced.strip()
    if not replaced:
        return None
    line = f"<b>Raw:</b> {replaced}"
    return line if not misc.strip() else f"{misc}<br><br>{line}"


class AiTranslateOperation(TranslateOperation):
    key = "ai-translate"
    label = "Translate sentence via AI queue"
    # `sentence` -> the text to translate (REQUIRED). `sentence-meaning` is both
    # optional input (its pre-translation content is the translator's context)
    # and the output the finished translation overwrites.
    input_aliases = ("sentence",)
    optional_input_aliases = ("sentence-meaning",)
    params_spec = (SEND_CONTEXT, PRESERVE_RAW)
    tag = TRANSLATE_TAG

    def io_spec(self, params: dict | None = None) -> IOSpec:
        # misc-info is written (and so mapping-validated) only when the replaced
        # content is being preserved into it.
        outputs = ["sentence-meaning", "notes"]
        if (params or {}).get("preserve_raw", True):
            outputs.append("misc-info")
        return IOSpec(
            required_inputs=self.input_aliases,
            optional_inputs=self.optional_input_aliases,
            outputs=tuple(outputs),
        )

    def translate(
        self,
        client: BackendClient,
        sources: list[dict[str, str]],
        params: dict | None = None,
    ) -> list[dict | None]:
        send_context = bool((params or {}).get("send_context", True))
        queries = []
        for source in sources:
            context = strip_markup(source.get("sentence-meaning", "")).strip()
            queries.append(
                {
                    "sentence": strip_markup(source.get("sentence", "")),
                    "context": context if send_context else "",
                }
            )
        resp = client.post("/v1/translations/lookup", {"queries": queries})
        out: list[dict | None] = []
        for result in resp.get("results", []):
            if result.get("status") == "done" and result.get("translation"):
                out.append(
                    {
                        "translation": result["translation"],
                        "notes": render_notes(result.get("notes", "")),
                    }
                )
            else:
                out.append(None)
        return out
