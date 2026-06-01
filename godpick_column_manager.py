# -*- coding: utf-8 -*-
"""
godpick_column_manager.py
v130：欄位順序文字框自動同步新欄位版

用途：
- 讓 07 股神推薦、08 股神推薦紀錄、10 推薦清單、11 資料診斷、12 股神管理中心
  所有 st.dataframe / st.data_editor 表格都套用同一套欄位管理方式。
- 支援欄位顯示 / 隱藏 / 排序 / 快速模板 / 只保留有資料欄位。
- 設定永久保存到 godpick_management_ui_config.json；若 GitHub Token 正常，也會同步寫回 GitHub。
- 對 data_editor 採「畫面欄位管理、回傳完整資料」策略，避免隱藏欄位後造成匯入/刪除/同步功能壞掉。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from datetime import datetime
import base64
import json

import pandas as pd
import streamlit as st

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "godpick_management_ui_config.json"
CONFIG_VERSION = "v130"
EMPTY_VALUES = {"", "None", "none", "nan", "NaN", "null", "NULL", "<NA>"}


def _is_empty_value(v: Any) -> bool:
    if v is None:
        return True
    try:
        if pd.isna(v):
            return True
    except Exception:
        pass
    return str(v).strip() in EMPTY_VALUES


def safe_text(v: Any, blank: str = "") -> str:
    if _is_empty_value(v):
        return blank
    if isinstance(v, (dict, list, tuple, set)):
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return str(v)
    return str(v)


def _safe_col_name(c: Any) -> str:
    s = str(c).strip()
    return s if s else "未命名欄位"


def clean_display_df(df: pd.DataFrame, hide_empty_columns: bool = False) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [_safe_col_name(c) for c in out.columns]
    out = out.loc[:, ~out.columns.duplicated()].copy()
    for c in out.columns:
        if out[c].dtype == "object":
            out[c] = out[c].map(lambda x: "" if _is_empty_value(x) else x)
        else:
            out[c] = out[c].where(~out[c].isna(), "")
    if hide_empty_columns:
        keep: List[str] = []
        for c in out.columns:
            s = out[c].map(lambda x: "" if _is_empty_value(x) else str(x).strip())
            if s.ne("").any():
                keep.append(c)
        out = out[keep] if keep else out.iloc[:, :0]
    return out


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _default_config() -> Dict[str, Any]:
    return {"version": CONFIG_VERSION, "updated_at": "", "profiles": {}}


def _normalize_config(payload: Any) -> Dict[str, Any]:
    cfg = _default_config()
    if isinstance(payload, dict):
        cfg.update({k: v for k, v in payload.items() if k != "profiles"})
        profiles = payload.get("profiles", {}) if isinstance(payload.get("profiles", {}), dict) else {}
        fixed: Dict[str, Any] = {}
        for key, prof in profiles.items():
            if not isinstance(prof, dict):
                continue
            fixed[str(key)] = {
                "label": str(prof.get("label", str(key))),
                "columns": [str(x) for x in prof.get("columns", []) if str(x).strip()],
                "hidden": [str(x) for x in prof.get("hidden", []) if str(x).strip()],
                "updated_at": str(prof.get("updated_at", "")),
            }
        cfg["profiles"] = fixed
    cfg["version"] = CONFIG_VERSION
    return cfg


def _read_local_config() -> Dict[str, Any]:
    try:
        if CONFIG_PATH.exists():
            txt = CONFIG_PATH.read_text(encoding="utf-8")
            if txt.strip():
                return _normalize_config(json.loads(txt))
    except Exception:
        pass
    return _default_config()


def _write_local_config(payload: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, f"本機已儲存：{CONFIG_PATH.name}"
    except Exception as exc:
        return False, f"本機儲存失敗：{exc}"


def _github_cfg() -> Dict[str, str]:
    try:
        secrets = st.secrets
    except Exception:
        secrets = {}
    return {
        "token": str(secrets.get("GITHUB_TOKEN", "")),
        "owner": str(secrets.get("GITHUB_REPO_OWNER", "cheng07021028")),
        "repo": str(secrets.get("GITHUB_REPO_NAME", "stock-app")),
        "branch": str(secrets.get("GITHUB_REPO_BRANCH", "main")),
        "path": str(secrets.get("GODPICK_MANAGEMENT_UI_CONFIG_GITHUB_PATH", "godpick_management_ui_config.json")),
    }


def _github_url(owner: str, repo: str, path: str) -> str:
    return f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"


def _github_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _read_github_config() -> Tuple[Dict[str, Any], str]:
    """v39：頁面載入時不主動讀 GitHub。

    原因：7/8/10/11/12 每個頁面都有多張表，如果每次 rerun 都向 GitHub
    讀取欄位設定，Streamlit Cloud 會明顯變慢。

    正確流程：
    - 平常讀取 repo 內的 godpick_management_ui_config.json，本機/雲端都很快。
    - 使用者按「套用並永久記錄」時，才寫入 GitHub。
    - GitHub 重新部署後，設定檔會跟著 repo 進來。
    """
    return _default_config(), "v39：頁面載入不讀 GitHub，避免每頁卡頓；套用欄位設定時才寫回 GitHub。"


def _write_github_config(payload: Dict[str, Any]) -> Tuple[bool, str]:
    cfg = _github_cfg()
    token = cfg.get("token", "")
    if not token or requests is None:
        return False, "未設定 GITHUB_TOKEN，已跳過 GitHub 永久寫入。"
    try:
        url = _github_url(cfg["owner"], cfg["repo"], cfg["path"])
        headers = _github_headers(token)
        sha = ""
        get_resp = requests.get(url, headers=headers, params={"ref": cfg["branch"]}, timeout=12)
        if get_resp.status_code == 200:
            sha = get_resp.json().get("sha", "")
        body = {
            "message": f"Update godpick column config {payload.get('updated_at', '')}",
            "content": base64.b64encode(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")).decode("ascii"),
            "branch": cfg["branch"],
        }
        if sha:
            body["sha"] = sha
        put_resp = requests.put(url, headers=headers, json=body, timeout=20)
        if put_resp.status_code in (200, 201):
            return True, f"GitHub 已永久儲存：{cfg['path']}"
        return False, f"GitHub 寫入失敗：{put_resp.status_code}"
    except Exception as exc:
        return False, f"GitHub 寫入例外：{exc}"


def _config_ts(payload: Dict[str, Any]) -> str:
    return str(payload.get("updated_at", "")) if isinstance(payload, dict) else ""


@st.cache_data(show_spinner=False, ttl=300)
def _load_config_cached(_seq: int = 0) -> Tuple[Dict[str, Any], str]:
    local = _read_local_config()
    _, gh_msg = _read_github_config()
    return local, f"使用 repo 內欄位設定。{gh_msg}"


def load_column_config() -> Dict[str, Any]:
    seq = int(st.session_state.get("godpick_column_config_refresh_seq", 0))
    cfg, _ = _load_config_cached(seq)
    return cfg


def save_column_config(config: Dict[str, Any]) -> bool:
    config = _normalize_config(config)
    config["version"] = CONFIG_VERSION
    config["updated_at"] = _now_text()
    local_ok, _ = _write_local_config(config)
    gh_ok, _ = _write_github_config(config)
    st.session_state["godpick_column_config_refresh_seq"] = int(st.session_state.get("godpick_column_config_refresh_seq", 0)) + 1
    try:
        _load_config_cached.clear()
    except Exception:
        pass
    return bool(local_ok or gh_ok)


def unique_existing_columns(cols: Iterable[str], df: Optional[pd.DataFrame] = None) -> List[str]:
    seen, out = set(), []
    available = set(df.columns) if isinstance(df, pd.DataFrame) else None
    for c in cols or []:
        c = str(c)
        if not c or c in seen:
            continue
        if available is not None and c not in available:
            continue
        seen.add(c)
        out.append(c)
    return out


def _non_empty_columns(df: pd.DataFrame, cols: List[str]) -> List[str]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return cols[:]
    out: List[str] = []
    for c in cols:
        if c not in df.columns:
            continue
        s = df[c].map(lambda x: "" if _is_empty_value(x) else str(x).strip())
        if s.ne("").any():
            out.append(c)
    return out


def column_templates(all_cols: Iterable[str]) -> Dict[str, List[str]]:
    all_cols = list(all_cols or [])
    return {
        "核心推薦欄位": ["勾選", "匯入自選", "刪除", "推薦日期", "推薦時間", "股票代號", "股票名稱", "市場別", "類別", "產業", "推薦模式", "推薦等級", "推薦分數", "股神決策分數", "買點分級", "最新價", "推薦價格"],
        "操作與倉位欄位": ["v21操作優先順序", "追蹤分級", "今日操作建議", "建議動作", "股神建議動作", "股神信心", "進場時機", "股神進場區間", "等待條件", "建議倉位%", "動態建議倉位%", "第一筆進場%", "分批策略"],
        "風控停利停損欄位": ["高風險狀態", "品質分級", "品質建議", "風險說明", "停損價", "停損參考", "停利目標", "賣出目標1", "賣出目標2", "最大回撤%", "風險報酬比", "R/R", "等待條件"],
        "族群大盤欄位": ["類別", "產業", "族群資金說明", "族群策略建議", "族群資金流分數", "族群資金流說明", "族群輪動狀態", "大盤情境分析", "大盤情境調權說明", "大盤策略建議", "大盤風控", "大盤交易時段"],
        "績效追蹤欄位": ["推薦後1日%", "推薦後1日勝率", "推薦後3日%", "推薦後3日勝率", "推薦後5日%", "推薦後5日勝率", "推薦後10日%", "推薦後10日勝率", "推薦後20日%", "推薦後20日勝率", "最大漲幅%", "最大回撤%", "目前績效%"],
        "全部欄位": all_cols,
    }


def get_table_columns(table_key: str, default_cols: Iterable[str], df: Optional[pd.DataFrame] = None) -> List[str]:
    cfg = load_column_config()
    prof = cfg.get("profiles", {}).get(table_key, {}) if isinstance(cfg.get("profiles", {}), dict) else {}
    saved = prof.get("columns", []) if isinstance(prof, dict) else []
    candidates = list(df.columns) if isinstance(df, pd.DataFrame) else list(default_cols or [])
    if saved:
        cols = [c for c in saved if c in candidates]
        for c in default_cols or []:
            if c in candidates and c not in cols:
                cols.append(c)
        return cols or candidates
    return unique_existing_columns(default_cols, df) or candidates


def set_table_columns(table_key: str, columns: Iterable[str], template: str = "custom", label: str = "") -> bool:
    cfg = load_column_config()
    cfg.setdefault("profiles", {})[table_key] = {
        "label": label or table_key,
        "columns": [str(c) for c in columns if str(c).strip()],
        "hidden": [],
        "template": template,
        "updated_at": _now_text(),
    }
    return save_column_config(cfg)



def _key_safe(s: str) -> str:
    return str(s).replace(" ", "_").replace("/", "_").replace(":", "_").replace("｜", "_").replace("\\", "_")


def _parse_column_text(raw: str, candidates: List[str]) -> List[str]:
    """將文字排序清單轉成有效欄位；支援一行一欄、逗號、tab。"""
    if not raw:
        return []
    parts: List[str] = []
    for line in str(raw).replace("\t", "\n").replace(",", "\n").replace("，", "\n").splitlines():
        c = line.strip()
        if c:
            parts.append(c)
    valid = []
    seen = set()
    cand = set(candidates)
    for c in parts:
        if c in cand and c not in seen:
            valid.append(c)
            seen.add(c)
    return valid




def _sync_column_order_text(text_key: str, current: List[str], candidates: List[str]) -> None:
    """v130：欄位管理文字框自動同步新欄位。

    舊版問題：使用者保存過欄位順序後，後續 07/08/10/14 新增欄位
    雖然表格候選欄位已出現，但 text_area 仍保留舊 session 內容，
    看起來像「欄位順序沒有同步新增欄位」。

    修正方式：保留使用者既有排序，把目前應顯示但文字框缺少的新欄位
    自動補到最後；不會打亂已保存順序。
    """
    cand = list(dict.fromkeys([str(c) for c in candidates if str(c).strip()]))
    cur = [str(c) for c in current if str(c).strip() and str(c) in cand]
    raw = st.session_state.get(text_key, "")

    if raw is None or not str(raw).strip():
        st.session_state[text_key] = "\n".join(cur)
        return

    parsed = _parse_column_text(str(raw), cand)
    if not parsed:
        st.session_state[text_key] = "\n".join(cur)
        return

    # 保留使用者文字框既有順序，補上 current 中已顯示但未列入文字框的欄位。
    merged = [c for c in parsed if c in cand]
    seen = set(merged)
    missing_from_current = [c for c in cur if c not in seen]
    if missing_from_current:
        merged.extend(missing_from_current)
        st.session_state[text_key] = "\n".join(merged)


def render_column_manager(table_key: str, table_label: str, df: pd.DataFrame, default_cols: Optional[Iterable[str]] = None) -> List[str]:
    """v48：統一操作樣式，但各模組 / 各主表獨立保存欄位設定。

    設計原則：
    - 平常只讀取已保存欄位，不顯示管理 UI，避免拖慢頁面。
    - 開啟側邊欄「欄位管理模式」後，才顯示與 12_股神管理中心一致的表單式欄位管理。
    - 欄位順序、搜尋、模板、隱藏空欄全部放在 st.form 裡。
    - 輸入/剪貼欄位順序時不解析、不保存；只有按按鈕才套用。
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []

    clean = clean_display_df(df, hide_empty_columns=False)
    candidates = list(clean.columns)
    default_cols = list(default_cols or candidates)
    current = get_table_columns(table_key, default_cols, clean)
    current = [c for c in current if c in candidates] or candidates[:]

    safe_key = _key_safe(table_key)
    preview_key = f"{safe_key}_preview_cols_v47"
    text_key = f"{safe_key}_order_text_v47"

    preview_cols = st.session_state.get(preview_key)
    if isinstance(preview_cols, list) and preview_cols:
        current = [c for c in preview_cols if c in candidates] or current

    # 平常模式：只套用設定，不顯示欄位管理器。
    if not bool(st.session_state.get("godpick_column_manager_edit_mode", False)):
        return current

    with st.expander(f"🧩 {table_label} 欄位管理 / v48 個別模組設定", expanded=False):
        st.caption("與股神管理中心相同方式：欄位順序一行一欄；輸入過程不運算，只有按『套用』才解析、重排與保存。")
        st.caption(f"目前顯示 **{len(current)}** 欄 / 可用 **{len(candidates)}** 欄。")

        # v130：舊欄位順序文字框若缺少新版本欄位，自動補到最後。
        _sync_column_order_text(text_key, current, candidates)

        templates = column_templates(candidates)
        with st.form(key=f"{safe_key}_column_form_v47", clear_on_submit=False):
            c0, c1, c2 = st.columns([1.2, 1.3, 1.0])
            with c0:
                preset = st.selectbox(
                    "快速模板",
                    ["目前設定", "全部欄位", "只保留有資料欄位"] + [k for k in templates.keys() if k not in ("全部欄位",)],
                    key=f"{safe_key}_preset_v47",
                )
            with c1:
                keyword = st.text_input("欄位搜尋", key=f"{safe_key}_kw_v47", placeholder="輸入欄位關鍵字")
            with c2:
                hide_empty_choice = st.checkbox("套用時隱藏全空欄", value=False, key=f"{safe_key}_hide_empty_v47")

            visible_options = [c for c in candidates if (not keyword or keyword in c)]
            selected_default = [c for c in current if c in visible_options]
            selected_cols = st.multiselect(
                "顯示欄位（可用搜尋縮小範圍；實際順序以下方文字框為準）",
                options=visible_options,
                default=selected_default,
                key=f"{safe_key}_selected_cols_v47",
            )
            order_text = st.text_area(
                "欄位順序（一行一欄；可直接剪下貼上調整）",
                key=text_key,
                height=320,
                help="v48：輸入時不即時計算；按套用後才重排欄位；每個模組獨立保存。",
            )

            b1, b2, b3, b4 = st.columns(4)
            apply_btn = b1.form_submit_button("✅ 套用並永久記錄", type="primary", use_container_width=True)
            preview_btn = b2.form_submit_button("👁️ 套用到本次畫面", use_container_width=True)
            reset_btn = b3.form_submit_button("↩️ 恢復系統預設", use_container_width=True)
            nonempty_btn = b4.form_submit_button("🧹 只保留有資料欄", use_container_width=True)

        submitted = apply_btn or preview_btn or reset_btn or nonempty_btn
        if not submitted:
            st.info("調整完欄位順序後，請按『套用並永久記錄』；輸入過程不會觸發表格重算。")
            return current

        if reset_btn:
            final_cols = [c for c in default_cols if c in candidates] or candidates[:]
        elif nonempty_btn:
            final_cols = _non_empty_columns(clean, candidates) or current[:]
        else:
            if preset == "全部欄位":
                base_cols = candidates[:]
            elif preset == "只保留有資料欄位":
                base_cols = _non_empty_columns(clean, candidates) or current[:]
            elif preset in templates:
                base_cols = [c for c in templates[preset] if c in candidates]
                for c in current:
                    if c in candidates and c not in base_cols:
                        base_cols.append(c)
            else:
                base_cols = current[:]

            if hide_empty_choice:
                non_empty = set(_non_empty_columns(clean, candidates))
                base_cols = [c for c in base_cols if c in non_empty] or current[:1] or candidates[:1]

            parsed_order = _parse_column_text(order_text, candidates)
            selected_set = set(selected_cols) if selected_cols else set(parsed_order or base_cols)
            final_cols = [c for c in parsed_order if c in selected_set]
            for c in selected_cols:
                if c in candidates and c not in final_cols:
                    final_cols.append(c)
            if not final_cols:
                final_cols = [c for c in base_cols if c in candidates] or current[:1] or candidates[:1]

        if not final_cols:
            st.error("至少要保留 1 個欄位。")
            return current

        st.session_state[preview_key] = final_cols

        if preview_btn or reset_btn or nonempty_btn:
            st.success("已套用到本次畫面；未強制整頁重跑。若要永久保存，請再按『套用並永久記錄』。")
            return final_cols

        if apply_btn:
            cfg = load_column_config()
            cfg = _normalize_config(cfg)
            cfg.setdefault("profiles", {})[table_key] = {
                "label": table_label,
                "columns": final_cols,
                "hidden": [c for c in candidates if c not in final_cols],
                "updated_at": _now_text(),
            }
            ok = save_column_config(cfg)
            if ok:
                st.success(f"{table_label} 欄位設定已套用並永久記錄；未強制整頁重跑。")
            else:
                st.warning(f"{table_label} 欄位設定已嘗試儲存，但可能未完全寫入；未強制整頁重跑。")
            return final_cols

    return current

