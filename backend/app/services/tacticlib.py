"""策略库业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "tacticlib"
REQUIRED_FIELDS = ["策略编号", "策略名称", "策略类型"]
STATUS_ORDER = ["草稿", "策略评审中", "已发布", "已退役"]
ACTION_RULES = {"提交策略评审": "策略评审中", "发布策略": "已发布", "退役策略": "已退役"}
NEGATIVE_ACTIONS = []


class TacticlibService:
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
            rows = [row for row in rows if keyword in str(row.get("策略编号", ""))]
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
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["使用次数"] = 0
        entry["适用场景"] = str(values.get("适用场景") or "").strip()
        entry["优先级"] = values.get("优先级") or 99
        entry["策略评分"] = values.get("策略评分") or 0
        entry["发布时间"] = ""
        entry["首次接入批次"] = ""
        entry["首次接入时间"] = ""
        entry["策略来源"] = "人工登记"
        entry["最近使用批次"] = ""
        self._attach_pending(entry)
        rows.append(entry)
        return entry, []

    def _attach_pending(self, entry: dict[str, Any]) -> None:
        """策略一旦发布就挂到运营策略库待处理明细里，供预检按首次接入读取。"""
        if entry.get("status") != "已发布":
            return
        from datetime import datetime

        now = datetime.now().replace(microsecond=0).isoformat()
        if not entry.get("发布时间"):
            entry["发布时间"] = now
        if not entry.get("首次接入批次"):
            batch = f"BATCH-{datetime.now().strftime('%Y%m%d')}-0001"
            entry["首次接入批次"] = batch
        if not entry.get("首次接入时间"):
            entry["首次接入时间"] = now
        entry["策略记录"] = (
            f"首次接入 {entry.get('首次接入批次')} · 适用场景 "
            f"{entry.get('适用场景') or '未登记'} · 优先级 {entry.get('优先级')}"
        )

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"运营策略 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于策略库可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        self._attach_pending(entry)
        return entry, f"运营策略已{action}"

    def bump_usage(self, tactic_no: str, batch: str, moment: str) -> None:
        """复用次数只随实际推荐动作增长，并落最近一次使用批次便于追溯。"""
        entry = next(
            (row for row in store.rows(MODULE) if str(row.get("策略编号")) == tactic_no),
            None,
        )
        if entry is None:
            return
        try:
            usage = int(float(entry.get("使用次数") or 0))
        except (TypeError, ValueError):
            usage = 0
        entry["使用次数"] = usage + 1
        entry["最近使用批次"] = batch
        entry["最近使用时间"] = moment
