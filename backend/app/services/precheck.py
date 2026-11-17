"""推荐策略发布预检业务规则：策略库复用、场景命中裁决与上线闭环。

预检是新增推荐能力上线前的独立关口：读推荐场景配置 + 策略库已发布策略，
按首次接入口径取策略库记录，算出唯一场景命中结果，再登记成预检明细数据集。
裁决口径固定为「优先级升序 → 更早发布 → 策略编号」，不按评分临时改判，
避免同一场景出现两个可用动作。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store
from app.services.tacticlib import TacticlibService

MODULE = "precheck"
RECOMMEND_MODULE = "recommend"
TACTIC_MODULE = "tacticlib"

CONCLUSION_PASS = "通过"
CONCLUSION_CANDIDATE = "候选"
CONCLUSION_FAIL = "未通过"
CLOSED = "已闭环"
OPEN = "未闭环"

DECISION_RULE = "优先级升序 → 更早发布 → 策略编号字典序"
CANDIDATE_STATUSES = {"草稿", "策略评审中"}
ONLINE_STATUS = "已上线"
PUBLISHED_STATUS = "已发布"

tactic_service = TacticlibService()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _next_batch() -> str:
    """业务批次号：同日按已有预检/上线批次顺延，保证每个动作都能追到具体批次。"""
    prefix = f"BATCH-{_today()}-"
    sequences = [
        _int(_text(row.get(field))[-4:])
        for row in store.rows(MODULE)
        for field in ("预检批次", "上线批次")
        if _text(row.get(field)).startswith(prefix)
    ]
    return f"{prefix}{max(sequences, default=0) + 1:04d}"


class PrecheckService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        conclusion: str | None = None,
        scenario: str | None = None,
        batch: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(MODULE))
        if keyword:
            rows = [
                row for row in rows
                if keyword in _text(row.get("推荐策略编号"))
                or keyword in _text(row.get("数据集编号"))
                or keyword in _text(row.get("命中策略编号"))
            ]
        if conclusion:
            rows = [row for row in rows if row.get("预检结论") == conclusion]
        if scenario:
            rows = [row for row in rows if scenario in _text(row.get("推荐场景"))]
        if batch:
            rows = [
                row for row in rows
                if row.get("业务批次") == batch or row.get("预检批次") == batch
            ]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def launchable(self) -> list[dict[str, Any]]:
        """上线列表：只有预检通过且尚未闭环的数据集才允许出现在这里。"""
        return [row for row in store.rows(MODULE) if row.get("是否进入上线列表")]

    def pending_for_tacticlib(self) -> list[dict[str, Any]]:
        """登记到策略库待处理明细的预检数据集，未闭环的排在前面。"""
        rows = list(store.rows(MODULE))
        rows.sort(key=lambda row: (row.get("闭环状态") == CLOSED, _int(row.get("id"))))
        return rows

    def _tactic(self, tactic_no: str) -> dict[str, Any] | None:
        return next(
            (row for row in store.rows(TACTIC_MODULE) if _text(row.get("策略编号")) == tactic_no),
            None,
        )

    def _published_for(self, scenario: str) -> list[dict[str, Any]]:
        return [
            row for row in store.rows(TACTIC_MODULE)
            if row.get("status") == PUBLISHED_STATUS and _text(row.get("适用场景")) == scenario
        ]

    def _choose(self, scenario: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any] | None]:
        """返回场景唯一命中策略、同优先级候选、按评分口径的备选命中。"""
        tactics = self._published_for(scenario)
        if not tactics:
            return None, [], None
        ordered = sorted(
            tactics,
            key=lambda row: (
                _int(row.get("优先级"), 99),
                _text(row.get("发布时间")) or "9999-12-31",
                _text(row.get("策略编号")),
            ),
        )
        winner = ordered[0]
        top_priority = _int(winner.get("优先级"), 99)
        tied = [row for row in ordered if _int(row.get("优先级"), 99) == top_priority]
        by_score = sorted(
            tied,
            key=lambda row: (
                -(_float(row.get("策略评分")) or 0.0),
                _text(row.get("发布时间")) or "9999-12-31",
                _text(row.get("策略编号")),
            ),
        )[0]
        return winner, tied, by_score

    def _by_strategy(self, strategy_id: int) -> dict[str, Any] | None:
        return next(
            (row for row in store.rows(MODULE) if _int(row.get("推荐策略ID")) == strategy_id),
            None,
        )

    def _compose(self, strategy: dict[str, Any], batch: str) -> dict[str, Any]:
        scenario = _text(strategy.get("推荐场景"))
        status = _text(strategy.get("status"))
        declared = _text(strategy.get("复用策略编号"))
        weight_raw = strategy.get("多样性权重")
        weight = _float(weight_raw)
        weight_ok = weight is not None and 0.0 <= weight <= 1.0
        winner, tied, by_score = self._choose(scenario)
        winner_no = _text(winner.get("策略编号")) if winner else ""
        declared_exists = self._tactic(declared) is not None if declared else False
        online_elsewhere = [
            row for row in store.rows(RECOMMEND_MODULE)
            if _text(row.get("推荐场景")) == scenario
            and row.get("status") == ONLINE_STATUS
            and _int(row.get("id")) != _int(strategy.get("id"))
        ]
        hit = bool(winner and declared and declared == winner_no)

        candidate = status in CANDIDATE_STATUSES
        reason: list[str] = []
        if candidate:
            conclusion = CONCLUSION_CANDIDATE
            reason.append("推荐策略仍在评审流程中，只登记为候选，不进入上线列表")
        else:
            if not weight_ok:
                conclusion = CONCLUSION_FAIL
                reason.append(f"多样性权重「{_text(weight_raw) or '未配置'}」不在 0~1 范围内")
            elif winner is None:
                conclusion = CONCLUSION_FAIL
                reason.append(f"场景归属未通过：场景「{scenario}」没有已发布运营策略覆盖")
            elif not declared:
                conclusion = CONCLUSION_FAIL
                reason.append("未声明复用的运营策略编号")
            elif not declared_exists:
                conclusion = CONCLUSION_FAIL
                reason.append(f"复用的运营策略「{declared}」不存在")
            elif declared != winner_no:
                conclusion = CONCLUSION_FAIL
                reason.append(
                    f"复用策略与场景裁决不一致：声明 {declared}，场景唯一命中 {winner_no}"
                )
            elif online_elsewhere:
                conclusion = CONCLUSION_FAIL
                reason.append(
                    f"场景「{scenario}」已有上线动作来源 {online_elsewhere[0].get('策略编号')}，同一场景只允许一个"
                )
            else:
                conclusion = CONCLUSION_PASS

        usage = _int(winner.get("使用次数")) if winner else 0
        expected_usage = usage + 1 if conclusion == CONCLUSION_PASS else usage

        if len(tied) > 1 and by_score is not None:
            by_score_no = _text(by_score.get("策略编号"))
            if by_score_no != winner_no:
                alternative = (
                    f"同优先级按更早发布命中 {winner_no}；若改按更高策略评分裁决将命中 "
                    f"{by_score_no}（评分 {_text(by_score.get('策略评分'))} 对 "
                    f"{_text(winner.get('策略评分'))}），推荐结果与复用次数会随之改变"
                )
            else:
                alternative = f"同优先级候选 {len(tied)} 项，按更早发布与按更高评分裁决结果一致"
        else:
            alternative = "无同优先级候选，无需裁决"

        missed = (
            "、".join(
                _text(row.get("策略编号")) for row in tied
                if _text(row.get("策略编号")) != winner_no
            )
            if winner else ""
        )
        result_text = (
            f"预计推荐 {_int(strategy.get('推荐条数上限'))} 条"
            f" · 排序模型 {_text(strategy.get('排序模型')) or '未配置'}"
            f" · 多样性权重 {_text(weight_raw) or '未配置'}"
            f" · 场景评分 {_text(strategy.get('场景评分')) or '未配置'}"
        )
        snapshot = "|".join([
            _text(strategy.get("策略编号")),
            scenario,
            _text(strategy.get("排序模型")),
            _text(weight_raw),
            _text(strategy.get("推荐条数上限")),
            winner_no,
            _text(usage),
        ])
        read_mode = (
            f"按首次接入批次 {_text(winner.get('首次接入批次')) or '未登记'} 读取策略库记录"
            if winner else "无可用策略库记录"
        )

        return {
            "status": conclusion,
            "pending": conclusion == CONCLUSION_PASS,
            "abnormal": conclusion == CONCLUSION_FAIL,
            "推荐策略ID": _int(strategy.get("id")),
            "推荐策略编号": _text(strategy.get("策略编号")),
            "推荐场景": scenario,
            "推荐策略状态": status,
            "场景评分": strategy.get("场景评分"),
            "预检结论": conclusion,
            "场景命中结果": "命中" if hit else "未命中",
            "场景归属": (
                f"已归属 {winner_no}" if winner
                else f"未归属（场景「{scenario}」没有已发布运营策略）"
            ),
            "命中策略编号": winner_no,
            "命中策略名称": _text(winner.get("策略名称")) if winner else "",
            "命中策略优先级": winner.get("优先级") if winner else "",
            "命中策略评分": winner.get("策略评分") if winner else "",
            "策略读取口径": read_mode,
            "策略库首次接入批次": _text(winner.get("首次接入批次")) if winner else "",
            "策略库首次接入时间": _text(winner.get("首次接入时间")) if winner else "",
            "策略复用次数": usage,
            "预计复用次数": expected_usage,
            "多样性权重": weight_raw,
            "排序模型": _text(strategy.get("排序模型")),
            "推荐条数上限": strategy.get("推荐条数上限"),
            "预计推荐结果": result_text,
            "同优先级候选": "、".join(_text(row.get("策略编号")) for row in tied),
            "同优先级候选数": len(tied),
            "裁决口径": DECISION_RULE,
            "备选裁决差异": alternative,
            "未命中策略": missed,
            "预检说明": "；".join(reason) or "场景归属与策略评审均通过，允许上线",
            "是否允许上线": conclusion == CONCLUSION_PASS,
            "是否进入上线列表": conclusion == CONCLUSION_PASS,
            "闭环状态": OPEN,
            "当前动作来源": winner_no,
            "业务批次": batch,
            "预检批次": batch,
            "批次资料快照": snapshot,
            "上线时间": "",
            "上线批次": "",
        }

    def register(
        self,
        strategy_id: int,
        *,
        operator: str = "值班管理员",
        requested_batch: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        strategy = store.find(RECOMMEND_MODULE, strategy_id)
        if strategy is None:
            return None, f"推荐策略 {strategy_id} 不存在或已归档"
        status = _text(strategy.get("status"))
        if status == ONLINE_STATUS:
            existing = self._by_strategy(strategy_id)
            if existing is not None:
                return existing, "推荐策略已上线且预检已闭环，重复登记不新增数据集"
            return None, "推荐策略已上线，没有可登记的发布预检"
        if status == "已下线":
            return None, "推荐策略已下线，不能再登记发布预检"

        with store.transaction():
            existing = self._by_strategy(strategy_id)
            if existing is not None and existing.get("闭环状态") == CLOSED:
                return existing, "该推荐策略的发布预检已闭环，重复登记不新增数据集"
            # 重复登记沿用原批次，保证预检结果始终能追到同一个业务批次。
            batch = (
                _text(requested_batch)
                or (_text(existing.get("业务批次")) if existing is not None else "")
                or _next_batch()
            )
            fields = self._compose(strategy, batch)
            conclusion = _text(fields.get("预检结论"))
            if existing is None:
                entry_id = max((_int(row.get("id")) for row in store.rows(MODULE)), default=0) + 1
                row = {"id": entry_id, "数据集编号": f"PREC-{entry_id:04d}"}
                row.update(fields)
                row["登记时间"] = _now()
                row["操作人"] = operator
                store.rows(MODULE).append(row)
                message = "推荐策略发布预检明细数据集已登记"
            else:
                row = existing
                row.update(fields)
                row["登记时间"] = _now()
                row["操作人"] = operator
                message = "重复登记已收敛为同一预检明细数据集，未新增记录"

            # 与预检结果同一次提交里回写推荐策略状态，避免出现预检通过但状态未同步。
            strategy["预检结论"] = conclusion
            strategy["最近预检批次"] = batch
            if conclusion == CONCLUSION_PASS:
                strategy["status"] = "预检通过"
                strategy["pending"] = True
                strategy["abnormal"] = False
            elif conclusion == CONCLUSION_FAIL:
                if _text(strategy.get("status")) == "预检通过":
                    strategy["status"] = "评审通过"
                strategy["pending"] = True
                strategy["abnormal"] = True
            else:
                strategy["pending"] = True
            return row, message

    def launch_for_strategy(self, strategy_id: int, *, operator: str) -> tuple[dict[str, Any] | None, str]:
        row = self._by_strategy(strategy_id)
        if row is None:
            return None, "推荐策略还没有发布预检明细数据集，请先执行策略复用预检"
        return self.launch(_int(row.get("id")), operator=operator)

    def launch(self, precheck_id: int, *, operator: str) -> tuple[dict[str, Any] | None, str]:
        row = store.find(MODULE, precheck_id)
        if row is None:
            return None, f"预检明细数据集 {precheck_id} 不存在"
        if row.get("闭环状态") == CLOSED:
            return row, "该预检明细数据集已闭环，上线动作不重复计数"
        if row.get("预检结论") != CONCLUSION_PASS or not row.get("是否进入上线列表"):
            return None, (
                f"预检结论为「{row.get('预检结论')}」，未通过场景归属与策略评审校验，"
                "不能进入上线列表"
            )

        with store.transaction():
            strategy = store.find(RECOMMEND_MODULE, _int(row.get("推荐策略ID")))
            if strategy is None:
                return None, "关联的推荐策略不存在或已归档"
            # 进入写事务后重新确认闭环状态：并发提交时只有第一个请求能拿到上线权。
            if row.get("闭环状态") != OPEN:
                return row, "该预检明细数据集已闭环，上线动作不重复计数"
            scenario = _text(row.get("推荐场景"))
            winner, _, _ = self._choose(scenario)
            batch = _next_batch()
            blocker = ""
            if _text(strategy.get("status")) != "预检通过":
                blocker = f"推荐策略状态为「{_text(strategy.get('status'))}」，未处于预检通过状态"
            elif winner is None:
                blocker = f"场景「{scenario}」已无已发布运营策略，场景归属失效"
            elif _text(winner.get("策略编号")) != _text(row.get("命中策略编号")):
                blocker = (
                    f"场景裁决已变化：当前唯一命中 {_text(winner.get('策略编号'))}，"
                    f"与原预检 {_text(row.get('命中策略编号'))} 不一致"
                )
            else:
                others = [
                    item for item in store.rows(RECOMMEND_MODULE)
                    if _text(item.get("推荐场景")) == scenario
                    and item.get("status") == ONLINE_STATUS
                    and _int(item.get("id")) != _int(strategy.get("id"))
                ]
                if others:
                    blocker = (
                        f"场景「{scenario}」已有上线动作来源 {others[0].get('策略编号')}，"
                        "同一场景只能保留一个来源"
                    )

            if blocker:
                # 上线失败也属于预检结论的一部分，同样与推荐策略状态一起落库；
                # 原业务批次保留，阻断批次单独记录，追溯链不断。
                row.update({
                    "status": CONCLUSION_FAIL,
                    "预检结论": CONCLUSION_FAIL,
                    "abnormal": True,
                    "pending": True,
                    "是否允许上线": False,
                    "是否进入上线列表": False,
                    "闭环状态": OPEN,
                    "预检说明": f"上线阻断：{blocker}",
                    "上线批次": batch,
                    "上线时间": _now(),
                })
                strategy["预检结论"] = CONCLUSION_FAIL
                if _text(strategy.get("status")) == "预检通过":
                    strategy["status"] = "评审通过"
                strategy["abnormal"] = True
                return row, f"上线失败：{blocker}"

            tactic_no = _text(winner.get("策略编号"))
            usage_after = _int(winner.get("使用次数")) + 1
            row.update({
                "闭环状态": CLOSED,
                "是否进入上线列表": False,
                "pending": False,
                "abnormal": False,
                "策略复用次数": usage_after,
                "预计复用次数": usage_after,
                "预检说明": (
                    f"预检通过并已上线；场景「{scenario}」当前动作来源为 {tactic_no}"
                ),
                "上线时间": _now(),
                "上线批次": batch,
            })
            strategy.update({
                "status": ONLINE_STATUS,
                "pending": False,
                "abnormal": False,
                "预检结论": CONCLUSION_PASS,
                "复用策略编号": tactic_no,
                "推荐动作次数": _int(strategy.get("推荐动作次数")) + 1,
                "最近执行批次": batch,
                "最近执行时间": _now(),
            })
            tactic_service.bump_usage(tactic_no, batch, _now())
            return row, f"推荐策略已上线，场景唯一动作来源为 {tactic_no}，复用次数已回写策略库"

    def execute_recommendation(self, strategy_id: int, *, operator: str) -> tuple[dict[str, Any] | None, str]:
        """实际推荐动作：只有真正执行推荐时才让复用次数增长。"""
        strategy = store.find(RECOMMEND_MODULE, strategy_id)
        if strategy is None:
            return None, f"推荐策略 {strategy_id} 不存在或已归档"
        if _text(strategy.get("status")) != ONLINE_STATUS:
            return None, "只有已上线的推荐策略可以执行推荐动作"
        tactic_no = _text(strategy.get("复用策略编号"))
        tactic = self._tactic(tactic_no)
        if tactic is None:
            return None, f"关联的运营策略「{tactic_no}」不存在，无法回写复用次数"

        with store.transaction():
            batch = _next_batch()
            strategy["推荐动作次数"] = _int(strategy.get("推荐动作次数")) + 1
            strategy["最近执行批次"] = batch
            strategy["最近执行时间"] = _now()
            tactic_service.bump_usage(tactic_no, batch, _now())
            closed = self._by_strategy(strategy_id)
            if closed is not None:
                closed["策略复用次数"] = _int(tactic.get("使用次数"))
            return strategy, (
                f"推荐动作已执行，{tactic_no} 复用次数回写为 {_int(tactic.get('使用次数'))}"
            )
