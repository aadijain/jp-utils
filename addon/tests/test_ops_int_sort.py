"""Tests for the integer-sort operation and the SortOperation ordering."""

from jp_utils.ops import ConfiguredOp, NoteFields, SortOperation, plan_operations
from jp_utils.ops.int_sort import IntSortOperation


def _src(rank):
    return {"rank": rank}


def test_sort_value_parses_int_else_none():
    op = IntSortOperation()
    assert op.sort_value(_src("5157")) == 5157
    assert op.sort_value(_src("  42 ")) == 42  # whitespace tolerated
    assert op.sort_value(_src("")) is None
    assert op.sort_value(_src("n/a")) is None
    assert op.sort_value({}) is None  # alias absent


def test_sort_value_reads_rank_only():
    op = IntSortOperation()
    src = {"rank": "10", "frequency": "3000"}
    assert op.sort_value(src) == 10  # always reads rank
    assert op.sort_value(src, {"field": "frequency"}) == 10  # a stray param is ignored


def test_order_ascending_lowest_first():
    op = IntSortOperation()
    sources = [_src("300"), _src("100"), _src("200")]
    assert op.order(sources) == [1, 2, 0]  # 100, 200, 300


def test_order_descending_highest_first():
    op = IntSortOperation()
    sources = [_src("300"), _src("100"), _src("200")]
    assert op.order(sources, {"direction": "descending"}) == [0, 2, 1]  # 300, 200, 100


def test_order_keeps_keyless_last_in_both_directions():
    op = IntSortOperation()
    sources = [_src(""), _src("50"), _src("bad"), _src("10")]
    assert op.order(sources) == [3, 1, 0, 2]  # 10, 50, then keyless in input order
    # descending: 50, 10, then keyless last
    assert op.order(sources, {"direction": "descending"}) == [1, 3, 0, 2]


def test_order_is_stable_on_ties():
    op = IntSortOperation()
    sources = [_src("10"), _src("10"), _src("5")]
    assert op.order(sources) == [2, 0, 1]  # 5 first; the two 10s keep input order


def test_plan_operations_ignores_sort_ops():
    # A sort op must never reach the field-write path (it writes no field).
    class _NoopSort(SortOperation):
        key = "noop-sort"
        label = "Noop"
        input_aliases = ("rank",)

        def sort_value(self, inputs, params=None):
            return None

    notes = [NoteFields(note_id=1, fields={"rank": "5"})]
    assert plan_operations(None, [ConfiguredOp(_NoopSort())], notes) == []
