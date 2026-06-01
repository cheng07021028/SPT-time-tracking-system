# -*- coding: utf-8 -*-
"""Clean authority-only permission service for SPT Time Tracking.

V300 CLEAN RULES
- 10. 權限管理 reads/writes only data/permanent_store/modules/10_permissions/records.json
- idle timeout reads/writes only security_runtime_settings.json
- no persistent_modules / persistent_state / recovery / SQLite fallback overwrites
- 06/11 logs are append-only jsonl authority files
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import json, os, hashlib, hmac, base64
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERM_DIR = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "10_permissions"
AUTH_FILE = PERM_DIR / "records.json"
SECURITY_FILE = PERM_DIR / "security_runtime_settings.json"
LOGIN_JSONL = PROJECT_ROOT / "data" / "permanent_store" / "modules" / "11_login_records" / "records.jsonl"

ACTIONS = [
    ("can_view", "可進入", "View"),
    ("can_create", "可新增", "Create"),
    ("can_edit", "可編輯", "Edit"),
    ("can_delete", "可刪除", "Delete"),
    ("can_import", "可匯入", "Import"),
    ("can_export", "可匯出", "Export"),
    ("can_backup", "可備份", "Backup"),
    ("can_restore", "可還原", "Restore"),
    ("can_manage", "可管理", "Manage"),
]
MODULES = [
    {"module_code":"01","module_name_zh":"工時紀錄","module_name_en":"Time Recording"},
    {"module_code":"02","module_name_zh":"歷史紀錄","module_name_en":"History"},
    {"module_code":"03","module_name_zh":"製令管理","module_name_en":"Work Orders"},
    {"module_code":"04","module_name_zh":"人員名單","module_name_en":"Employees"},
    {"module_code":"05","module_name_zh":"製令工時分析","module_name_en":"WO Time Analysis"},
    {"module_code":"06","module_name_zh":"LOG查詢","module_name_en":"Logs"},
    {"module_code":"07","module_name_zh":"今日未紀錄名單","module_name_en":"Missing Today"},
    {"module_code":"08","module_name_zh":"人員每日工時","module_name_en":"Daily Hours"},
    {"module_code":"09","module_name_zh":"資料永久保存與備份","module_name_en":"Backup"},
    {"module_code":"10","module_name_zh":"權限管理","module_name_en":"Permissions"},
    {"module_code":"11","module_name_zh":"登入紀錄","module_name_en":"Login Records"},
    {"module_code":"12","module_name_zh":"模組永久紀錄中心","module_name_en":"Persistence Center"},
    {"module_code":"13","module_name_zh":"系統設定","module_name_en":"System Settings"},
    {"module_code":"14","module_name_zh":"資料健康檢查中心","module_name_en":"Data Health"},
    {"module_code":"99","module_name_zh":"效能診斷","module_name_en":"Performance"},
]
ROLE_DESCRIPTIONS = {
    # Keep both old/new keys for page compatibility:
    # - zh/en/desc are used by 10_10. 權限管理.py
    # - label/description are used by older services and fallback code
    "admin": {"zh":"系統管理員", "en":"Administrator", "desc":"全部權限", "label":"系統管理員", "description":"全部權限"},
    "manager": {"zh":"主管", "en":"Manager", "desc":"管理與查詢", "label":"主管", "description":"管理與查詢"},
    "leader": {"zh":"現場幹部", "en":"Leader", "desc":"現場操作", "label":"現場幹部", "description":"現場操作"},
    "operator": {"zh":"作業人員", "en":"Operator", "desc":"工時操作", "label":"作業人員", "description":"工時操作"},
    "viewer": {"zh":"查詢者", "en":"Viewer", "desc":"只讀查詢", "label":"查詢者", "description":"只讀查詢"},
    "auditor": {"zh":"稽核", "en":"Auditor", "desc":"稽核查詢", "label":"稽核", "description":"稽核查詢"},
}

def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _read_json(path: Path, default: Any=None) -> Any:
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {} if default is None else default

def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)

def _tables(payload: dict) -> dict[str, list[dict[str, Any]]]:
    t = payload.get("tables") if isinstance(payload, dict) else {}
    if not isinstance(t, dict): t = {}
    for k in ["auth_users","auth_account_permissions","auth_security_settings","security_settings","security_users","security_user_roles"]:
        if not isinstance(t.get(k), list): t[k] = []
    return t

def _payload() -> dict:
    PERM_DIR.mkdir(parents=True, exist_ok=True)
    data = _read_json(AUTH_FILE, {})
    if not isinstance(data, dict) or not data:
        data = {"authority_schema":"SPT_PERMISSION_AUTHORITY_CLEAN_V1","module_key":"10_permissions","kind":"records","updated_at":now_text(),"tables":{},"settings":{},"table_counts":{}}
    _tables(data)
    return data

def _write_payload(data: dict, reason: str="permission_save") -> dict:
    data["authority_schema"] = "SPT_PERMISSION_AUTHORITY_CLEAN_V1"
    data["module_key"] = "10_permissions"
    data["kind"] = "records"
    data["updated_at"] = now_text()
    data["reason"] = reason
    t = _tables(data)
    data["table_counts"] = {k: len(v) for k,v in t.items() if isinstance(v, list)}
    _atomic_write_json(AUTH_FILE, data)
    _sync_github_best_effort()
    return {"ok": True, "authority_file": str(AUTH_FILE), "table_counts": data["table_counts"]}

def _sync_github_best_effort() -> dict:
    """Best effort immediate GitHub write-through for Streamlit Cloud reboot durability."""
    try:
        from services import permanent_authority_service as pas
        if hasattr(pas, "github_put_file"):
            return pas.github_put_file(AUTH_FILE, AUTH_FILE.read_text(encoding="utf-8"), "SPT 10_permissions authority save")
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": False, "error": "github_put_file_unavailable"}

def _clean_username(v: Any) -> str:
    return str(v or "").strip()

def _norm_bool(v: Any, default: bool=True) -> int:
    if isinstance(v, bool): return 1 if v else 0
    t = str(v).strip().lower()
    if t in {"1","true","yes","y","啟用","是","active"}: return 1
    if t in {"0","false","no","n","停用","否","inactive"}: return 0
    return 1 if default else 0

def hash_password(password: str, salt: str|None=None) -> str:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), str(salt).encode("utf-8"), 120000).hex()
    return f"pbkdf2_sha256${salt}${digest}"

def verify_password(password: str, password_hash: str) -> bool:
    h = str(password_hash or "")
    try:
        if h.startswith("pbkdf2_sha256$"):
            _, salt, digest = h.split("$", 2)
            chk = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt.encode("utf-8"), 120000).hex()
            return hmac.compare_digest(chk, digest)
    except Exception:
        pass
    return False

def _role_defaults(role: str, module: str) -> dict[str,int]:
    role = str(role or "operator").lower()
    if role == "admin": return {a[0]: 1 for a in ACTIONS}
    if module == "99": return {a[0]: 0 for a in ACTIONS}
    if role == "viewer": return {**{a[0]:0 for a in ACTIONS}, "can_view":1, "can_export":1}
    if role == "operator": return {**{a[0]:0 for a in ACTIONS}, "can_view":1, "can_create":1, "can_edit":1}
    if role in {"manager","leader"}: return {**{a[0]:1 for a in ACTIONS}, "can_manage": 1 if role=="manager" else 0}
    if role == "auditor": return {**{a[0]:0 for a in ACTIONS}, "can_view":1, "can_export":1}
    return {**{a[0]:0 for a in ACTIONS}, "can_view":1}

def _module_no(code: Any) -> str:
    s = str(code or "").strip()
    mapping = {"01_time_record":"01","01_time_records":"01","02_history":"02","03_work_orders":"03","04_employees":"04","05_analysis":"05","05_work_order_time_analysis":"05","06_logs":"06","06_log_query":"06","07_missing":"07","07_missing_today":"07","08_daily_hours":"08","08_employee_daily_hours":"08","09_persistence":"09","09_backup_restore":"09","10_permissions":"10","11_login_logs":"11","11_login_records":"11","12_module_persistence":"12","12_module_persistence_center":"12","13_system_settings":"13","14_data_health":"14","99_speed_diagnostic":"99"}
    return mapping.get(s, s[:2] if s[:2].isdigit() else s)

def _ensure_permissions_for_user(tables: dict, username: str, role: str) -> None:
    perms = tables["auth_account_permissions"]
    existing = {(str(r.get("username")).lower(), _module_no(r.get("module_code"))) for r in perms if isinstance(r,dict)}
    for m in MODULES:
        code = m["module_code"]
        key = (username.lower(), code)
        if key not in existing:
            row = {"username": username, "module_code": code, "module_name_zh": m["module_name_zh"], "module_name_en": m["module_name_en"], "updated_at": now_text()}
            row.update(_role_defaults(role, code))
            perms.append(row)

def init_permission_tables(force: bool=False) -> dict:
    data = _payload(); t = _tables(data)
    if not t["auth_users"]:
        admin_hash = hash_password("Admin@1234")
        t["auth_users"].append({"username":"admin","password_hash":admin_hash,"display_name":"系統管理員","email":"","employee_id":"","role_code":"admin","is_active":1,"force_password_change":0,"note":"clean default admin","created_at":now_text(),"updated_at":now_text()})
    for u in list(t["auth_users"]):
        if isinstance(u,dict): _ensure_permissions_for_user(t, str(u.get("username","")), str(u.get("role_code","operator")))
    _write_payload(data, "init_permission_tables")
    return {"ok": True}

def restore_default_accounts_once_v57(): return {"ok": True, "skipped": True}
def restore_permission_settings_from_permanent_files(force: bool=False): return {"ok": True, "skipped": True, "authority_file": str(AUTH_FILE)}
def export_permission_settings_permanently(reason: str="manual"): return _write_payload(_payload(), reason)
def reconcile_permission_matrix_for_current_modules(force: bool=False):
    data=_payload(); t=_tables(data)
    for u in t["auth_users"]: _ensure_permissions_for_user(t, str(u.get("username","")), str(u.get("role_code","operator")))
    return _write_payload(data, "reconcile_permission_matrix")

def get_users() -> list[dict[str,Any]]:
    data=_payload(); t=_tables(data); deleted={str(x).lower() for x in data.get("deleted_usernames",[]) if str(x).strip()}
    out=[]
    for r in t["auth_users"]:
        if not isinstance(r,dict): continue
        u=_clean_username(r.get("username"))
        if not u or u.lower() in deleted: continue
        row=dict(r)
        row["password_display"]="********" if row.get("password_hash") else ""
        row.setdefault("new_password", "")
        out.append(row)
    return sorted(out, key=lambda r: str(r.get("username","")).lower())

def save_users(rows: list[dict[str,Any]]) -> dict:
    data=_payload(); t=_tables(data); users=t["auth_users"]
    existing={str(r.get("username","")).lower(): r for r in users if isinstance(r,dict)}
    saved=0; skipped=[]
    for src in rows or []:
        username=_clean_username(src.get("username") or src.get("帳號 / Username"))
        if not username: continue
        key=username.lower(); old=existing.get(key, {})
        new_pwd=str(src.get("new_password") or src.get("password") or src.get("密碼 / Password") or "").strip()
        password_hash = hash_password(new_pwd) if new_pwd and set(new_pwd)!={"*"} else str(old.get("password_hash") or "")
        if not password_hash:
            password_hash = hash_password("Admin@1234" if key=="admin" else username)
        row=dict(old)
        row.update({
            "username": username,
            "password_hash": password_hash,
            "employee_id": str(src.get("employee_id") or src.get("工號 / Employee ID") or old.get("employee_id") or ""),
            "display_name": str(src.get("display_name") or src.get("姓名 / Display Name") or old.get("display_name") or username),
            "email": str(src.get("email") or src.get("Email") or old.get("email") or ""),
            "role_code": str(src.get("role_code") or src.get("角色 / Role") or old.get("role_code") or "operator"),
            "is_active": _norm_bool(src.get("is_active", src.get("啟用 / Active", old.get("is_active",1))), True),
            "force_password_change": _norm_bool(src.get("force_password_change", src.get("強制改密碼 / Force Change", old.get("force_password_change",0))), False),
            "note": str(src.get("note") or src.get("備註 / Note") or old.get("note") or ""),
            "updated_at": now_text(),
        })
        row.setdefault("created_at", old.get("created_at") or now_text())
        if key in existing: existing[key].clear(); existing[key].update(row)
        else:
            users.append(row); existing[key]=row
        # remove from tombstone when explicitly saved/created
        data["deleted_usernames"]=[x for x in data.get("deleted_usernames",[]) if str(x).lower()!=key]
        _ensure_permissions_for_user(t, username, row.get("role_code","operator"))
        saved += 1
    res=_write_payload(data, "save_users_direct_authority")
    res.update({"saved": saved, "skipped": skipped})
    return res

def save_account_master(rows: list[dict[str,Any]], delete_usernames: list[str]|None=None) -> dict:
    res=save_users(rows or [])
    deleted=delete_users(delete_usernames or []) if delete_usernames else 0
    res["deleted"] = deleted
    return res

def delete_users(usernames: list[str]) -> int:
    data=_payload(); t=_tables(data); dels={_clean_username(x).lower() for x in usernames or [] if _clean_username(x)}
    dels.discard("admin")
    if not dels: return 0
    before=len(t["auth_users"])
    t["auth_users"]=[r for r in t["auth_users"] if str(r.get("username","")).lower() not in dels]
    for tbl in ["security_users","security_user_roles","auth_account_permissions"]:
        t[tbl]=[r for r in t.get(tbl,[]) if str(r.get("username","")).lower() not in dels]
    existing_del={str(x).lower() for x in data.get("deleted_usernames",[]) if str(x).strip()}
    data["deleted_usernames"] = sorted(existing_del | dels)
    _write_payload(data, "delete_users_direct_authority")
    return before-len(t["auth_users"])

def get_account_permissions() -> list[dict[str,Any]]:
    data=_payload(); t=_tables(data)
    # ensure no missing rows for current users
    for u in t["auth_users"]: _ensure_permissions_for_user(t, str(u.get("username","")), str(u.get("role_code","operator")))
    _write_payload(data, "get_account_permissions_reconcile")
    return [dict(r) for r in t["auth_account_permissions"] if isinstance(r,dict)]

def save_account_permissions(rows: list[dict[str,Any]]) -> dict:
    data=_payload(); t=_tables(data)
    existing={(str(r.get("username","")).lower(), _module_no(r.get("module_code"))): r for r in t["auth_account_permissions"] if isinstance(r,dict)}
    saved=0
    for src in rows or []:
        username=_clean_username(src.get("username") or src.get("帳號 / Username"))
        code=_module_no(src.get("module_code") or src.get("模組代碼 / Module") or src.get("Module") or src.get("module"))
        if not username or not code: continue
        key=(username.lower(), code)
        row=dict(existing.get(key, {}))
        m=next((m for m in MODULES if m["module_code"]==code), {"module_name_zh":"","module_name_en":""})
        row.update({"username":username,"module_code":code,"module_name_zh":m.get("module_name_zh",""),"module_name_en":m.get("module_name_en",""),"updated_at":now_text()})
        for action,_,_ in ACTIONS:
            row[action]=_norm_bool(src.get(action, src.get(action.replace('can_',''), row.get(action,0))), False)
        if key in existing: existing[key].clear(); existing[key].update(row)
        else: t["auth_account_permissions"].append(row); existing[key]=row
        saved+=1
    res=_write_payload(data, "save_account_permissions_direct_authority")
    res["saved"] = saved
    return res

def has_permission(username: str, module_code: str, action: str="can_view") -> bool:
    uname=_clean_username(username).lower(); code=_module_no(module_code); act=str(action or "can_view")
    if uname=="admin": return True
    data=_payload(); t=_tables(data)
    users={str(r.get("username","")).lower():r for r in t["auth_users"] if isinstance(r,dict)}
    u=users.get(uname)
    if not u or not _norm_bool(u.get("is_active",1), True): return False
    for r in t["auth_account_permissions"]:
        if str(r.get("username","")).lower()==uname and _module_no(r.get("module_code"))==code:
            return bool(_norm_bool(r.get(act, 0), False))
    return bool(_role_defaults(str(u.get("role_code","operator")), code).get(act,0))

def get_security_settings() -> dict[str,Any]:
    sec=_read_json(SECURITY_FILE,{})
    out={}
    if isinstance(sec,dict):
        out.update(sec.get("security_settings", {}) if isinstance(sec.get("security_settings"),dict) else {})
        for k in ["idle_auto_logout_minutes","idle_timeout_minutes","ask_continue_after_record"]:
            if k in sec: out[k]=sec[k]
    data=_payload(); t=_tables(data)
    for row in t.get("auth_security_settings",[]) + t.get("security_settings",[]):
        if isinstance(row,dict) and row.get("setting_key") not in out:
            out[str(row.get("setting_key"))]=row.get("setting_value")
    out.setdefault("idle_timeout_minutes", out.get("idle_auto_logout_minutes", 15))
    out.setdefault("idle_auto_logout_minutes", out.get("idle_timeout_minutes", 15))
    out.setdefault("ask_continue_after_record", 1)
    return out

def save_security_settings(settings: dict[str,Any]) -> dict:
    cur=get_security_settings(); cur.update(settings or {})
    minutes = cur.get("idle_timeout_minutes", cur.get("idle_auto_logout_minutes", 15))
    cur["idle_timeout_minutes"] = int(float(minutes or 15))
    cur["idle_auto_logout_minutes"] = cur["idle_timeout_minutes"]
    payload={"authority_schema":"SPT_SECURITY_RUNTIME_SETTINGS_V1","updated_at":now_text(),"security_settings":cur, **cur}
    _atomic_write_json(SECURITY_FILE, payload)
    data=_payload(); t=_tables(data)
    rows=[]
    for k,v in cur.items(): rows.append({"setting_key":k,"setting_value":str(v),"updated_at":now_text()})
    t["auth_security_settings"]=rows; t["security_settings"]=rows
    res=_write_payload(data, "save_security_settings_direct_authority")
    res["saved"] = len(rows)
    return res

def add_login_log(username: str, event_type: str, result: str, message: str="", module_code: str="", module_name: str="") -> None:
    LOGIN_JSONL.parent.mkdir(parents=True, exist_ok=True)
    row={"ts":now_text(),"username":username,"event_type":event_type,"result":result,"message":message,"module_code":module_code,"module_name":module_name}
    with LOGIN_JSONL.open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')

def get_login_logs(start_date: str|None=None, end_date: str|None=None) -> list[dict[str,Any]]:
    rows=[]
    if LOGIN_JSONL.exists():
        for line in LOGIN_JSONL.read_text(encoding='utf-8').splitlines():
            try: rows.append(json.loads(line))
            except Exception: pass
    return rows

def delete_login_logs(start_date: str, end_date: str) -> int:
    rows=get_login_logs(); kept=[]; deleted=0
    for r in rows:
        d=str(r.get('ts',''))[:10]
        if start_date <= d <= end_date: deleted += 1
        else: kept.append(r)
    LOGIN_JSONL.parent.mkdir(parents=True, exist_ok=True)
    LOGIN_JSONL.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in kept), encoding='utf-8')
    return deleted

# compatibility no-ops
def connect_db():
    import sqlite3
    p=PROJECT_ROOT/'data'/'permanent_store'/'database'/'spt_time_tracking.db'; p.parent.mkdir(parents=True, exist_ok=True); return sqlite3.connect(str(p))
def clear_permission_runtime_cache(): return None
def sync_auth_users_to_runtime_security(usernames=None): return {"ok": True, "skipped": True}
def permission_recovery_diagnostic(): return {"ok": True, "authority_file": str(AUTH_FILE), "users": len(get_users())}
def permission_password_emergency_recovery(): return {"ok": True, "skipped": True}
def force_restore_admin_password_v30017_4():
    return save_users([{"username":"admin","new_password":"Admin@1234","display_name":"系統管理員","role_code":"admin","is_active":1}])
