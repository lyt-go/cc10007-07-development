"""推荐策略发布预检接口：新增推荐能力上线前，先按策略库记录算场景命中结果。

三条入口分别对应：
- 智能推荐动作回写：precheck/register 与 precheck/launch（TACT-0003 契约样本走这条）；
- 策略库待处理明细：tacticlib/pending；
- 预检数据集与批次追溯：precheck 列表与 precheck/batches。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.permissions import Operator, current_operator, require_write
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.precheck import CONCLUSION_FAIL, PrecheckService

router = APIRouter(prefix="/api/precheck", tags=["推荐策略发布预检"])

service = PrecheckService()

@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按数据集编号、推荐策略编号或命中策略编号检索"),
    conclusion: str | None = Query(default=None, description="通过、候选、未通过"),
    scenario: str | None = Query(default=None, description="按推荐场景检索"),
    batch: str | None = Query(default=None, description="按业务批次或预检批次检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """读取预检明细数据集；列表本身就是承接新能力的推荐策略发布预检明细数据集。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, conclusion=conclusion, scenario=scenario, batch=batch, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/launchable", response_model=dict)
def list_launchable() -> dict[str, Any]:
    """上线列表：只包含预检通过且未闭环的数据集，评审中的候选不会出现在这里。"""
    items = service.launchable()
    return {"items": items, "total": len(items)}


@router.get("/batches", response_model=dict)
def list_batches() -> dict[str, Any]:
    """按批次汇总预检结果，保证新增推荐发布前的策略库复用预检可从数据批次追溯。"""
    groups: dict[str, dict[str, Any]] = {}
    for row in service.pending_for_tacticlib():
        batch = str(row.get("业务批次") or "未登记批次")
        group = groups.setdefault(
            batch,
            {
                "业务批次": batch,
                "预检批次": row.get("预检批次"),
                "数据集数": 0,
                "通过": 0,
                "候选": 0,
                "未通过": 0,
                "已闭环": 0,
                "数据集编号": [],
            },
        )
        group["数据集数"] += 1
        conclusion = str(row.get("预检结论"))
        if conclusion in ("通过", "候选", "未通过"):
            group[conclusion] += 1
        if row.get("闭环状态") == "已闭环":
            group["已闭环"] += 1
        group["数据集编号"].append(row.get("数据集编号"))
    items = sorted(groups.values(), key=lambda item: str(item.get("业务批次")), reverse=True)
    return {"items": items, "total": len(items)}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条预检明细；核对场景命中结果、复用次数与预计推荐结果都看同一条记录。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"预检明细数据集 {entry_id} 不存在")
    return entry


@router.post("/register", response_model=ActionResult)
def register(payload: EntryPayload, operator: Operator = Depends(current_operator)) -> ActionResult:
    """对新增推荐能力执行策略复用预检并登记明细数据集。

    推荐策略仍在评审中时只登记为候选；重复登记收敛为同一个数据集。
    """
    require_write(operator)
    strategy_id = _strategy_id(payload.merged())
    if strategy_id is None:
        return ActionResult(ok=False, message="缺少推荐策略ID，无法执行策略复用预检")
    entry, message = service.register(
        strategy_id,
        operator=operator.name,
        requested_batch=payload.merged().get("batch"),
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=entry.get("预检结论") != CONCLUSION_FAIL, message=message, entry=entry)


@router.post("/{entry_id}/launch", response_model=ActionResult)
def launch(
    entry_id: int, payload: EntryPayload, operator: Operator = Depends(current_operator)
) -> ActionResult:
    """在预检明细数据集上执行上线：预检结果、推荐策略状态与复用次数同一次写入。"""
    require_write(operator)
    entry, message = service.launch(entry_id, operator=operator.name)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(
        ok=entry.get("预检结论") != CONCLUSION_FAIL, message=message, entry=entry
    )


@router.post("/execute", response_model=ActionResult)
def execute(payload: EntryPayload, operator: Operator = Depends(current_operator)) -> ActionResult:
    """执行一次实际推荐动作，用于验证复用次数只随真实推荐动作增长。"""
    require_write(operator)
    strategy_id = _strategy_id(payload.merged())
    if strategy_id is None:
        return ActionResult(ok=False, message="缺少推荐策略ID，无法执行推荐动作")
    entry, message = service.execute_recommendation(
        strategy_id, operator=operator.name
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


def _strategy_id(values: dict[str, Any]) -> int | None:
    raw = values.get("strategy_id") or values.get("推荐策略ID")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
