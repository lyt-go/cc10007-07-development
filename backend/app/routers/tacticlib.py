"""策略库接口：维护运营策略，覆盖提交策略评审、发布策略、退役策略等动作。

发布后的策略记录会进入「运营策略库待处理明细」，推荐策略发布预检按首次接入批次
读取这些记录；预检上线后回写的复用次数也在这里展示。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.permissions import Operator, current_operator, require_write
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.precheck import PrecheckService
from app.services.tacticlib import TacticlibService

router = APIRouter(prefix="/api/tacticlib", tags=["策略库"])

service = TacticlibService()
precheck_service = PrecheckService()

LIST_FIELDS = [
    "策略编号", "策略名称", "策略类型", "触发条件", "执行动作", "生效周期",
    "策略评分", "使用次数", "适用场景", "优先级", "发布时间", "首次接入批次",
]
STATUSES = ["草稿", "策略评审中", "已发布", "已退役"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按策略编号检索"),
    status: str | None = Query(default=None, description="草稿、策略评审中、已发布、已退役"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按策略编号与状态过滤策略库列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出策略库清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "tacticlib", "total": total, "items": items}


SHARED_FIELDS = [
    "数据集编号", "推荐策略编号", "推荐场景", "预检结论", "场景命中结果",
    "命中策略编号", "策略复用次数", "预计复用次数", "预计推荐结果", "多样性权重",
    "同优先级候选", "裁决口径", "闭环状态", "业务批次", "上线批次", "预检说明",
]


@router.get("/pending", response_model=dict)
def list_pending(
    batch: str | None = Query(default=None, description="按业务批次筛选预检明细"),
    operator: Operator = Depends(current_operator),
) -> dict[str, Any]:
    """运营策略库待处理明细：承接推荐策略发布预检明细数据集，未闭环的排在前面。

    对只读角色只共享核对字段，不暴露推荐策略内部配置与写入口。
    """
    items = precheck_service.pending_for_tacticlib()
    if batch:
        items = [row for row in items if row.get("业务批次") == batch]
    if operator.read_only:
        items = [{key: row.get(key) for key in SHARED_FIELDS} for row in items]
    return {"items": items, "total": len(items)}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条运营策略明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"运营策略 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, operator: Operator = Depends(current_operator)) -> ActionResult:
    """登记一条运营策略，缺字段时说明原因而不是静默丢弃。"""
    require_write(operator)
    entry, missing = service.create_entry(payload.merged())
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="运营策略已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int, payload: EntryPayload, operator: Operator = Depends(current_operator)
) -> ActionResult:
    """对单条运营策略执行提交策略评审、发布策略、退役策略；不允许的动作会被拦下并说明原因。"""
    require_write(operator)
    action = str(payload.merged().get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
