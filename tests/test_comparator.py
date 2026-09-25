"""双版本对勘（compare_editions）测试。"""

import pytest

from app.assembler import assemble
from app.comparator import (
    EditionAssemblyError,
    _align_global,
    compare_editions,
)

LEFT_SEGS = ["学而?习之", "时习之不", "之不亦乐乎"]
# 左稿：学而时习之不亦乐乎（9 字）
LEFT_TEXT = "学而时习之不亦乐乎"


def _right_segs(tail: str) -> list[str]:
    """构造右稿 segments：前段与左稿相同，末段尾部替换为 ``tail``。"""
    return ["学而?习之", "时习之不", "之不亦" + tail]


def test_assemble_fixtures():
    assert assemble(LEFT_SEGS)["text"] == LEFT_TEXT
    assert assemble(_right_segs("说乎"))["text"] == "学而时习之不亦说乎"
    assert assemble(_right_segs("X乐乎"))["text"] == "学而时习之不亦X乐乎"
    assert assemble(_right_segs("乎"))["text"] == "学而时习之不亦乎"
    assert assemble(_right_segs("说焉"))["text"] == "学而时习之不亦说焉"
    assert assemble(_right_segs("XYZ"))["text"] == "学而时习之不亦XYZ"


def test_identical_editions_have_no_blocks():
    r = compare_editions(LEFT_SEGS, LEFT_SEGS)
    assert r["left_text"] == r["right_text"] == LEFT_TEXT
    assert r["total_cost"] == 0
    assert r["ambiguous"] is False
    assert r["blocks"] == []


def test_single_substitution_block():
    r = compare_editions(LEFT_SEGS, _right_segs("说乎"))
    assert r["total_cost"] == 1
    assert r["ambiguous"] is False
    assert len(r["blocks"]) == 1
    block = r["blocks"][0]
    assert block["cost"] == 1
    assert (block["left"]["start"], block["left"]["end"]) == (7, 8)
    assert (block["right"]["start"], block["right"]["end"]) == (7, 8)
    assert block["left"]["fragment"] == "乐"
    assert block["right"]["fragment"] == "说"
    # 逐字 sources 与 /api/assemble 对应区间一致
    assert block["left"]["sources"] == assemble(LEFT_SEGS)["sources"][7:8]
    assert block["right"]["sources"] == assemble(_right_segs("说乎"))["sources"][7:8]


def test_insertion_block_has_empty_left_interval():
    r = compare_editions(LEFT_SEGS, _right_segs("X乐乎"))
    assert r["total_cost"] == 1
    assert len(r["blocks"]) == 1
    block = r["blocks"][0]
    assert (block["left"]["start"], block["left"]["end"]) == (7, 7)
    assert block["left"]["fragment"] == ""
    assert block["left"]["sources"] == []
    assert (block["right"]["start"], block["right"]["end"]) == (7, 8)
    assert block["right"]["fragment"] == "X"
    assert block["right"]["sources"] == [[{"segment": 2, "pos": 3}]]


def test_deletion_block_has_empty_right_interval():
    r = compare_editions(LEFT_SEGS, _right_segs("乎"))
    assert r["total_cost"] == 1
    assert len(r["blocks"]) == 1
    block = r["blocks"][0]
    assert (block["left"]["start"], block["left"]["end"]) == (7, 8)
    assert block["left"]["fragment"] == "乐"
    assert (block["right"]["start"], block["right"]["end"]) == (7, 7)
    assert block["right"]["fragment"] == ""
    assert block["right"]["sources"] == []


def test_separated_diffs_form_two_blocks():
    # 等长两稿：第 7、9 字（亦→X、乎→Y）两处替换被第 8 字相同字隔开，各自成块
    right_segs = ["学而?习之", "时习之不", "之不X乐Y"]
    assert assemble(right_segs)["text"] == "学而时习之不X乐Y"
    r = compare_editions(LEFT_SEGS, right_segs)
    assert r["total_cost"] == 2
    assert r["ambiguous"] is False
    assert [ (b["left"]["start"], b["left"]["end"]) for b in r["blocks"] ] == [(6, 7), (8, 9)]
    assert [b["left"]["fragment"] for b in r["blocks"]] == ["亦", "乎"]
    assert [b["right"]["fragment"] for b in r["blocks"]] == ["X", "Y"]
    assert [b["cost"] for b in r["blocks"]] == [1, 1]


