# -*- coding: utf-8 -*-
"""05｜製令工時分析：判斷機型清單與萃取服務。

設計原則：
- Neon / PostgreSQL 的 system_settings 是正式權威來源。
- Local JSON 只做 fallback / mirror，避免正式環境 Reboot 後被舊檔覆蓋。
- 此服務只產生 05 分析用衍生欄位，不寫回 01/02 工時權威資料。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from services.timezone_service import now_text
except Exception:  # pragma: no cover
    import time

    def now_text() -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_MODEL_RULES_PATH = (
    PROJECT_ROOT
    / "data"
    / "permanent_store"
    / "persistent_modules"
    / "05_analysis"
    / "model_detection_rules.json"
)

SYSTEM_SETTING_KEY = "05_model_detection_rules_v1"
SYSTEM_SETTING_NOTE = "05 製令工時分析｜判斷機型清單 JSON"
_DB_SCHEMA_READY = False

DEFAULT_MODEL_NAMES: list[str] = [
    "Sorter",
    "EFEM",
    "NTB",
    "FCLP",
    "BWBS",
    "Bench",
    "EB2",
    "EB4",
    "EB4L",
    "SB2",
    "SB4",
    "SB4L",
    "SB3L",
    "SA4L",
]

# match_keyword：從「機型 / Type」或「P/N / Part No.」裡抓到的包含字。
# model_name：實際顯示在「判斷機型」欄位的名稱。
# 既有規則（Sorter、EFEM...）會以同名方式保存；特殊規則可把關鍵字映射到不同顯示名稱，
# 例如 ROBOT+X-table -> Others(倍利)。
DEFAULT_MODEL_RULES: list[dict[str, Any]] = [
    {"match_keyword": name, "model_name": name, "enabled": True, "sort_order": idx + 1, "note": ""}
    for idx, name in enumerate(DEFAULT_MODEL_NAMES)
]
DEFAULT_MODEL_RULES.append(
    {
        "match_keyword": "ROBOT+X-table",
        "model_name": "Others(倍利)",
        "enabled": True,
        "sort_order": len(DEFAULT_MODEL_RULES) + 1,
        "note": "包含 ROBOT+X-table 時歸類為 Others(倍利)",
    }
)


def _db_services():
    try:
        from services.db_service import ensure_database, query_one, execute

        return ensure_database, query_one, execute
    except Exception:
        return None, None, None


def _ensure_db_schema() -> bool:
    global _DB_SCHEMA_READY
    if _DB_SCHEMA_READY:
        return True
    ensure_database, _query_one, execute = _db_services()
    if not callable(ensure_database) or not callable(execute):
        return False
    try:
        ensure_database()
        execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key TEXT,
                setting_value TEXT,
                note TEXT,
                updated_at TEXT
            )
            """,
            (),
        )
        try:
            execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_05_model_detection_system_settings_key ON system_settings(setting_key)",
                (),
            )
        except Exception:
            pass
        _DB_SCHEMA_READY = True
        return True
    except Exception:
        return False


def _blank(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value if value is not None else "").strip()
    return "" if text.lower() in {"none", "nan", "nat", "null"} else text


