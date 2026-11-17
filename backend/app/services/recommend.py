"""智能推荐业务规则：状态流转、字段校验与筛选口径都收在这里。

上线动作不在这里直接改状态：它必须先经过策略复用预检，由预检把
「预检结论 + 推荐策略状态 + 策略库复用次数」放在同一次写入里完成。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "recommend"
REQUIRED_FIELDS = ["策略编号", "推荐场景", "召回算法"]
STATUS_ORDER = ["草稿", "策略评审中", "评审通过", "预检通过", "已上线", "已下线"]
ACTION_RULES = {"提交策略评审": "策略评审中", "评审通过策略": "评审通过", "下线策略": "已下线"}
NEGATIVE_ACTIONS = ["下线策略"]
# 评审流程没走完的策略只能登记为候选，不能进入上线列表。
CANDIDATE_STATUSES = {"草稿", "策略评审中"}
ONLINE_ACTION = "上线策略"
OPTIONAL_NUMERIC_FIELDS = ["多样性权重", "推荐条数上限", "场景评分"]


class RecommendService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("策略编号", ""))
                or keyword in str(row.get("推荐场景", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in ["排序模型", "冷启动策略", "刷新频率", "复用策略编号"]:
            entry[field] = str(values.get(field) or "").strip()
        for field in OPTIONAL_NUMERIC_FIELDS:
            entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["推荐动作次数"] = 0
        entry["最近执行批次"] = ""
        entry["最近执行时间"] = ""
        entry["预检结论"] = ""
        entry["最近预检批次"] = ""
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"推荐策略 {entry_id} 不存在或已归档"
        if action == ONLINE_ACTION:
            return None, "上线策略必须走推荐策略发布预检，请在预检明细数据集上执行上线"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于智能推荐可执行范围"
        target = ACTION_RULES[action]
        if entry.get("status") == "已上线":
            return None, "推荐策略已上线，请先下线再变更评审状态"
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"推荐策略已{action}"
