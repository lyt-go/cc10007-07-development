"""智能推荐接口：维护推荐策略，覆盖提交策略评审、评审通过、发布预检与上线动作。

上线策略不在这里直接改状态：它必须由推荐策略发布预检给出唯一场景命中结果后，
再由预检明细数据集执行上线。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.permissions import Operator, current_operator, require_write
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.precheck import PrecheckService
from app.services.recommend import RecommendService

router = APIRouter(prefix="/api/recommend", tags=["智能推荐"])

service = RecommendService()
precheck_service = PrecheckService()

LIST_FIELDS = [
    "策略编号", "推荐场景", "召回算法", "排序模型", "冷启动策略", "多样性权重",
    "刷新频率", "推荐条数上限", "场景评分", "复用策略编号", "预检结论",
]
STATUSES = ["草稿", "策略评审中", "评审通过", "预检通过", "已上线", "已下线"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按策略编号或推荐场景检索"),
    status: str | None = Query(default=None, description="草稿、策略评审中、评审通过、预检通过、已上线、已下线"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按策略编号、推荐场景与状态过滤智能推荐列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出智能推荐清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "recommend", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条推荐策略明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"推荐策略 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, operator: Operator = Depends(current_operator)) -> ActionResult:
    """登记一条推荐策略，缺字段时说明原因而不是静默丢弃。"""
    require_write(operator)
    entry, missing = service.create_entry(payload.merged())
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="推荐策略已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload, operator: Operator = Depends(current_operator)) -> ActionResult:
    """执行提交策略评审、评审通过、下线策略；上线策略会被引导到发布预检。"""
    require_write(operator)
    action = str(payload.merged().get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/precheck", response_model=ActionResult)
def register_precheck(
    entry_id: int, payload: EntryPayload, operator: Operator = Depends(current_operator)
) -> ActionResult:
    """从智能推荐动作接入发布预检：读推荐场景配置与策略库已发布策略，登记预检明细数据集。"""
    require_write(operator)
    entry, message = precheck_service.register(
        entry_id,
        operator=operator.name,
        requested_batch=payload.merged().get("batch"),
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=entry.get("预检结论") != "未通过", message=message, entry=entry)


@router.post("/{entry_id}/launch", response_model=ActionResult)
def launch(
    entry_id: int, payload: EntryPayload, operator: Operator = Depends(current_operator)
) -> ActionResult:
    """从智能推荐动作上线：只允许预检通过且未闭环的数据集，同一场景只保留一个来源。"""
    require_write(operator)
    entry, message = precheck_service.launch_for_strategy(
        entry_id, operator=operator.name
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=entry.get("预检结论") != "未通过", message=message, entry=entry)