def _truthy(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    text = _blank(value).strip().lower()
    if not text:
        return bool(default)
    if text in {"1", "true", "yes", "y", "on", "啟用", "是", "勾選"}:
        return True
    if text in {"0", "false", "no", "n", "off", "停用", "否", "刪除"}:
        return False
    return bool(default)


def _clean_match_text(value: Any) -> str:
    """Normalize a text cell for robust model matching.

    Removing punctuation lets EB-4L / EB 4L still match EB4L. Longest enabled
    model names are matched first, so EB4L wins before EB4 and SB4L wins before SB4.
    """
    text = _blank(value).upper()
    return re.sub(r"[^A-Z0-9]+", "", text)


def _default_rules_payload() -> dict[str, Any]:
    return {
        "version": "V2",
        "updated_at": now_text(),
        "rules": [dict(rule) for rule in DEFAULT_MODEL_RULES],
    }


def default_model_rules_payload() -> dict[str, Any]:
    """Public default payload for page-level reset buttons."""
    return _default_rules_payload()


def normalize_model_rules(payload: Any) -> dict[str, Any]:
    source_version = str(payload.get("version") or "") if isinstance(payload, dict) else ""
    if isinstance(payload, list):
        raw_rules = payload
    elif isinstance(payload, dict):
        raw_rules = payload.get("rules", [])
    else:
        raw_rules = []

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, row in enumerate(raw_rules if isinstance(raw_rules, list) else []):
        if not isinstance(row, dict):
            row = {"model_name": row}

        display_name = _blank(
            row.get("model_name")
            or row.get("display_model")
            or row.get("display_name")
            or row.get("name")
            or row.get("機型")
            or row.get("判斷機型")
        )
        match_keyword = _blank(
            row.get("match_keyword")
            or row.get("keyword")
            or row.get("contains_text")
            or row.get("contains")
            or row.get("比對字")
            or row.get("包含字")
            or row.get("包含關鍵字")
            or row.get("比對關鍵字")
        )

        # Backward compatibility: old V1 rows only had model_name, which meant
        # both matching keyword and output display name.
        if not match_keyword:
            match_keyword = display_name
        if not display_name:
            display_name = match_keyword

        match_key = _clean_match_text(match_keyword)
        if not match_key or not display_name or match_key in seen:
            continue
        seen.add(match_key)
        try:
            order = int(float(row.get("sort_order") or row.get("order") or row.get("排序") or idx + 1))
        except Exception:
            order = idx + 1
        rows.append(
            {
                "match_keyword": match_keyword,
                "model_name": display_name,
                "enabled": _truthy(row.get("enabled", row.get("啟用", True)), default=True),
                "sort_order": order,
                "note": _blank(row.get("note") or row.get("備註")),
            }
        )

    if not rows:
        rows = _default_rules_payload()["rules"]
    elif source_version != "V2":
        # One-time migration for older saved V1 lists: keep user rules, but add
        # the new requested keyword-mapping example if it is not already present.
        existing_keys = {_clean_match_text(r.get("match_keyword") or r.get("model_name")) for r in rows}
        for default_rule in DEFAULT_MODEL_RULES:
            key = _clean_match_text(default_rule.get("match_keyword") or default_rule.get("model_name"))
            if key == _clean_match_text("ROBOT+X-table") and key not in existing_keys:
                migrated = dict(default_rule)
                migrated["sort_order"] = len(rows) + 1
                rows.append(migrated)
                existing_keys.add(key)

    rows = sorted(
        rows,
        key=lambda r: (
            int(r.get("sort_order") or 999999),
            -len(_clean_match_text(r.get("match_keyword"))),
            str(r.get("model_name") or ""),
        ),
    )
    for idx, row in enumerate(rows):
        row["sort_order"] = idx + 1
    return {"version": "V2", "updated_at": now_text(), "rules": rows}


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists() and path.stat().st_size > 0:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
    except Exception:
        return None
    return None


def _write_local_cache(payload: dict[str, Any]) -> None:
    try:
        LOCAL_MODEL_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_MODEL_RULES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass


def _load_from_db() -> dict[str, Any] | None:
    if not _ensure_db_schema():
        return None
    _ensure_database, query_one, _execute = _db_services()
    if not callable(query_one):
        return None
    try:
        row = query_one(
            "SELECT setting_value FROM system_settings WHERE setting_key=? ORDER BY updated_at DESC LIMIT 1",
            (SYSTEM_SETTING_KEY,),
        ) or {}
        raw = row.get("setting_value") if isinstance(row, dict) else None
        if not raw:
            return None
        parsed = json.loads(str(raw))
        return normalize_model_rules(parsed)
    except Exception:
        return None


def _save_to_db(payload: dict[str, Any]) -> bool:
    if not _ensure_db_schema():
        return False
    _ensure_database, query_one, execute = _db_services()
    if not callable(query_one) or not callable(execute):
        return False
    text = json.dumps(payload, ensure_ascii=False, default=str)
    now = now_text()
    try:
        existing = query_one("SELECT setting_key FROM system_settings WHERE setting_key=? LIMIT 1", (SYSTEM_SETTING_KEY,))
        if existing:
            execute(
                "UPDATE system_settings SET setting_value=?, note=?, updated_at=? WHERE setting_key=?",
                (text, SYSTEM_SETTING_NOTE, now, SYSTEM_SETTING_KEY),
            )
        else:
            execute(
                "INSERT INTO system_settings(setting_key, setting_value, note, updated_at) VALUES (?, ?, ?, ?)",
                (SYSTEM_SETTING_KEY, text, SYSTEM_SETTING_NOTE, now),
            )
        return True
    except Exception:
        try:
            execute(
                """
                INSERT INTO system_settings(setting_key, setting_value, note, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value=excluded.setting_value,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (SYSTEM_SETTING_KEY, text, SYSTEM_SETTING_NOTE, now),
            )
            return True
        except Exception:
            return False


def load_model_rules() -> dict[str, Any]:
    db_payload = _load_from_db()
    if db_payload:
        _write_local_cache(db_payload)
        return db_payload

    local = _load_json(LOCAL_MODEL_RULES_PATH)
    if local:
        payload = normalize_model_rules(local)
        _save_to_db(payload)
        return payload

    payload = _default_rules_payload()
    _save_to_db(payload)
    _write_local_cache(payload)
    return payload


def save_model_rules(payload: Any) -> dict[str, Any]:
    normalized = normalize_model_rules(payload)
    normalized["updated_at"] = now_text()
    _save_to_db(normalized)
    _write_local_cache(normalized)
    return normalized


def model_rules_to_dataframe(payload: Any) -> pd.DataFrame:
    rules = normalize_model_rules(payload).get("rules", [])
    df = pd.DataFrame(rules)
    if df.empty:
        df = pd.DataFrame(columns=["delete", "match_keyword", "model_name", "enabled", "sort_order", "note"])
    if "delete" not in df.columns:
        df.insert(0, "delete", False)
    cols = ["delete", "match_keyword", "model_name", "enabled", "sort_order", "note"]
    for col in cols:
        if col not in df.columns:
            df[col] = False if col in {"delete", "enabled"} else ""
    df["match_keyword"] = df["match_keyword"].map(_blank)
    df["model_name"] = df["model_name"].map(_blank)
    # Keep older saved rows usable if they only had model_name.
    df.loc[df["match_keyword"].eq(""), "match_keyword"] = df.loc[df["match_keyword"].eq(""), "model_name"]
    df.loc[df["model_name"].eq(""), "model_name"] = df.loc[df["model_name"].eq(""), "match_keyword"]
    df["delete"] = df["delete"].map(lambda _: False).astype(bool)
    df["enabled"] = df["enabled"].map(lambda x: _truthy(x, default=True)).astype(bool)
    order = pd.to_numeric(df["sort_order"], errors="coerce")
    fallback_order = pd.Series(range(1, len(df) + 1), index=df.index, dtype="int64")
    df["sort_order"] = order.where(order.notna(), fallback_order).astype(int)
    return df[cols].reset_index(drop=True)


def dataframe_to_model_rules(df: pd.DataFrame) -> dict[str, Any]:
    if not isinstance(df, pd.DataFrame):
        return normalize_model_rules({"rules": []})
    work = df.copy()
    # Support either internal or localized column labels if table wrappers ever return localized names.
    rename = {
        "刪除 / Delete": "delete",
        "包含關鍵字 / Contains Text": "match_keyword",
        "比對關鍵字 / Match Keyword": "match_keyword",
        "判斷機型 / Model": "model_name",
        "顯示判斷機型 / Display Model": "model_name",
        "啟用 / Enabled": "enabled",
        "排序 / Sort Order": "sort_order",
        "備註 / Note": "note",
    }
    work = work.rename(columns={c: rename.get(str(c), str(c)) for c in work.columns})
    rows: list[dict[str, Any]] = []
    for idx, row in work.iterrows():
        rd = dict(row)
        if _truthy(rd.get("delete"), default=False):
            continue
        match_keyword = _blank(rd.get("match_keyword"))
        display_name = _blank(rd.get("model_name"))
        # Backward compatibility for old table layout.
        if not match_keyword:
            match_keyword = display_name
        if not display_name:
            display_name = match_keyword
        if not match_keyword or not display_name:
            continue
        try:
            order = int(float(rd.get("sort_order") or idx + 1))
        except Exception:
            order = idx + 1
        rows.append(
            {
                "match_keyword": match_keyword,
                "model_name": display_name,
                "enabled": _truthy(rd.get("enabled"), default=True),
                "sort_order": order,
                "note": _blank(rd.get("note")),
            }
        )
    return normalize_model_rules({"rules": rows})


def _enabled_model_names(payload: Any) -> list[str]:
    rules = normalize_model_rules(payload).get("rules", [])
    names = [
        str(r.get("model_name") or "").strip()
        for r in rules
        if _truthy(r.get("enabled"), default=True) and _blank(r.get("model_name"))
    ]
    # Return display names for compatibility with audit counters and legacy callers.
    return names


def _prepared_match_rules(payload: Any) -> list[tuple[str, str]]:
    """Return once-normalized (match_key, display_name) rules.

    match_key comes from match_keyword（包含關鍵字）; display_name comes from
    model_name（判斷機型）.  This supports rules such as:
        ROBOT+X-table -> Others(倍利)

    Longer keywords are matched first so EB4L/SB4L still win before EB4/SB4.
    """
    prepared: list[tuple[str, str]] = []
    seen: set[str] = set()
    for rule in normalize_model_rules(payload).get("rules", []):
        if not _truthy(rule.get("enabled"), default=True):
            continue
        keyword = _blank(rule.get("match_keyword") or rule.get("model_name"))
        display_name = _blank(rule.get("model_name") or keyword)
        key = _clean_match_text(keyword)
        if not key or not display_name or key in seen:
            continue
        prepared.append((key, display_name))
        seen.add(key)
    return sorted(prepared, key=lambda item: len(item[0]), reverse=True)


def _normalize_match_series(series: pd.Series, index: pd.Index) -> pd.Series:
    """Vectorized version of _clean_match_text for a dataframe column."""
    if not isinstance(series, pd.Series):
        series = pd.Series([""] * len(index), index=index)
    return (
        series.reindex(index)
        .fillna("")
        .astype(str)
        .str.upper()
        .str.replace(r"[^A-Z0-9]+", "", regex=True)
    )


def detect_model_from_values(type_value: Any, part_no_value: Any, payload: Any) -> str:
    """Detect one row. Kept for compatibility with existing callers/tests."""
    type_text = _clean_match_text(type_value)
    pn_text = _clean_match_text(part_no_value)
    for key, name in _prepared_match_rules(payload):
        if key and key in type_text:
            return name
    for key, name in _prepared_match_rules(payload):
        if key and key in pn_text:
            return name
    return ""


def apply_judged_model_column(df: pd.DataFrame, payload: Any | None = None, column_name: str = "judged_model") -> pd.DataFrame:
    """Add 05 analysis-only judged model column with vectorized matching.

    Priority is unchanged:
    1. Match model rules from 機型 / Type (`type_name`).
    2. Only when not found, match from P/N / Part No. (`part_no`).

    This function does not write back to 01/02 records.  It only enriches the
    dataframe used by 05 reports, so it is safe for UI reruns and cache reuse.
    """
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()

    out = df.copy()
    if out.empty:
        out[column_name] = pd.Series(dtype="object")
        return out

    rules = payload if payload is not None else load_model_rules()
    prepared = _prepared_match_rules(rules)
    if not prepared:
        out[column_name] = ""
        return out

    type_series = out["type_name"] if "type_name" in out.columns else pd.Series([""] * len(out), index=out.index)
    pn_series = out["part_no"] if "part_no" in out.columns else pd.Series([""] * len(out), index=out.index)

    type_text = _normalize_match_series(type_series, out.index)
    pn_text = _normalize_match_series(pn_series, out.index)

    result = pd.Series("", index=out.index, dtype="object")

    # First priority: 機型 / Type. Longest rules are already first.
    unmatched = result.eq("")
    for key, name in prepared:
        if not unmatched.any():
            break
        mask = unmatched & type_text.str.contains(key, regex=False, na=False)
        if mask.any():
            result.loc[mask] = name
            unmatched = result.eq("")

    # Second priority: P/N / Part No. only for rows still unmatched.
    unmatched = result.eq("")
    for key, name in prepared:
        if not unmatched.any():
            break
        mask = unmatched & pn_text.str.contains(key, regex=False, na=False)
        if mask.any():
            result.loc[mask] = name
            unmatched = result.eq("")

    out[column_name] = result
    return out


def audit_model_detection_service() -> dict[str, Any]:
    payload = load_model_rules()
    return {
        "version": "V2",
        "authority": "system_settings",
        "setting_key": SYSTEM_SETTING_KEY,
        "default_model_count": len(DEFAULT_MODEL_RULES),
        "active_model_count": len(_enabled_model_names(payload)),
        "fallback_order": ["type_name", "part_no"],
    }
