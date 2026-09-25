"""双版本对勘：两份拼接稿的全局逐字最小编辑对齐与差异块汇总。

提交两组与 :func:`app.assembler.assemble` 相同的有序 segments
（``left_segments`` / ``right_segments``，沿用段数/长度限制与续接失败
规则），分别拼接得到左、右两份拼接稿，再对两份拼接稿做**全局**逐字
最小编辑对齐（两稿均须完全消耗）：

- 相同字、或任一侧为 ``?``（未辨认字）的字符对代价 0；
- 替换（双方均为已知且不同）、插入、删除各代价 1。

同分路径按**对角（字符对）→ 删除左字 → 插入右字**的固定顺序择优；
同时统计取得最小代价的路径条数（多于一条即标记歧义，计数到 2 即止）。

对齐后把**连续非零代价列**合并为差异块：每块给出两侧左闭右开区间、
原文片段与逐字 sources 及块内代价；两稿逐字相容（无非零代价列）时
差异块为空。

本模块只做对勘比较，绝不改写任一侧拼接稿。
"""

from __future__ import annotations

from .aligner import WILDCARD
from .assembler import AssemblyError, assemble


class EditionAssemblyError(ValueError):
    """某一侧的 segments 无法完成拼接（沿用 /api/assemble 的续接门槛）。"""

    def __init__(self, side: str, cause: AssemblyError):
        self.side = side
        self.failed_segment = cause.failed_segment
        label = "左" if side == "left" else "右"
        super().__init__(f"{label}侧拼接失败：{cause}")


def _pair_cost(a: str, b: str) -> int:
    """单对字符的代价：相同字或任一侧为 ``?`` 代价 0，否则替换代价 1。"""
    if a == WILDCARD or b == WILDCARD:
        return 0
    return 0 if a == b else 1


def _align_global(
    left: str, right: str
) -> tuple[list[tuple[int | None, int | None, int]], int, bool]:
    """对两稿做全局最小编辑对齐。

    返回 ``(columns, total_cost, ambiguous)``：``columns`` 为按“对角 →
    删除左字 → 插入右字”择优回溯出的逐列对齐，每列 ``(左下标或 None,
    右下标或 None, 本列代价)``；``ambiguous`` 标记最小代价路径是否多
    于一条。
    """
    m, n = len(left), len(right)
    # dp[i][j]：左稿前 i 字与右稿前 j 字对齐的最小代价；
    # ways[i][j]：取得该最小代价的路径条数（多于 1 条即记 2，只辨歧义）。
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    ways = [[0] * (n + 1) for _ in range(m + 1)]
    ways[0][0] = 1
    for i in range(1, m + 1):
        dp[i][0] = i            # 左稿前 i 字全部删除
        ways[i][0] = 1
    for j in range(1, n + 1):
        dp[0][j] = j            # 右稿前 j 字全部插入
        ways[0][j] = 1
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cand = (
                dp[i - 1][j - 1] + _pair_cost(left[i - 1], right[j - 1]),  # 对角
                dp[i - 1][j] + 1,   # 删除左字
                dp[i][j - 1] + 1,   # 插入右字
            )
            best = min(cand)
            dp[i][j] = best
            w = 0
            for c, prev_w in zip(
                cand, (ways[i - 1][j - 1], ways[i - 1][j], ways[i][j - 1])
            ):
                if c == best:
                    w += prev_w
                    if w > 1:       # 只关心是否多于一条
                        w = 2
                        break
            ways[i][j] = w

    # 回溯：同分按 对角 → 删除左字 → 插入右字 固定择优
    columns: list[tuple[int | None, int | None, int]] = []
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            pc = _pair_cost(left[i - 1], right[j - 1])
            if dp[i][j] == dp[i - 1][j - 1] + pc:
                columns.append((i - 1, j - 1, pc))
                i, j = i - 1, j - 1
                continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            columns.append((i - 1, None, 1))
            i -= 1
        else:
            columns.append((None, j - 1, 1))
            j -= 1
    columns.reverse()
    return columns, dp[m][n], ways[m][n] > 1


def _merge_blocks(
    columns: list[tuple[int | None, int | None, int]],
    left_text: str,
    right_text: str,
    left_sources: list[list[dict]],
    right_sources: list[list[dict]],
) -> list[dict]:
    """把连续非零代价列合并为差异块。

    每块给出两侧左闭右开区间、原文片段、逐字 sources 与块内代价；
    纯插入/纯删除块的一侧区间为空（``start == end``）。
    """
    blocks: list[dict] = []
    li = ri = 0                 # 当前列之前已消耗的左/右字数
    open_block: dict | None = None

    def close() -> None:
        nonlocal open_block
        if open_block is None:
            return
        ls, rs = open_block["ls"], open_block["rs"]
        blocks.append({
            "left": {
                "start": ls,
                "end": li,
                "fragment": left_text[ls:li],
                "sources": [list(s) for s in left_sources[ls:li]],
            },
            "right": {
                "start": rs,
                "end": ri,
                "fragment": right_text[rs:ri],
                "sources": [list(s) for s in right_sources[rs:ri]],
            },
            "cost": open_block["cost"],
        })
        open_block = None

    for lp, rp, cost in columns:
        if cost == 0:
            close()
        else:
            if open_block is None:
                open_block = {"ls": li, "rs": ri, "cost": 0}
            open_block["cost"] += cost
        if lp is not None:
            li += 1
        if rp is not None:
            ri += 1
    close()
    return blocks


def compare_editions(left_segments: list[str], right_segments: list[str]) -> dict:
    """对两份拼接稿做全局逐字对勘。

    返回 ``{"left_text", "right_text", "total_cost", "ambiguous",
    "blocks"}``；任一侧拼接失败抛出 :class:`EditionAssemblyError`
    （``side`` 为 ``"left"`` / ``"right"``，``failed_segment`` 为该侧
    失败段序号，从 0 开始）。
    """
    try:
        left_result = assemble(left_segments)
    except AssemblyError as exc:
        raise EditionAssemblyError("left", exc) from exc
    try:
        right_result = assemble(right_segments)
    except AssemblyError as exc:
        raise EditionAssemblyError("right", exc) from exc

    left_text, left_sources = left_result["text"], left_result["sources"]
    right_text, right_sources = right_result["text"], right_result["sources"]

    columns, total_cost, ambiguous = _align_global(left_text, right_text)
    blocks = _merge_blocks(
        columns, left_text, right_text, left_sources, right_sources
    )
    return {
        "left_text": left_text,
        "right_text": right_text,
        "total_cost": total_cost,
        "ambiguous": ambiguous,
        "blocks": blocks,
    }
