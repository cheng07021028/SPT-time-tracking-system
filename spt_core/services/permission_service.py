from __future__ import annotations

from ..result import Result

ROLE_ORDER = {
    "operator": 10,
    "supervisor": 50,
    "admin": 100,
}

ACTION_MIN_ROLE = {
    "time.start": "operator",
    "time.finish": "operator",
    "time.view": "operator",
    "time.delete": "admin",
    "work_order.view": "operator",
    "work_order.write": "supervisor",
    "work_order.delete": "admin",
    "employee.view": "operator",
    "employee.write": "admin",
    "employee.delete": "admin",
    "log.view": "admin",
    "login_event.view": "admin",
    "permission.manage": "admin",
    "setting.manage": "admin",
}


def role_allows(role: str, action: str) -> bool:
    required = ACTION_MIN_ROLE.get(action, "admin")
    return ROLE_ORDER.get(role, 0) >= ROLE_ORDER.get(required, 100)


def require_permission(actor: dict | None, action: str) -> Result:
    if not actor:
        return Result.failure("尚未登入或登入狀態已失效")
    role = actor.get("role", "operator")
    if not role_allows(role, action):
        return Result.failure(f"權限不足：{action} 需要 {ACTION_MIN_ROLE.get(action, 'admin')} 以上角色")
    return Result.success()
