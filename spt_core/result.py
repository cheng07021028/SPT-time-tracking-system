from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Result:
    ok: bool
    message: str = ""
    data: Any = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    log_id: str | None = None

    @classmethod
    def success(cls, message: str = "", data: Any = None, warnings: list[str] | None = None, log_id: str | None = None) -> "Result":
        return cls(ok=True, message=message, data=data, warnings=warnings or [], log_id=log_id)

    @classmethod
    def failure(cls, message: str, errors: list[str] | None = None, data: Any = None) -> "Result":
        return cls(ok=False, message=message, errors=errors or [message], data=data)