def apply_columns(df: pd.DataFrame, table_key: str, default_cols: Iterable[str], hide_empty_columns: bool = False) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    clean = clean_display_df(df, hide_empty_columns=False)
    cols = get_table_columns(table_key, default_cols, clean)
    out = clean[cols].copy() if cols else clean.copy()
    if hide_empty_columns:
        out = clean_display_df(out, hide_empty_columns=True)
    return out



# =========================================================
# v105：全系統表格篩選 / 排序 / 勾選延後套用
# =========================================================
def _view_profiles(config: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    views = config.setdefault("table_views", {})
    if not isinstance(views, dict):
        config["table_views"] = {}
        views = config["table_views"]
    return views


def _default_table_view(df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    cols = list(df.columns) if isinstance(df, pd.DataFrame) else []
    return {
        "keyword": "",
        "keyword_columns": [],
        "filters": {},
        "sort_column": "",
        "sort_ascending": False,
        "limit_rows": 0,
        "updated_at": "",
    }


def get_table_view_config(table_key: str, df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    cfg = load_column_config()
    views = cfg.get("table_views", {}) if isinstance(cfg.get("table_views", {}), dict) else {}
    raw = views.get(table_key, {}) if isinstance(views, dict) else {}
    view = _default_table_view(df)
    if isinstance(raw, dict):
        view.update(raw)
    # 清掉不存在欄位，避免舊設定造成錯誤。
    if isinstance(df, pd.DataFrame):
        available = set(map(str, df.columns))
        view["keyword_columns"] = [c for c in view.get("keyword_columns", []) if c in available]
        if view.get("sort_column") not in available:
            view["sort_column"] = ""
        filters = view.get("filters", {}) if isinstance(view.get("filters", {}), dict) else {}
        view["filters"] = {k: v for k, v in filters.items() if k in available}
    return view


def save_table_view_config(table_key: str, view: Dict[str, Any], label: str = "") -> bool:
    cfg = load_column_config()
    cfg = _normalize_config(cfg)
    views = _view_profiles(cfg)
    payload = dict(view or {})
    payload["label"] = label or table_key
    payload["updated_at"] = _now_text()
    views[table_key] = payload
    return save_column_config(cfg)


def _series_as_text(s: pd.Series) -> pd.Series:
    try:
        return s.map(lambda x: "" if _is_empty_value(x) else str(x))
    except Exception:
        return pd.Series([""] * len(s), index=s.index)


def _safe_to_numeric(s: pd.Series) -> pd.Series:
    try:
        return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False), errors="coerce")
    except Exception:
        return pd.to_numeric(s, errors="coerce")


def apply_table_view(df: pd.DataFrame, table_key: str) -> pd.DataFrame:
    """只對目前已存在的 DataFrame 做輕量篩選 / 排序，不重新抓資料、不重跑推薦。"""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame() if df is None else df
    out = df.copy()
    view = get_table_view_config(table_key, out)

    keyword = safe_text(view.get("keyword", "")).strip()
    if keyword:
        kw_cols = [c for c in view.get("keyword_columns", []) if c in out.columns]
        if not kw_cols:
            kw_cols = list(out.columns)
        mask = pd.Series(False, index=out.index)
        for c in kw_cols:
            try:
                mask = mask | _series_as_text(out[c]).str.contains(keyword, case=False, na=False, regex=False)
            except Exception:
                pass
        out = out.loc[mask].copy()

    filters = view.get("filters", {}) if isinstance(view.get("filters", {}), dict) else {}
    for c, vals in filters.items():
        if c not in out.columns:
            continue
        if not isinstance(vals, list) or not vals:
            continue
        wanted = set(str(v) for v in vals)
        out = out[_series_as_text(out[c]).isin(wanted)].copy()

    sort_col = safe_text(view.get("sort_column", "")).strip()
    if sort_col and sort_col in out.columns:
        asc = bool(view.get("sort_ascending", False))
        try:
            numeric = _safe_to_numeric(out[sort_col])
            if numeric.notna().sum() >= max(1, int(len(out) * 0.6)):
                out = out.assign(_godpick_sort_tmp_=numeric).sort_values("_godpick_sort_tmp_", ascending=asc, na_position="last").drop(columns=["_godpick_sort_tmp_"])
            else:
                out = out.sort_values(sort_col, ascending=asc, na_position="last")
        except Exception:
            try:
                out = out.sort_values(sort_col, ascending=asc, na_position="last")
            except Exception:
                pass

    try:
        limit = int(view.get("limit_rows", 0) or 0)
    except Exception:
        limit = 0
    if limit > 0:
        out = out.head(limit).copy()
    return out


def _candidate_filter_columns(df: pd.DataFrame, max_cols: int = 80) -> List[str]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    preferred = []
    for c in df.columns:
        name = str(c)
        if any(k in name for k in ["群組", "市場", "類別", "產業", "狀態", "等級", "模式", "成功", "訊息", "來源", "日期", "股票代號", "股票名稱"]):
            preferred.append(c)
    others = [c for c in df.columns if c not in preferred]
    return (preferred + others)[:max_cols]


def render_table_view_manager(table_key: str, table_label: str, df: pd.DataFrame) -> Dict[str, Any]:
    """v114：所有表格共用的篩選 / 排序表單；只有按套用才永久記錄。"""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return _default_table_view(df)
    if not bool(st.session_state.get("godpick_table_filter_sort_enabled", True)):
        return get_table_view_config(table_key, df)

    safe_key = _key_safe(table_key)
    clean = clean_display_df(df, hide_empty_columns=False)
    cols = list(clean.columns)
    current = get_table_view_config(table_key, clean)

    with st.expander(f"🔎 {table_label}｜篩選 / 排序 / 永久記錄 v116", expanded=False):
        st.caption("輸入篩選、排序或勾選條件時不重算資料；只有按『套用並永久記錄』後，才套用到目前表格顯示。")
        with st.form(key=f"{safe_key}_table_view_form_v105", clear_on_submit=False):
            c1, c2, c3, c4 = st.columns([1.3, 1.4, 1.1, 0.8])
            with c1:
                keyword = st.text_input("關鍵字篩選", value=safe_text(current.get("keyword", "")), key=f"{safe_key}_view_kw_v105")
            with c2:
                kw_cols = st.multiselect(
                    "關鍵字搜尋欄位（空白=全部欄）",
                    options=cols,
                    default=[c for c in current.get("keyword_columns", []) if c in cols],
                    key=f"{safe_key}_view_kw_cols_v105",
                )
            with c3:
                sort_col = st.selectbox(
                    "排序欄位",
                    options=[""] + cols,
                    index=([""] + cols).index(current.get("sort_column", "")) if current.get("sort_column", "") in cols else 0,
                    key=f"{safe_key}_view_sort_col_v105",
                )
            with c4:
                sort_mode = st.selectbox(
                    "排序方式",
                    options=["大到小 / 新到舊", "小到大 / 舊到新"],
                    index=1 if bool(current.get("sort_ascending", False)) else 0,
                    key=f"{safe_key}_view_sort_mode_v105",
                )

            filter_cols = st.multiselect(
                "要啟用的欄位篩選（最多建議 5 欄，避免畫面太長）",
                options=_candidate_filter_columns(clean),
                default=[c for c in current.get("filters", {}).keys() if c in clean.columns],
                key=f"{safe_key}_view_filter_cols_v105",
            )
            new_filters: Dict[str, List[str]] = {}
            for c in filter_cols[:8]:
                try:
                    vals = _series_as_text(clean[c]).replace("", pd.NA).dropna().value_counts().head(200).index.tolist()
                except Exception:
                    vals = []
                old_vals = current.get("filters", {}).get(c, []) if isinstance(current.get("filters", {}), dict) else []
                old_vals = [v for v in old_vals if v in vals]
                selected = st.multiselect(
                    f"{c} 篩選值",
                    options=vals,
                    default=old_vals,
                    key=f"{safe_key}_filter_{_key_safe(c)}_v105",
                )
                if selected:
                    new_filters[c] = [str(x) for x in selected]

            limit_default = int(current.get("limit_rows", 0) or 0) if str(current.get("limit_rows", 0)).isdigit() else 0
            limit_rows = st.number_input("顯示前 N 筆（0=全部）", min_value=0, max_value=20000, value=limit_default, step=50, key=f"{safe_key}_limit_v105")

            b1, b2, b3 = st.columns([1, 1, 2])
            apply_btn = b1.form_submit_button("✅ 套用並永久記錄", type="primary", use_container_width=True)
            clear_btn = b2.form_submit_button("🧹 清除篩選排序", use_container_width=True)

        if clear_btn:
            new_view = _default_table_view(clean)
            ok = save_table_view_config(table_key, new_view, table_label)
            st.success("已清除本表格篩選 / 排序設定並永久記錄。" if ok else "已嘗試清除設定，但永久寫入可能失敗。")
            return new_view

        if apply_btn:
            new_view = {
                "keyword": keyword,
                "keyword_columns": [str(c) for c in kw_cols],
                "filters": new_filters,
                "sort_column": sort_col,
                "sort_ascending": sort_mode.startswith("小到大"),
                "limit_rows": int(limit_rows or 0),
            }
            ok = save_table_view_config(table_key, new_view, table_label)
            st.success("篩選 / 排序已套用並永久記錄；只重排目前表格，不重跑推薦或重新抓資料。" if ok else "已套用，但永久寫入可能失敗。")
            return new_view

        active_msg = []
        if current.get("keyword"):
            active_msg.append(f"關鍵字：{current.get('keyword')}")
        if current.get("sort_column"):
            active_msg.append(f"排序：{current.get('sort_column')}")
        if current.get("filters"):
            active_msg.append(f"篩選欄位：{len(current.get('filters', {}))}")
        st.caption("目前已套用：" + ("；".join(active_msg) if active_msg else "無"))
    return current


def _checkbox_like_columns(df: pd.DataFrame) -> List[str]:
    """找出可批次全選 / 取消全選的欄位。

    v114 原則：
    - bool 欄位可批次處理。
    - 欄名含「勾選 / 選取 / 匯入 / 刪除 / 加入 / check / select」也可處理。
    - 不會直接回傳給主程式；只改本表格草稿，按「套用勾選 / 編輯結果」後才生效。
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    out: List[str] = []
    for c in df.columns:
        name = str(c)
        is_bool = False
        try:
            is_bool = str(df[c].dtype) == "bool"
        except Exception:
            is_bool = False
        name_hit = any(k in name for k in ["勾選", "選取", "匯入", "刪除", "加入", "check", "select"])
        if is_bool or name_hit:
            out.append(c)
    return out


def _has_checkbox_like_column(df: pd.DataFrame) -> bool:
    return bool(_checkbox_like_columns(df))


def _default_checkbox_column(cols: List[str]) -> str:
    if not cols:
        return ""
    priority = ["勾選", "選取", "匯入", "加入", "刪除", "check", "select"]
    for p in priority:
        for c in cols:
            if p in str(c):
                return c
    return cols[0]


def _same_table_shape(a: Any, b: pd.DataFrame) -> bool:
    if not isinstance(a, pd.DataFrame) or not isinstance(b, pd.DataFrame):
        return False
    try:
        return list(a.columns) == list(b.columns) and list(a.index) == list(b.index)
    except Exception:
        return False




def _action_button_any_context(label: str, key: str, use_container_width: bool = True) -> bool:
    """v116：表格全選/取消按鈕可在一般頁面或既有 st.form 內使用。

    Streamlit 在 st.form 內不允許 st.button；此函式先嘗試一般 button，
    若遇到 form 限制，改用 form_submit_button，避免自訂表格被包在 form 時
    全選功能消失或造成錯誤。
    """
    try:
        return bool(st.button(label, key=key, use_container_width=use_container_width))
    except Exception:
        try:
            return bool(st.form_submit_button(label, use_container_width=use_container_width))
        except Exception:
            return False

def render_checkbox_bulk_controls(table_key: str, table_label: str, df: pd.DataFrame) -> pd.DataFrame:
    """v116：在含勾選欄位的表格上方加入全選 / 取消全選。

    只操作目前表格顯示的 df 草稿，不執行匯入 / 刪除 / 同步 / 推薦重算。
    真正回傳給原頁面，仍要按 data_editor 下方的「套用勾選 / 編輯結果」。
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    checkbox_cols = _checkbox_like_columns(df)
    if not checkbox_cols:
        return df

    safe_key = _key_safe(table_key)
    draft_key = f"{safe_key}_checkbox_draft_df_v114"
    col_key = f"{safe_key}_checkbox_target_col_v114"

    working = df.copy()
    draft = st.session_state.get(draft_key)
    if _same_table_shape(draft, working):
        # 只帶回勾選欄位，避免把舊草稿中的其他欄位覆蓋新資料。
        for c in checkbox_cols:
            if c in draft.columns and c in working.columns:
                working[c] = draft[c].values

    default_col = st.session_state.get(col_key, _default_checkbox_column(checkbox_cols))
    if default_col not in checkbox_cols:
        default_col = _default_checkbox_column(checkbox_cols)

    with st.container():
        c0, c1, c2, c3 = st.columns([1.5, 1, 1, 2])
        with c0:
            if len(checkbox_cols) > 1:
                target_col = st.selectbox(
                    "批次勾選欄位",
                    options=checkbox_cols,
                    index=checkbox_cols.index(default_col) if default_col in checkbox_cols else 0,
                    key=col_key,
                    help="選擇要全選 / 取消全選的勾選欄位；此動作只改草稿，不會立即匯入或刪除。",
                )
            else:
                target_col = checkbox_cols[0]
                st.caption(f"批次勾選欄位：{target_col}")
        with c1:
            select_all = _action_button_any_context("✅ 勾選全選", key=f"{safe_key}_select_all_v116", use_container_width=True)
        with c2:
            clear_all = _action_button_any_context("⬜ 全部取消", key=f"{safe_key}_clear_all_v116", use_container_width=True)
        with c3:
            st.caption("v116：全選/取消只修改目前顯示草稿；仍需按下方『套用勾選 / 編輯結果』才生效。")

    if select_all or clear_all:
        try:
            working[target_col] = bool(select_all)
            st.session_state[draft_key] = working.copy()
            st.success(f"{table_label}：{target_col} 已{'全選' if select_all else '全部取消'}；尚未觸發主流程，請再按『套用勾選 / 編輯結果』。")
        except Exception as exc:
            st.warning(f"批次勾選失敗：{exc}")
    else:
        st.session_state[draft_key] = working.copy()

    return working


def _merge_edited_subset(original: pd.DataFrame, edited_subset: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(original, pd.DataFrame) or not isinstance(edited_subset, pd.DataFrame):
        return edited_subset
    full = original.copy()
    try:
        common_cols = [c for c in edited_subset.columns if c in full.columns]
        for idx in edited_subset.index:
            if idx in full.index:
                for c in common_cols:
                    full.at[idx, c] = edited_subset.at[idx, c]
        return full
    except Exception:
        return edited_subset


def install_global_table_patch(page_key: str = "global") -> None:
    """v105：全域攔截 st.dataframe / st.data_editor，讓所有表格都有篩選排序，勾選延後套用。"""
    if getattr(st, "_godpick_table_patch_v105", False):
        return
    try:
        original_dataframe = st.dataframe
        original_data_editor = st.data_editor
        st._godpick_original_dataframe_v105 = original_dataframe
        st._godpick_original_data_editor_v105 = original_data_editor
    except Exception:
        return

    def _auto_key(kind: str, user_key: Any = None) -> str:
        if user_key:
            return f"{page_key}_{kind}_{_key_safe(str(user_key))}"
        counter_key = f"_godpick_{page_key}_{kind}_counter_v105"
        n = int(st.session_state.get(counter_key, 0)) + 1
        st.session_state[counter_key] = n
        return f"{page_key}_{kind}_{n}"

    def patched_dataframe(data=None, *args, **kwargs):
        if kwargs.pop("_godpick_bypass", False):
            return original_dataframe(data, *args, **kwargs)
        if isinstance(data, pd.DataFrame) and not data.empty:
            table_key = _auto_key("dataframe", kwargs.get("key"))
            table_label = str(kwargs.get("key") or f"表格 {table_key.split('_')[-1]}")
            try:
                render_table_view_manager(table_key, table_label, data)
                data = apply_table_view(data, table_key)
            except Exception as exc:
                try:
                    st.caption(f"v116 表格篩選排序略過：{exc}")
                except Exception:
                    pass
        return original_dataframe(data, *args, **kwargs)

    def patched_data_editor(data=None, *args, **kwargs):
        if kwargs.pop("_godpick_bypass", False):
            return original_data_editor(data, *args, **kwargs)
        if not isinstance(data, pd.DataFrame) or data.empty:
            return original_data_editor(data, *args, **kwargs)
        table_key = _auto_key("editor", kwargs.get("key"))
        table_label = str(kwargs.get("key") or f"可編輯表格 {table_key.split('_')[-1]}")
        original_df = data.copy()
        try:
            render_table_view_manager(table_key, table_label, original_df)
            show_df = apply_table_view(original_df, table_key)
        except Exception:
            show_df = original_df

        # 有勾選 / 選取欄位時，加入全選 / 取消全選，並放入 form：
        # 勾選過程不回傳給主程式，按套用後才生效。
        if _has_checkbox_like_column(show_df):
            applied_key = f"{table_key}_applied_editor_df_v114"
            form_key = f"{table_key}_deferred_editor_form_v114"
            try:
                show_df = render_checkbox_bulk_controls(table_key, table_label, show_df)
                with st.form(form_key, clear_on_submit=False):
                    edited_show = original_data_editor(show_df, *args, **kwargs)
                    submitted = st.form_submit_button("✅ 套用勾選 / 編輯結果", type="primary", use_container_width=True)
                if submitted and isinstance(edited_show, pd.DataFrame):
                    merged = _merge_edited_subset(original_df, edited_show)
                    st.session_state[applied_key] = merged
                    st.success("已套用本表格勾選 / 編輯結果；套用前不會觸發後續匯入、刪除或重算。")
                    return merged
                saved = st.session_state.get(applied_key)
                if isinstance(saved, pd.DataFrame) and list(saved.columns) == list(original_df.columns):
                    return saved
                return original_df
            except Exception:
                # 若原頁面已在 form 中，避免 nested form 錯誤，退回普通 editor；仍保留全選草稿後的顯示。
                try:
                    show_df = render_checkbox_bulk_controls(table_key, table_label, show_df)
                except Exception:
                    pass
                edited_show = original_data_editor(show_df, *args, **kwargs)
                return _merge_edited_subset(original_df, edited_show)
        edited_show = original_data_editor(show_df, *args, **kwargs)
        return _merge_edited_subset(original_df, edited_show)

    st.dataframe = patched_dataframe
    st.data_editor = patched_data_editor
    st._godpick_table_patch_v105 = True


def uninstall_global_table_patch() -> bool:
    """v116：復原完整表格管理攔截，但保留後續可安裝輕量勾選補丁。"""
    restored = False
    try:
        original_dataframe = getattr(st, "_godpick_original_dataframe_v105", None)
        if original_dataframe is not None:
            st.dataframe = original_dataframe
            restored = True
    except Exception:
        pass
    try:
        original_data_editor = getattr(st, "_godpick_original_data_editor_v105", None)
        if original_data_editor is not None:
            st.data_editor = original_data_editor
            restored = True
    except Exception:
        pass
    try:
        st._godpick_table_patch_v105 = False
    except Exception:
        pass
    return restored


def uninstall_light_checkbox_patch() -> bool:
    """v116：切回完整全域表格管理前，先移除輕量勾選補丁，避免重複顯示。"""
    restored = False
    try:
        original = getattr(st, "_godpick_original_data_editor_v116_light", None)
        if original is not None and getattr(st, "_godpick_light_checkbox_patch_v116", False):
            st.data_editor = original
            restored = True
    except Exception:
        pass
    try:
        st._godpick_light_checkbox_patch_v116 = False
    except Exception:
        pass
    return restored


def install_light_checkbox_patch(page_key: str = "global") -> None:
    """v116：重型頁也要有『全選 / 全部取消』，但不啟動完整表格篩選排序攔截。

    用途：
    - 0/3/7/8/10/14 這類重型頁，完整表格管理會拖慢進頁。
    - 但使用者仍要求所有勾選表格都有全選 / 取消。
    - 因此只輕量攔截 st.data_editor：有勾選欄才顯示全選工具，不做篩選排序、不做欄位管理、不重跑資料。
    """
    if getattr(st, "_godpick_table_patch_v105", False):
        return
    if getattr(st, "_godpick_light_checkbox_patch_v116", False):
        return
    try:
        original_data_editor = st.data_editor
        st._godpick_original_data_editor_v116_light = original_data_editor
    except Exception:
        return

    def _auto_key(user_key: Any = None) -> str:
        if user_key:
            return f"{page_key}_light_editor_{_key_safe(str(user_key))}"
        counter_key = f"_godpick_{page_key}_light_editor_counter_v116"
        n = int(st.session_state.get(counter_key, 0)) + 1
        st.session_state[counter_key] = n
        return f"{page_key}_light_editor_{n}"

    def patched_data_editor(data=None, *args, **kwargs):
        if kwargs.pop("_godpick_bypass", False):
            return original_data_editor(data, *args, **kwargs)
        if not isinstance(data, pd.DataFrame) or data.empty or not _has_checkbox_like_column(data):
            return original_data_editor(data, *args, **kwargs)
        table_key = _auto_key(kwargs.get("key"))
        table_label = str(kwargs.get("key") or f"勾選表格 {table_key.split('_')[-1]}")
        try:
            show_df = render_checkbox_bulk_controls(table_key, table_label, data.copy())
        except Exception:
            show_df = data
        return original_data_editor(show_df, *args, **kwargs)

    st.data_editor = patched_data_editor
    st._godpick_light_checkbox_patch_v116 = True


def managed_dataframe(df: pd.DataFrame, table_key: str, table_label: str, default_cols: Optional[Iterable[str]] = None, hide_empty_columns: bool = False, **kwargs: Any) -> None:
    render_table_view_manager(table_key, table_label, df)
    filtered = apply_table_view(df, table_key)
    cols = render_column_manager(table_key, table_label, filtered, default_cols or (list(filtered.columns) if isinstance(filtered, pd.DataFrame) else []))
    show = apply_columns(filtered, table_key, cols or (list(filtered.columns) if isinstance(filtered, pd.DataFrame) else []), hide_empty_columns=hide_empty_columns)
    kwargs["_godpick_bypass"] = True
    return st.dataframe(show, **kwargs)


def managed_data_editor(df: pd.DataFrame, table_key: str, table_label: str, default_cols: Optional[Iterable[str]] = None, hide_empty_columns: bool = False, **kwargs: Any) -> Any:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        kwargs["_godpick_bypass"] = True
        return st.data_editor(df, **kwargs)
    original = df.copy()
    render_table_view_manager(table_key, table_label, original)
    filtered = apply_table_view(original, table_key)
    cols = render_column_manager(table_key, table_label, filtered, default_cols or list(filtered.columns))
    show = apply_columns(filtered, table_key, cols or list(filtered.columns), hide_empty_columns=hide_empty_columns)
    cfg = kwargs.get("column_config")
    if isinstance(cfg, dict):
        kwargs["column_config"] = {k: v for k, v in cfg.items() if k in show.columns}
    kwargs["_godpick_bypass"] = True

    if _has_checkbox_like_column(show):
        safe_key = _key_safe(table_key)
        applied_key = f"{safe_key}_managed_applied_editor_df_v114"
        form_key = f"{safe_key}_managed_deferred_editor_form_v114"
        show = render_checkbox_bulk_controls(table_key, table_label, show)
        try:
            with st.form(form_key, clear_on_submit=False):
                edited = st.data_editor(show, **kwargs)
                submitted = st.form_submit_button("✅ 套用勾選 / 編輯結果", type="primary", use_container_width=True)
            if submitted and isinstance(edited, pd.DataFrame):
                merged = _merge_edited_subset(original, edited)
                st.session_state[applied_key] = merged
                st.success(f"{table_label} 勾選 / 編輯結果已套用；套用前不會觸發匯入、刪除或重算。")
                return merged
            saved = st.session_state.get(applied_key)
            if isinstance(saved, pd.DataFrame) and list(saved.columns) == list(original.columns):
                return saved
            return original
        except Exception:
            # 原頁若已經包在 form 內，不能再巢狀 form；退回普通 editor，但全選/取消草稿仍可顯示。
            edited = st.data_editor(show, **kwargs)
            return _merge_edited_subset(original, edited) if isinstance(edited, pd.DataFrame) else edited

    edited = st.data_editor(show, **kwargs)
    return _merge_edited_subset(original, edited) if isinstance(edited, pd.DataFrame) else edited






# =========================================================
# v112：重型頁面防卡設定
# =========================================================
# 這些頁面通常包含大量資料抓取、K線圖、推薦掃描、績效回補或 GitHub/Firestore 同步。
# 全域 monkey patch 表格管理若在進頁時自動攔截，會讓尚未按「推薦 / 更新 / 套用」就開始建立大量 widget，
# 甚至上一頁殘留的 patch 也會讓本頁繼續卡住。v110 對這些頁面預設先復原攔截。
HEAVY_AUTO_PATCH_PAGE_MARKERS = [
    "0_大盤趨勢", "00_大盤趨勢", "大盤趨勢",
    "1_儀表板", "01_儀表板", "儀表板",
    "2_行情查詢", "02_行情查詢", "行情查詢",
    "3_歷史K線分析", "03_歷史K線分析", "歷史K線分析",
    "4_自選股中心", "04_自選股中心", "自選股中心",
    "5_排行榜", "05_排行榜", "排行榜",
    "6_多股比較", "06_多股比較", "多股比較",
    "7_股神推薦", "07_股神推薦", "股神推薦.py",
    "8_股神推薦紀錄", "08_股神推薦紀錄", "股神推薦紀錄",
    "9_股票主檔更新", "09_股票主檔更新", "股票主檔更新",
    "10_推薦清單", "推薦清單",
    "11_資料診斷", "資料診斷",
    "12_股神管理中心", "股神管理中心",
    "14_股神權重校正", "股神權重校正",
]

def _is_heavy_auto_patch_page(page_key: str = "") -> bool:
    text = str(page_key or "")
    try:
        import inspect
        for frame in inspect.stack()[1:24]:
            fn = str(getattr(frame, "filename", "") or "")
            text += "|" + fn.replace("\\", "/")
    except Exception:
        pass
    return any(m in text for m in HEAVY_AUTO_PATCH_PAGE_MARKERS)

def _heavy_page_force_enabled(page_key: str = "") -> bool:
    safe = _key_safe(page_key or "global")
    return bool(st.session_state.get(f"godpick_force_auto_table_patch_{safe}", False))

def _render_heavy_page_guard(page_key: str = "") -> bool:
    """回傳 True 代表本頁允許安裝全域攔截；False 代表防卡暫停並復原舊攔截。

    v112：防卡邏輯與顯示分離。這裡只負責判斷與還原 monkey patch；
    側邊欄只由 _render_heavy_guard_sidebar_once() 顯示一次，避免完全消失或重複出現。
    """
    if not _is_heavy_auto_patch_page(page_key):
        st.session_state["_godpick_heavy_guard_status_v110"] = {"heavy": False, "restored": False, "page_key": str(page_key or "global")}
        return True

    safe = _key_safe(page_key or "global")
    if _heavy_page_force_enabled(page_key):
        st.session_state["_godpick_heavy_guard_status_v110"] = {"heavy": True, "enabled": True, "restored": False, "page_key": str(page_key or "global")}
        return True

    restored = uninstall_global_table_patch()
    st.session_state["_godpick_heavy_guard_status_v110"] = {"heavy": True, "enabled": False, "restored": bool(restored), "page_key": str(page_key or "global")}
    return False



def _render_heavy_guard_sidebar_once(page_key: str = "") -> None:
    """v112：側邊欄只顯示一個「重型模組防卡模式」。

    v110 把防卡狀態整合進表格管理，使用者會以為防卡模式消失；
    v111 改回獨立面板，但用 session flag 去重，避免 v108 那種重複兩個區塊。
    """
    try:
        if bool(st.session_state.get("_godpick_heavy_guard_sidebar_rendered_this_run_v111", False)):
            return
        guard_status = st.session_state.get("_godpick_heavy_guard_status_v110", {})
        if not isinstance(guard_status, dict) or not guard_status.get("heavy"):
            return
        st.session_state["_godpick_heavy_guard_sidebar_rendered_this_run_v111"] = True
        safe_guard = _key_safe(str(guard_status.get("page_key") or page_key or "global"))
        with st.sidebar.expander("⚡ 重型模組防卡模式｜v116", expanded=False):
            st.caption("重型頁面預設不自動攔截所有表格，避免進頁就卡住；需要表格篩選排序時，可本次手動啟用。")
            if guard_status.get("enabled"):
                st.warning("本頁已手動啟用全域表格管理；若進頁或操作變慢，請恢復防卡。")
                if st.button("恢復防卡並重新整理", key=f"{safe_guard}_restore_heavy_guard_v111", use_container_width=True):
                    st.session_state[f"godpick_force_auto_table_patch_{safe_guard}"] = False
                    uninstall_global_table_patch()
                    st.rerun()
            else:
                st.success("防卡已啟用：本頁不會自動攔截所有 st.dataframe / st.data_editor。")
                if guard_status.get("restored"):
                    st.info("已清除上一頁殘留的表格攔截。")
                if st.button("本次手動啟用全域表格管理", key=f"{safe_guard}_force_auto_table_patch_v111", use_container_width=True):
                    st.session_state[f"godpick_force_auto_table_patch_{safe_guard}"] = True
                    st.rerun()
            st.caption("說明：重型防卡只影響全域表格攔截，不會停用各頁本身的更新、推薦、績效或同步功能。")
    except Exception:
        return


# =========================================================
# v112：全域表格管理設定（永久保存）
# =========================================================
def _default_global_options() -> Dict[str, Any]:
    return {
        "table_filter_sort_enabled": True,
        "column_manager_edit_mode": False,
        "auto_sidebar_enabled": True,
        "updated_at": "",
    }


def get_global_table_options() -> Dict[str, Any]:
    cfg = load_column_config()
    raw = cfg.get("global_options", {}) if isinstance(cfg, dict) else {}
    opts = _default_global_options()
    if isinstance(raw, dict):
        opts.update(raw)
    return opts


def save_global_table_options(options: Dict[str, Any]) -> bool:
    cfg = load_column_config()
    cfg = _normalize_config(cfg)
    opts = _default_global_options()
    if isinstance(options, dict):
        opts.update(options)
    opts["updated_at"] = _now_text()
    cfg["global_options"] = opts
    ok = save_column_config(cfg)
    st.session_state["godpick_table_filter_sort_enabled"] = bool(opts.get("table_filter_sort_enabled", True))
    st.session_state["godpick_column_manager_edit_mode"] = bool(opts.get("column_manager_edit_mode", False))
    st.session_state["godpick_table_auto_sidebar_enabled"] = bool(opts.get("auto_sidebar_enabled", True))
    return ok


def hydrate_global_table_options_once() -> Dict[str, Any]:
    opts = get_global_table_options()
    if "godpick_table_filter_sort_enabled" not in st.session_state:
        st.session_state["godpick_table_filter_sort_enabled"] = bool(opts.get("table_filter_sort_enabled", True))
    if "godpick_column_manager_edit_mode" not in st.session_state:
        st.session_state["godpick_column_manager_edit_mode"] = bool(opts.get("column_manager_edit_mode", False))
    if "godpick_table_auto_sidebar_enabled" not in st.session_state:
        st.session_state["godpick_table_auto_sidebar_enabled"] = bool(opts.get("auto_sidebar_enabled", True))
    return opts

def install_auto_column_manager(page_key: str) -> None:
    """v112：統一表格管理入口。

    修正重點：
    - 同一頁被 app_auth 與頁面本身重複呼叫時，側邊欄只顯示一次。
    - 側邊欄開關改成表單式，勾選不立即套用；按「套用並永久記錄」後才保存。
    - 全域開關永久保存到 godpick_management_ui_config.json。
    - 每張表格仍各自保存篩選 / 排序 / 欄位設定。
    """
    try:
        hydrate_global_table_options_once()
    except Exception:
        pass

    # v112：所有重型頁面預設不自動攔截所有 st.dataframe / st.data_editor，並復原上一頁殘留 patch。
    # 避免使用者只是點進頁面，尚未按「推薦 / 更新 / 套用」就因全域表格管理產生大量 widget 而卡住。
    allow_auto_patch = _render_heavy_page_guard(page_key)
    if allow_auto_patch:
        try:
            uninstall_light_checkbox_patch()
        except Exception:
            pass
        try:
            install_global_table_patch(page_key)
        except Exception:
            pass
    else:
        # v116：重型頁不啟動完整表格管理，但仍要讓所有有勾選欄位的 data_editor
        # 顯示「勾選全選 / 全部取消」。這個輕量補丁不做篩選排序、不重算資料。
        try:
            install_light_checkbox_patch(page_key)
        except Exception:
            pass

    # v106：避免同一頁面出現兩個一模一樣的「表格管理」區塊。
    # app_auth 會在每次 require_login() 時重置此旗標；同一次 rerun 內第二次呼叫會被跳過。
    # v112：重型防卡模式獨立顯示一次；不是拿掉，也不重複。
    _render_heavy_guard_sidebar_once(page_key)

    if bool(st.session_state.get("_godpick_table_sidebar_rendered_this_run_v110", False)):
        return None
    st.session_state["_godpick_table_sidebar_rendered_this_run_v110"] = True

    try:
        opts = get_global_table_options()
        with st.sidebar.expander("🧩 表格管理｜v116 篩選排序＋欄位順序＋勾選全選/取消", expanded=False):
            st.caption("每個模組 / 每張表格獨立保存；勾選、篩選、排序、欄位設定都要按套用才生效。")
            if bool(st.session_state.get("godpick_column_manager_edit_mode", False)):
                st.success("欄位順序管理：已啟用。請在表格上方的『欄位管理』區塊調整順序，並按套用保存。")
            else:
                st.info("欄位順序管理：目前關閉。勾選下方『啟用欄位順序管理模式』並套用後才會顯示。")
            guard_status = st.session_state.get("_godpick_heavy_guard_status_v110", {})
            if isinstance(guard_status, dict) and guard_status.get("heavy"):
                if guard_status.get("enabled"):
                    st.warning("本頁已手動啟用全域表格管理；若進頁變慢，可關閉後重新整理。")
                else:
                    st.info("本頁屬於重型模組，已自動停用全域表格攔截，避免進頁卡住。")
                    if guard_status.get("restored"):
                        st.success("已清除上一頁殘留的表格攔截。")
                safe_guard = _key_safe(str(guard_status.get("page_key") or page_key or "global"))
                if st.button("本次手動啟用全域表格管理", key=f"{safe_guard}_force_auto_table_patch_v110", use_container_width=True):
                    st.session_state[f"godpick_force_auto_table_patch_{safe_guard}"] = True
                    st.rerun()
            st.markdown("**欄位順序管理**")
            st.caption("功能沒有移除：先勾選『啟用欄位順序管理模式』，再按『套用並永久記錄』；套用後各表格會出現欄位順序、顯示/隱藏欄位與永久保存功能。")
            with st.form(key=f"{page_key}_global_table_options_form_v112", clear_on_submit=False):
                filter_enabled = st.checkbox(
                    "啟用表格篩選 / 排序",
                    value=bool(st.session_state.get("godpick_table_filter_sort_enabled", opts.get("table_filter_sort_enabled", True))),
                    help="只處理目前 DataFrame，不重新抓資料、不重跑推薦。",
                )
                column_enabled = st.checkbox(
                    "啟用欄位順序管理模式",
                    value=bool(st.session_state.get("godpick_column_manager_edit_mode", opts.get("column_manager_edit_mode", False))),
                    help="關閉時只快速套用已保存欄位；開啟後各表格上方會顯示欄位順序調整器。重型頁需按套用後才啟用，不會勾選就重整。",
                )
                auto_sidebar = st.checkbox(
                    "顯示本表格管理面板",
                    value=bool(st.session_state.get("godpick_table_auto_sidebar_enabled", opts.get("auto_sidebar_enabled", True))),
                    help="只控制側邊欄管理面板；不影響已保存的各表格設定。",
                )
                c1, c2 = st.columns(2)
                apply_global = c1.form_submit_button("✅ 套用並永久記錄", type="primary", use_container_width=True)
                reload_global = c2.form_submit_button("🔄 重新讀取設定", use_container_width=True)

            if apply_global:
                ok = save_global_table_options({
                    "table_filter_sort_enabled": bool(filter_enabled),
                    "column_manager_edit_mode": bool(column_enabled),
                    "auto_sidebar_enabled": bool(auto_sidebar),
                })
                # v112：若使用者明確套用「欄位順序管理模式」，重型頁本次自動啟用表格管理；
                # 這樣欄位順序調整器才會出現在各表格上方。未按套用前不啟用，避免進頁防卡失效。
                try:
                    guard_status = st.session_state.get("_godpick_heavy_guard_status_v110", {})
                    safe_guard = _key_safe(str((guard_status or {}).get("page_key") or page_key or "global"))
                    st.session_state[f"godpick_force_auto_table_patch_{safe_guard}"] = bool(column_enabled or filter_enabled)
                except Exception:
                    pass
                if ok:
                    if column_enabled:
                        st.success("已啟用欄位順序管理並永久記錄；重新整理後，各表格會顯示欄位順序調整器。")
                    else:
                        st.success("表格管理全域設定已套用並永久記錄。")
                else:
                    st.warning("已套用到本次畫面，但永久寫入可能失敗，請確認 GitHub Token 權限。")
                st.rerun()

            if reload_global:
                st.session_state["godpick_column_config_refresh_seq"] = int(st.session_state.get("godpick_column_config_refresh_seq", 0)) + 1
                try:
                    _load_config_cached.clear()
                except Exception:
                    pass
                for k in ["godpick_table_filter_sort_enabled", "godpick_column_manager_edit_mode", "godpick_table_auto_sidebar_enabled"]:
                    st.session_state.pop(k, None)
                st.rerun()

            st.caption("v116：所有 data_editor 只要有勾選欄位，都會提供『全選 / 全部取消』；重型頁使用輕量補丁，不啟動完整表格攔截。")
    except Exception:
        pass
    return None

