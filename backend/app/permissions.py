"""智能推荐权限归属：写操作只对运营角色开放，只读角色不能改变状态。

请求头只收 ASCII 角色码（admin / ops_lead / auditor / analyst），避免中文头在
HTTP 传输层被截断；角色码在这里映射成业务称呼。
策略库待处理明细是跨模块共享视图：只读角色只拿到核对字段，也没有写入入口，
越权写会被拦下，从而保持只读与共享边界不变。
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

ROLE_LABELS = {
    "admin": "值班管理员",
    "ops_lead": "运营主管",
    "auditor": "只读审计",
    "analyst": "数据分析员",
}
WRITE_ROLES = {"admin", "ops_lead"}
READ_ROLES = {"auditor", "analyst"}
DEFAULT_ROLE = "admin"


@dataclass(frozen=True)
class Operator:
    name: str
    role_code: str
    can_write: bool

    @property
    def role(self) -> str:
        return ROLE_LABELS[self.role_code]

    @property
    def read_only(self) -> bool:
        return self.role_code in READ_ROLES


def current_operator(
    x_operator: str | None = Header(default=None, alias="X-Operator"),
    x_role: str | None = Header(default=None, alias="X-Role"),
) -> Operator:
    role_code = (x_role or DEFAULT_ROLE).strip().lower()
    if role_code in ROLE_LABELS.values():
        role_code = next(code for code, label in ROLE_LABELS.items() if label == role_code)
    if role_code not in ROLE_LABELS:
        raise HTTPException(status_code=403, detail=f"角色码「{role_code}」没有智能推荐权限")
    return Operator(
        name=(x_operator or ROLE_LABELS[role_code]).strip(),
        role_code=role_code,
        can_write=role_code in WRITE_ROLES,
    )


def require_write(operator: Operator) -> None:
    if not operator.can_write:
        raise HTTPException(
            status_code=403,
            detail=f"当前角色「{operator.role}」只读，不能改变推荐策略与策略库状态",
        )
