# -*- coding: utf-8 -*-
"""Apply SPT V162 safe JSON write overrides to the current project.

This patcher appends override blocks instead of replacing whole service files,
so it will not downgrade V156/V157/V158/V159/V160/V161 changes already applied.
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKER = "# === SPT V162 SAFE JSON WRITE OVERRIDE ==="

TARGETS = {
    "services/permanent_authority_service.py": r'''
# === SPT V162 SAFE JSON WRITE OVERRIDE ===
# This block is intentionally appended at file end to preserve earlier Vxxx patches.
try:
    from pathlib import Path as _V162_Path
    from services.safe_file_write_service import atomic_write_json_safely as _v162_atomic_write_json_safely, read_json_safely as _v162_read_json_safely

    def atomic_write_json(path: _V162_Path, payload: dict[str, Any]) -> None:  # type: ignore[override]
        _v162_atomic_write_json_safely(
            path,
            payload,
            default=_json_default,
            reason="permanent_authority_service",
            create_bak=True,
        )
        try:
            _CACHE.pop((str(path), "json"), None)
        except Exception:
            pass

    def read_json(path: _V162_Path) -> dict[str, Any]:  # type: ignore[override]
        data = _v162_read_json_safely(path, restore_if_corrupt=True, default={})
        return data if isinstance(data, dict) else {}
except Exception:
    pass
''',
    "services/persistence_core_service.py": r'''
# === SPT V162 SAFE JSON WRITE OVERRIDE ===
try:
    from pathlib import Path as _V162_Path
    from services.safe_file_write_service import atomic_write_json_safely as _v162_atomic_write_json_safely, read_json_safely as _v162_read_json_safely

    def atomic_write_json(path: _V162_Path, payload: dict[str, Any]) -> None:  # type: ignore[override]
        _v162_atomic_write_json_safely(path, payload, default=str, reason="persistence_core_service", create_bak=True)

    def read_json(path: _V162_Path) -> dict[str, Any]:  # type: ignore[override]
        data = _v162_read_json_safely(path, restore_if_corrupt=True, default={})
        return data if isinstance(data, dict) else {}
except Exception:
    pass
''',
    "services/system_settings_service.py": r'''
# === SPT V162 SAFE JSON WRITE OVERRIDE ===
try:
    from pathlib import Path as _V162_Path
    from services.safe_file_write_service import atomic_write_json_safely as _v162_atomic_write_json_safely, read_json_safely as _v162_read_json_safely

    def _atomic_write_json(path: _V162_Path, payload: dict[str, Any]) -> None:  # type: ignore[override]
        _v162_atomic_write_json_safely(path, payload, default=str, reason="system_settings_service", create_bak=True)

    def _load_json_file(path: _V162_Path) -> dict[str, Any] | None:  # type: ignore[override]
        data = _v162_read_json_safely(path, restore_if_corrupt=True, default=None)
        return data if isinstance(data, dict) else None
except Exception:
    pass
''',
    "services/table_persistence_service.py": r'''
# === SPT V162 SAFE JSON WRITE OVERRIDE ===
try:
    from pathlib import Path as _V162_Path
    from services.safe_file_write_service import atomic_write_json_safely as _v162_atomic_write_json_safely

    def _atomic_json(path: _V162_Path, payload: dict[str, Any]) -> None:  # type: ignore[override]
        _v162_atomic_write_json_safely(path, payload, default=str, reason="table_persistence_service", create_bak=True)

    def _v366_write_payload(path: _V162_Path, payload: dict[str, Any]) -> None:  # type: ignore[override]
        _v162_atomic_write_json_safely(path, payload, default=str, reason="table_persistence_service_v366", create_bak=True)

    def _v370_write_settings_file(path: _V162_Path, module_code: str, shard: dict[str, Any]) -> None:  # type: ignore[override]
        payload = {"module_code": module_code, "settings": shard, "source": "v370_table_settings"}
        _v162_atomic_write_json_safely(path, payload, default=str, reason="table_persistence_service_v370", create_bak=True)
except Exception:
    pass
''',
}


def patch_file(rel_path: str, block: str) -> dict[str, str]:
    path = PROJECT_ROOT / rel_path
    if not path.exists():
        return {"file": rel_path, "status": "missing"}
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        return {"file": rel_path, "status": "already_patched"}
    backup = path.with_suffix(path.suffix + ".bak_v162_before_safe_write")
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")
    path.write_text(text.rstrip() + "\n\n" + block.strip() + "\n", encoding="utf-8")
    return {"file": rel_path, "status": "patched", "backup": str(backup.relative_to(PROJECT_ROOT))}


def main() -> int:
    results = [patch_file(rel, block) for rel, block in TARGETS.items()]
    for r in results:
        print(r)
    missing = [r for r in results if r.get("status") == "missing"]
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