def test_consecutive_nonzero_columns_merge_into_one_block():
    # 乐乎 / YZ 替换与 X 插入相邻，合成一个差异块
    r = compare_editions(LEFT_SEGS, _right_segs("XYZ"))
    assert r["total_cost"] == 3
    assert len(r["blocks"]) == 1
    block = r["blocks"][0]
    assert (block["left"]["start"], block["left"]["end"]) == (7, 9)
    assert (block["right"]["start"], block["right"]["end"]) == (7, 10)
    assert block["left"]["fragment"] == "乐乎"
    assert block["right"]["fragment"] == "XYZ"
    assert block["cost"] == 3


def test_wildcard_pair_costs_zero_on_either_side():
    # 左稿含 ?（甲乙?丁），右稿对应位置为已知字（丙）：免代价，无差异块
    r = compare_editions(["甲乙?丁", "乙?丁"], ["甲乙丙丁", "乙丙丁"])
    assert r["left_text"] == "甲乙?丁"
    assert r["right_text"] == "甲乙丙丁"
    assert r["total_cost"] == 0
    assert r["blocks"] == []


def test_diagonal_preferred_on_equal_cost():
    # 甲乙 vs 乙甲：同分路径含 替换+替换 / 删+插 等，按对角优先选出两处替换
    columns, total_cost, ambiguous = _align_global("甲乙", "乙甲")
    assert total_cost == 2
    assert ambiguous is True
    assert columns == [(0, 0, 1), (1, 1, 1)]

    r = compare_editions(["甲乙", "甲乙"], ["乙甲", "乙甲"])
    assert r["total_cost"] == 2
    assert r["ambiguous"] is True
    assert len(r["blocks"]) == 1
    block = r["blocks"][0]
    assert block["left"]["fragment"] == "甲乙"
    assert block["right"]["fragment"] == "乙甲"
    assert block["cost"] == 2


def test_delete_left_preferred_over_insert_right():
    # 甲乙甲 vs 乙甲乙：末端同分且对角更劣时，删除左字优先于插入右字
    columns, total_cost, ambiguous = _align_global("甲乙甲", "乙甲乙")
    assert total_cost == 2
    assert ambiguous is True
    assert columns == [
        (None, 0, 1),   # 插入右字 乙
        (0, 1, 0),
        (1, 2, 0),
        (2, None, 1),   # 删除左字 甲（优先于在末尾插入右字 乙）
    ]

    r = compare_editions(
        ["甲乙甲", "乙甲乙", "甲乙甲"],
        ["乙甲乙", "甲乙甲", "乙甲乙"],
    )
    assert r["total_cost"] == 2
    assert r["ambiguous"] is True
    assert [(b["left"]["start"], b["left"]["end"]) for b in r["blocks"]] == [(0, 0), (4, 5)]
    assert [(b["right"]["start"], b["right"]["end"]) for b in r["blocks"]] == [(0, 1), (5, 5)]
    assert [b["left"]["fragment"] for b in r["blocks"]] == ["", "甲"]
    assert [b["right"]["fragment"] for b in r["blocks"]] == ["乙", ""]


def test_ambiguous_flag_only_when_multiple_optimal_paths():
    # 甲乙 vs 甲乙甲乙：插入的 甲乙 可挂多个位置，多条最优路径
    r = compare_editions(["甲乙", "甲乙"], ["甲乙甲", "乙甲乙"])
    assert r["total_cost"] == 2
    assert r["ambiguous"] is True
    # 唯一最优路径：单处替换不歧义
    r = compare_editions(LEFT_SEGS, _right_segs("说乎"))
    assert r["ambiguous"] is False


def test_total_cost_equals_sum_of_block_costs():
    r = compare_editions(LEFT_SEGS, _right_segs("说焉"))
    assert r["total_cost"] == sum(b["cost"] for b in r["blocks"])


def test_left_side_gate_failure_raises_with_side():
    bad = ["孔子曰未知", "未知生焉", "完全无关文本"]
    with pytest.raises(EditionAssemblyError) as exc:
        compare_editions(bad, LEFT_SEGS)
    assert exc.value.side == "left"
    assert exc.value.failed_segment == 2


def test_right_side_gate_failure_raises_with_side():
    bad = ["孔子曰未知", "未知生焉", "完全无关文本"]
    with pytest.raises(EditionAssemblyError) as exc:
        compare_editions(LEFT_SEGS, bad)
    assert exc.value.side == "right"
    assert exc.value.failed_segment == 2
