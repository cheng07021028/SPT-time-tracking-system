# -*- coding: utf-8 -*-
"""股神推薦績效回饋校正服務 vNext 2026-05-30.

設計原則：
- 只讀取既有 godpick_records.json，不覆蓋正式紀錄。
- 不刪除舊推薦欄位；只新增績效回饋欄位，讓 7/8/10/12 可共用。
- 讓歷史績效反饋到：選股潛力、進場買點、風控安全、績效校正、買點分級。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import math

import pandas as pd

PERFORMANCE_FEEDBACK_VERSION = "vnext_performance_feedback_20260604_phase3_breakout_false_negative"
DEFAULT_RECORD_PATH = "godpick_records.json"

FEEDBACK_COLUMNS = [
    "股神實戰總分",
    "Alpha選股潛力分",
    "Entry進場買點分",
    "Risk風控安全分",
    "Feedback績效校正分",
    "選股潛力分",
    "進場買點分",
    "風控安全分",
    "績效校正分",
    "績效校正說明",
    "新買點分級",
    "推薦角色",
    "過熱原因",
    "硬否決原因",
    "真禁買原因",
    "等待突破原因",
    "突破確認狀態",
    "突破確認條件",
    "假陰性檢討",
    "今日決策結論",
    "候選強度分",
    "實戰過濾狀態",
    "主推薦降級原因",
    "冷卻提示",
    "建議動作",
    "建議倉位",
    "建議倉位%",
    "小量試單建議",
    "加碼條件",
    "失效條件",
    "失效條件_績效回饋",
    "績效回饋建議",
    "績效樣本數",
    "績效回饋版本",
    "決策版本",
]


@dataclass(frozen=True)
class SegmentStat:
    sample: int = 0
    avg_return: float = 0.0
    median_return: float = 0.0
    win_rate: float = 0.0
    target1_rate: float = 0.0
    target2_rate: float = 0.0
    stop_rate: float = 0.0
    boost: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample": self.sample,
            "avg_return": round(self.avg_return, 4),
            "median_return": round(self.median_return, 4),
            "win_rate": round(self.win_rate, 4),
            "target1_rate": round(self.target1_rate, 4),
            "target2_rate": round(self.target2_rate, 4),
            "stop_rate": round(self.stop_rate, 4),
            "boost": round(self.boost, 4),
        }


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v).strip()


def _safe_float(v: Any, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        if pd.isna(v):
            return default
    except Exception:
        pass
    if isinstance(v, str):
        s = v.strip().replace("%", "").replace(",", "")
        if s.lower() in {"", "none", "nan", "null", "--", "-", "<na>"}:
            return default
        v = s
    try:
        x = float(v)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except Exception:
        return default


def _score_clip(v: Any, low: float = 0.0, high: float = 100.0) -> float:
    x = _safe_float(v, low)
    if x is None:
        x = low
    return round(max(low, min(high, float(x))), 2)


def _boolish(v: Any) -> bool:
    s = _safe_str(v).lower()
    return s in {"true", "1", "yes", "y", "是", "已買進", "已達", "達標"}


def _load_records_payload(path: str | Path = DEFAULT_RECORD_PATH) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ["records", "items", "data", "rows"]:
            rows = payload.get(key)
            if isinstance(rows, list):
                return [x for x in rows if isinstance(x, dict)]
    return []


def _to_numeric_series(df: pd.DataFrame, col: str, default: float | None = None) -> pd.Series:
    if col not in df.columns:
        return pd.Series([default] * len(df), index=df.index, dtype="float64")
    s = df[col].map(lambda x: _safe_float(x, default))
    return pd.to_numeric(s, errors="coerce")


def _tracking_return_series(df: pd.DataFrame) -> pd.Series:
    """建立回饋用報酬欄。

    優先用系統追蹤報酬；若該筆已有實際買進/實際報酬，則改用實際報酬，
    讓人工買進紀錄也能反饋到模型。
    """
    base = pd.Series([pd.NA] * len(df), index=df.index, dtype="object")
    for col in ["損益幅%", "損益%", "即時追蹤報酬%", "推薦後20日%", "推薦後10日%", "推薦後最大漲幅%"]:
        if col not in df.columns:
            continue
        s = _to_numeric_series(df, col)
        mask = base.isna() & s.notna()
        base.loc[mask] = s.loc[mask]
    actual = _to_numeric_series(df, "實際報酬%")
    if "是否已實際買進" in df.columns:
        actual_mask = df["是否已實際買進"].map(_boolish) & actual.notna()
    elif "是否已買進" in df.columns:
        actual_mask = df["是否已買進"].map(_boolish) & actual.notna()
    else:
        actual_mask = actual.notna() & actual.ne(0)
    base.loc[actual_mask] = actual.loc[actual_mask]
    return pd.to_numeric(base, errors="coerce")


def _score_bucket(score: Any) -> str:
    x = _safe_float(score, 0) or 0
    if x >= 95:
        return ">=95"
    if x >= 90:
        return "90-95"
    if x >= 85:
        return "85-90"
    if x >= 80:
        return "80-85"
    if x >= 75:
        return "75-80"
    return "<75"


def _truth_rate(df: pd.DataFrame, col: str) -> float:
    if col not in df.columns or df.empty:
        return 0.0
    return float(df[col].map(_boolish).mean())


def _segment_stats(df: pd.DataFrame, col: str, baseline: dict[str, float], *, min_sample: int = 3) -> dict[str, dict[str, Any]]:
    if col not in df.columns or df.empty:
        return {}
    out: dict[str, dict[str, Any]] = {}
    tmp = df.copy()
    tmp[col] = tmp[col].map(_safe_str).replace("", "未分類")
    for key, g in tmp.groupby(col, dropna=False):
        ret = pd.to_numeric(g.get("_feedback_return_pct"), errors="coerce").dropna()
        sample = int(len(ret))
        if sample <= 0:
            continue
        avg = float(ret.mean())
        med = float(ret.median())
        win = float((ret > 0).mean())
        t1 = _truth_rate(g, "是否達目標1")
        t2 = _truth_rate(g, "是否達目標2")
        stop = _truth_rate(g, "是否達停損")
        if sample < min_sample:
            boost = 0.0
        else:
            raw = ((avg - baseline.get("avg_return", 0.0)) / 3.0)
            raw += (win - baseline.get("win_rate", 0.5)) * 8.0
            raw += (t1 - baseline.get("target1_rate", 0.0)) * 4.0
            raw += (t2 - baseline.get("target2_rate", 0.0)) * 2.0
            raw -= max(0.0, stop - baseline.get("stop_rate", 0.0)) * 8.0
            shrink = min(1.0, sample / 20.0)
            boost = max(-8.0, min(8.0, raw * shrink))
        stat = SegmentStat(sample, avg, med, win, t1, t2, stop, boost)
        out[_safe_str(key)] = stat.as_dict()
    return out


def build_godpick_performance_profile(records: list[dict[str, Any]] | pd.DataFrame | None = None) -> dict[str, Any]:
    if records is None:
        records = _load_records_payload(DEFAULT_RECORD_PATH)
    df = records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame(records or [])
    if df.empty:
        return _empty_profile("沒有可用股神推薦紀錄")
    df = df.loc[:, ~df.columns.duplicated()].copy()
    df["_feedback_return_pct"] = _tracking_return_series(df)
    df["_score_bucket"] = df.get("推薦總分", pd.Series([0] * len(df), index=df.index)).map(_score_bucket)
    valid = df[df["_feedback_return_pct"].notna()].copy()
    if valid.empty:
        return _empty_profile("股神推薦紀錄缺少可計算報酬欄位")

    ret = pd.to_numeric(valid["_feedback_return_pct"], errors="coerce").dropna()
    baseline = {
        "sample": int(len(ret)),
        "avg_return": float(ret.mean()),
        "median_return": float(ret.median()),
        "win_rate": float((ret > 0).mean()),
        "target1_rate": _truth_rate(valid, "是否達目標1"),
        "target2_rate": _truth_rate(valid, "是否達目標2"),
        "stop_rate": _truth_rate(valid, "是否達停損"),
    }
    profile = {
        "version": PERFORMANCE_FEEDBACK_VERSION,
        "available": True,
        "message": "ok",
        "baseline": {k: round(v, 4) if isinstance(v, float) else v for k, v in baseline.items()},
        "by_recommend_type": _segment_stats(valid, "推薦型態", baseline, min_sample=3),
        "by_category": _segment_stats(valid, "類別", baseline, min_sample=4),
        "by_score_bucket": _segment_stats(valid, "_score_bucket", baseline, min_sample=5),
        "by_buy_grade": _segment_stats(valid, "買點分級", baseline, min_sample=3),
    }
    profile["top_categories"] = _top_keys(profile["by_category"], positive=True)
    profile["weak_categories"] = _top_keys(profile["by_category"], positive=False)
    profile["top_recommend_types"] = _top_keys(profile["by_recommend_type"], positive=True)
    profile["weak_recommend_types"] = _top_keys(profile["by_recommend_type"], positive=False)
    return profile


def _empty_profile(message: str) -> dict[str, Any]:
    return {
        "version": PERFORMANCE_FEEDBACK_VERSION,
        "available": False,
        "message": message,
        "baseline": {"sample": 0, "avg_return": 0.0, "median_return": 0.0, "win_rate": 0.0, "target1_rate": 0.0, "target2_rate": 0.0, "stop_rate": 0.0},
        "by_recommend_type": {},
        "by_category": {},
        "by_score_bucket": {},
        "by_buy_grade": {},
        "top_categories": [],
        "weak_categories": [],
        "top_recommend_types": [],
        "weak_recommend_types": [],
    }


def _top_keys(stats: dict[str, dict[str, Any]], *, positive: bool) -> list[str]:
    items = []
    for k, v in stats.items():
        boost = _safe_float(v.get("boost"), 0) or 0
        sample = int(_safe_float(v.get("sample"), 0) or 0)
        if sample <= 0:
            continue
        if positive and boost > 0:
            items.append((boost, sample, k))
        elif not positive and boost < 0:
            items.append((boost, sample, k))
    items.sort(key=lambda x: (x[0], x[1]), reverse=positive)
    if not positive:
        items.sort(key=lambda x: (x[0], -x[1]))
    return [k for _, _, k in items[:8]]


def load_godpick_performance_profile(path: str | Path = DEFAULT_RECORD_PATH) -> dict[str, Any]:
    return build_godpick_performance_profile(_load_records_payload(path))


def _lookup_boost(profile: dict[str, Any], section: str, key: Any) -> tuple[float, int]:
    stats = profile.get(section) or {}
    row = stats.get(_safe_str(key)) or {}
    return float(_safe_float(row.get("boost"), 0) or 0), int(_safe_float(row.get("sample"), 0) or 0)


def _num(out: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    return _to_numeric_series(out, col, default).fillna(default)


def _text(out: pd.DataFrame, col: str) -> pd.Series:
    if col not in out.columns:
        return pd.Series([""] * len(out), index=out.index, dtype="object")
    return out[col].map(_safe_str)


def _sync_phase1_feedback_columns(out: pd.DataFrame) -> pd.DataFrame:
    """補齊 Phase 1 決策欄位別名；不刪欄、不寫檔。"""
    if out is None:
        return pd.DataFrame()
    if out.empty:
        for c in FEEDBACK_COLUMNS:
            if c not in out.columns:
                out[c] = ""
        return out

    def _ensure_numeric_alias(target: str, source: str, default: float = 0.0) -> None:
        if target not in out.columns:
            out[target] = pd.to_numeric(out[source], errors="coerce").fillna(default) if source in out.columns else default
        elif source in out.columns:
            blank = out[target].map(lambda v: _safe_str(v) == "")
            if blank.any():
                out.loc[blank, target] = pd.to_numeric(out.loc[blank, source], errors="coerce").fillna(default)

    _ensure_numeric_alias("Alpha選股潛力分", "選股潛力分", 0.0)
    _ensure_numeric_alias("Entry進場買點分", "進場買點分", 0.0)
    _ensure_numeric_alias("Risk風控安全分", "風控安全分", 0.0)

    corr_src = out["績效校正分"] if "績效校正分" in out.columns else pd.Series([0] * len(out), index=out.index)
    corr = pd.to_numeric(corr_src, errors="coerce").fillna(0).clip(-15, 15)
    feedback_score = (50 + corr * 3).clip(0, 100).round(1)
    if "Feedback績效校正分" not in out.columns:
        out["Feedback績效校正分"] = feedback_score
    else:
        feedback_now = pd.to_numeric(out["Feedback績效校正分"], errors="coerce")
        blank = out["Feedback績效校正分"].map(lambda v: _safe_str(v) == "") | feedback_now.fillna(0).eq(0)
        if blank.any():
            out.loc[blank, "Feedback績效校正分"] = feedback_score.loc[blank]

    if "建議動作" not in out.columns:
        out["建議動作"] = out.get("績效回饋建議", "")
    else:
        src = out.get("績效回饋建議", "")
        if isinstance(src, pd.Series):
            blank = out["建議動作"].map(lambda v: _safe_str(v) == "")
            out.loc[blank, "建議動作"] = src.loc[blank]

    if "建議倉位" not in out.columns:
        if "建議倉位%" in out.columns:
            out["建議倉位"] = out["建議倉位%"].map(lambda v: f"{_safe_float(v, 0) or 0:.0f}%")
        elif "建議部位%" in out.columns:
            out["建議倉位"] = out["建議部位%"].map(lambda v: f"{_safe_float(v, 0) or 0:.0f}%")
        else:
            out["建議倉位"] = ""

    if "失效條件" not in out.columns:
        out["失效條件"] = out.get("失效條件_績效回饋", "")
    else:
        src = out.get("失效條件_績效回饋", "")
        if isinstance(src, pd.Series):
            blank = out["失效條件"].map(lambda v: _safe_str(v) == "")
            out.loc[blank, "失效條件"] = src.loc[blank]

    if "失效條件_績效回饋" not in out.columns:
        out["失效條件_績效回饋"] = out.get("失效條件", "")
    if "決策版本" not in out.columns:
        out["決策版本"] = PERFORMANCE_FEEDBACK_VERSION
    else:
        blank = out["決策版本"].map(lambda v: _safe_str(v) == "")
        out.loc[blank, "決策版本"] = PERFORMANCE_FEEDBACK_VERSION
    return out


def _ret5_score(ret5: pd.Series) -> pd.Series:
    # 0~8% 視為健康起漲；過高視為追高風險，負值則降低買點。
    s = pd.Series([55.0] * len(ret5), index=ret5.index)
    s = s.mask((ret5 >= 0) & (ret5 <= 8), 78)
    s = s.mask((ret5 > 8) & (ret5 <= 14), 62)
    s = s.mask(ret5 > 14, 38)
    s = s.mask(ret5 < 0, 48)
    return s.astype(float)


def _support_space_score(support_dist: pd.Series, resistance_space: pd.Series) -> pd.Series:
    support = pd.Series([55.0] * len(support_dist), index=support_dist.index)
    support = support.mask((support_dist >= 0) & (support_dist <= 5.5), 78)
    support = support.mask((support_dist > 5.5) & (support_dist <= 9), 64)
    support = support.mask(support_dist > 12, 40)
    space = pd.Series([55.0] * len(resistance_space), index=resistance_space.index)
    space = space.mask(resistance_space >= 8, 78)
    space = space.mask((resistance_space >= 4) & (resistance_space < 8), 65)
    space = space.mask((resistance_space > 0) & (resistance_space < 3), 38)
    return ((support * 0.55) + (space * 0.45)).clip(0, 100)


def _risk_reward_score(rr: pd.Series) -> pd.Series:
    s = pd.Series([50.0] * len(rr), index=rr.index)
    s = s.mask(rr >= 2.0, 82)
    s = s.mask((rr >= 1.5) & (rr < 2.0), 72)
    s = s.mask((rr >= 1.2) & (rr < 1.5), 58)
    s = s.mask((rr > 0) & (rr < 1.2), 40)
    return s.astype(float)


def _stop_distance_score(stop_dist: pd.Series) -> pd.Series:
    s = pd.Series([60.0] * len(stop_dist), index=stop_dist.index)
    s = s.mask((stop_dist > 0) & (stop_dist <= 5), 80)
    s = s.mask((stop_dist > 5) & (stop_dist <= 8), 66)
    s = s.mask(stop_dist > 8, 42)
    return s.astype(float)


def _build_correction_for_row(row: pd.Series, profile: dict[str, Any]) -> tuple[float, str, int]:
    rec_type = _safe_str(row.get("推薦型態")) or _safe_str(row.get("機會型態"))
    category = _safe_str(row.get("類別")) or _safe_str(row.get("產業"))
    score = _safe_float(row.get("推薦總分"), 0) or 0
    buy_grade = _safe_str(row.get("買點分級"))
    layer = _safe_str(row.get("推薦分層")) + _safe_str(row.get("股神推薦層級"))
    chase = _safe_float(row.get("追價風險分"), _safe_float(row.get("追高風險分數_決策"), 50)) or 50
    ret5 = _safe_float(row.get("近5日漲幅%"), 0) or 0
    no_buy = _safe_str(row.get("高分禁買原因"))

    score_bucket = _score_bucket(score)
    type_boost, type_n = _lookup_boost(profile, "by_recommend_type", rec_type)
    cat_boost, cat_n = _lookup_boost(profile, "by_category", category)
    bucket_boost, bucket_n = _lookup_boost(profile, "by_score_bucket", score_bucket)
    buy_boost, buy_n = _lookup_boost(profile, "by_buy_grade", buy_grade)

    corr = type_boost * 0.35 + cat_boost * 0.25 + bucket_boost * 0.25 + buy_boost * 0.15
    reasons: list[str] = []
    if type_n:
        reasons.append(f"型態{rec_type}校正{type_boost:+.1f}/樣本{type_n}")
    if cat_n:
        reasons.append(f"類別{category}校正{cat_boost:+.1f}/樣本{cat_n}")
    if bucket_n:
        reasons.append(f"分數區間{score_bucket}校正{bucket_boost:+.1f}/樣本{bucket_n}")
    if buy_n:
        reasons.append(f"原買點{buy_grade}校正{buy_boost:+.1f}/樣本{buy_n}")

    # 固定專業規則：從本次績效檢討得到的硬邏輯。
    if "C" in rec_type and "初步轉強" in rec_type:
        corr += 4.0
        reasons.append("C初步轉強歷史勝率佳 +4")
    if "D" in rec_type and "尚未起漲" in rec_type:
        corr += 2.0
        reasons.append("D尚未起漲保留潛伏 +2")
    if "B" in rec_type and "轉強確認" in rec_type:
        corr += 1.0
        reasons.append("B轉強確認 +1")
    if any(k in rec_type + layer for k in ["止跌反彈"]):
        corr -= 5.0
        reasons.append("止跌反彈績效較弱 -5")
    if score >= 90 and score < 95:
        corr += 3.0
        reasons.append("90-95分為歷史最佳區間 +3")
    if score >= 95 and ("高分但過熱" in layer or no_buy or chase >= 75 or ret5 >= 12):
        corr -= 8.0
        reasons.append("95分以上且過熱/追高風險 -8")
    if "高分但過熱" in layer or _safe_str(row.get("高分禁買旗標")) == "是":
        corr -= 6.0
        reasons.append("高分但過熱硬降級 -6")
    if chase >= 78:
        corr -= 6.0
        reasons.append("追高風險高 -6")
    elif chase >= 70:
        corr -= 3.0
        reasons.append("追高風險中 -3")

    corr = max(-15.0, min(15.0, corr))
    total_sample = int(max(type_n, cat_n, bucket_n, buy_n))
    return round(corr, 2), "｜".join(reasons[:8]) if reasons else "無足夠歷史分群資料，採保守校正", total_sample


def _decide_grade_and_role(row: pd.Series) -> tuple[str, str, str, str, str, str]:
    final_score = _safe_float(row.get("股神實戰總分"), 0) or 0
    potential = _safe_float(row.get("選股潛力分"), 0) or 0
    entry = _safe_float(row.get("進場買點分"), 0) or 0
    safety = _safe_float(row.get("風控安全分"), 0) or 0
    tech = _safe_float(row.get("技術結構分數"), 0) or 0
    heat = _safe_float(row.get("類股熱度分數"), 0) or 0
    pre = _safe_float(row.get("起漲前兆分數"), _safe_float(row.get("飆股起漲分數"), 0)) or 0
    chase = _safe_float(row.get("追價風險分"), 50) or 50
    ret5 = _safe_float(row.get("近5日漲幅%"), 0) or 0
    rec_type = _safe_str(row.get("推薦型態")) + _safe_str(row.get("機會型態"))
    layer = _safe_str(row.get("推薦分層")) + _safe_str(row.get("股神推薦層級"))
    no_buy = _safe_str(row.get("高分禁買原因"))
    score = _safe_float(row.get("推薦總分"), 0) or 0

    overheat_reasons = []
    if "高分但過熱" in layer:
        overheat_reasons.append("推薦分層過熱")
    if chase >= 78:
        overheat_reasons.append(f"追高風險{chase:.1f}")
    if ret5 >= 14:
        overheat_reasons.append(f"近5日漲幅{ret5:.1f}%")
    if score >= 95 and entry < 60:
        overheat_reasons.append("95分以上但買點分不足")
    if no_buy:
        overheat_reasons.append(no_buy)

    is_early = (("C" in rec_type and "初步轉強" in rec_type) or ("D" in rec_type and "尚未起漲" in rec_type))

    if overheat_reasons:
        grade = "D｜過熱禁買"
        role = "高分但過熱 / 禁買"
        suggestion = "不追價，等拉回支撐或重新突破確認。"
        trial = "否"
    elif final_score >= 88 and potential >= 85 and entry >= 70 and safety >= 65:
        grade = "A｜股神主買點"
        role = "股神主推薦"
        suggestion = "可列優先追蹤；依突破/回測條件分批執行。"
        trial = "可小量試單"
    elif is_early and potential >= 70 and tech >= 65 and heat >= 60 and pre >= 55 and chase < 75:
        grade = "C+｜早期潛伏"
        role = "早期潛伏股"
        suggestion = "剛起漲潛伏型；可小量試單，不追高，突破加碼。"
        trial = "可小量試單"
    elif potential >= 80 and entry >= 58 and safety >= 55:
        grade = "B｜等突破確認"
        role = "等突破確認"
        suggestion = "條件不差，但需等量價突破或回測承接。"
        trial = "待確認"
    elif potential >= 65:
        grade = "C-｜弱勢觀察"
        role = "觀察不追"
        suggestion = "保留觀察，尚未達進場條件。"
        trial = "否"
    else:
        grade = "C-｜弱勢觀察"
        role = "觀察不追"
        suggestion = "條件不足，不列主推薦。"
        trial = "否"

    add_condition = "放量突破確認價且不爆量開高走低；或回測支撐守穩後轉強。"
    invalid_condition = "跌破停損價/近端支撐，或量縮跌破MA20，取消推薦。"
    return grade, role, "、".join(overheat_reasons), trial, add_condition, suggestion + "｜" + invalid_condition


def apply_performance_feedback(df: pd.DataFrame | None, profile: dict[str, Any] | None = None) -> pd.DataFrame:
    """將歷史績效回饋欄位補到推薦結果。

    不會刪除原欄位；舊的推薦總分保留，新版排序可使用「股神實戰總分」。
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    out = out.loc[:, ~out.columns.duplicated()].copy()
    if profile is None:
        profile = load_godpick_performance_profile(DEFAULT_RECORD_PATH)
    if not profile or not profile.get("available"):
        for c in FEEDBACK_COLUMNS:
            if c not in out.columns:
                out[c] = "" if c not in {"股神實戰總分", "Alpha選股潛力分", "Entry進場買點分", "Risk風控安全分", "Feedback績效校正分", "選股潛力分", "進場買點分", "風控安全分", "績效校正分", "候選強度分", "績效樣本數", "建議倉位%"} else 0
        out["績效回饋版本"] = PERFORMANCE_FEEDBACK_VERSION
        out["績效校正說明"] = (profile or {}).get("message", "未載入績效回饋")
        return _sync_phase1_feedback_columns(out)

    tech = _num(out, "技術結構分數", 50)
    pre = _num(out, "起漲前兆分數", 0)
    pre = pre.where(pre > 0, _num(out, "飆股起漲分數", 50))
    heat = _num(out, "類股熱度分數", 50)
    pattern = _num(out, "型態突破分數", 50)
    burst = _num(out, "爆發力分數", 50)
    factor = _num(out, "自動因子總分", 50)
    leader = _num(out, "同類股領先幅度", 50)
    buy_score = _num(out, "買進分數", 0)
    buy_score = buy_score.where(buy_score > 0, _num(out, "實戰買點分數", 0))
    buy_score = buy_score.where(buy_score > 0, _num(out, "交易可行分數", 50))
    entry_score = _num(out, "隔日進場分數", 50)
    chase = _num(out, "追價風險分", 50)
    chase = chase.where(chase > 0, _num(out, "追高風險分數_決策", 50))
    rr = _num(out, "風險報酬比", 0)
    rr = rr.where(rr > 0, _num(out, "風險報酬比_決策", 0))
    stop_dist = _num(out, "停損距離%", 0)
    support_dist = _num(out, "支撐距離%", 0)
    resistance_space = _num(out, "壓力空間%", 0)
    ret5 = _num(out, "近5日漲幅%", 0)
    no_buy = _text(out, "高分禁買原因")

    out["選股潛力分"] = (tech * 0.30 + pre * 0.25 + heat * 0.15 + pattern * 0.10 + burst * 0.08 + factor * 0.05 + leader * 0.07).clip(0, 100).round(1)
    out["進場買點分"] = (buy_score * 0.40 + (100 - chase).clip(0, 100) * 0.20 + _ret5_score(ret5) * 0.15 + _support_space_score(support_dist, resistance_space) * 0.15 + entry_score * 0.10).clip(0, 100).round(1)
    no_buy_penalty = no_buy.str.strip().ne("").map({True: 38.0, False: 76.0}).astype(float)
    out["風控安全分"] = ((100 - chase).clip(0, 100) * 0.35 + _stop_distance_score(stop_dist) * 0.25 + _risk_reward_score(rr) * 0.25 + no_buy_penalty * 0.15).clip(0, 100).round(1)

    correction_rows = out.apply(lambda r: _build_correction_for_row(r, profile), axis=1)
    out["績效校正分"] = [x[0] for x in correction_rows]
    out["績效校正說明"] = [x[1] for x in correction_rows]
    out["績效樣本數"] = [x[2] for x in correction_rows]
    out["股神實戰總分"] = (
        out["選股潛力分"] * 0.50
        + out["進場買點分"] * 0.25
        + out["風控安全分"] * 0.15
        + out["績效校正分"]
    ).clip(0, 100).round(1)

    decisions = out.apply(_decide_grade_and_role, axis=1)
    out["新買點分級"] = [x[0] for x in decisions]
    out["推薦角色"] = [x[1] for x in decisions]
    out["過熱原因"] = [x[2] for x in decisions]
    out["小量試單建議"] = [x[3] for x in decisions]
    out["加碼條件"] = [x[4] for x in decisions]
    out["績效回饋建議"] = [x[5] for x in decisions]
    out["失效條件_績效回饋"] = "跌破停損價/近端支撐或量縮跌破MA20，取消推薦。"
    out["績效回饋版本"] = PERFORMANCE_FEEDBACK_VERSION

    # 不覆蓋原始推論，僅補充績效回饋摘要。
    if "股神推論邏輯" in out.columns:
        base = out["股神推論邏輯"].map(_safe_str)
        add = out["績效回饋建議"].map(_safe_str)
        out["股神推論邏輯"] = [b + ("｜績效回饋：" + a if a and a not in b else "") for b, a in zip(base, add)]
    return _sync_phase1_feedback_columns(out)


def performance_feedback_summary(profile: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    if not profile or not profile.get("available"):
        return [("績效回饋", (profile or {}).get("message", "未載入"), "")]
    b = profile.get("baseline", {})
    top_types = "、".join(profile.get("top_recommend_types", [])[:3]) or "無"
    weak_types = "、".join(profile.get("weak_recommend_types", [])[:3]) or "無"
    top_cats = "、".join(profile.get("top_categories", [])[:3]) or "無"
    return [
        ("歷史樣本", f"{int(_safe_float(b.get('sample'), 0) or 0)} 筆", ""),
        ("平均報酬 / 勝率", f"{_safe_float(b.get('avg_return'), 0):.2f}% / {_safe_float(b.get('win_rate'), 0) * 100:.1f}%", ""),
        ("加權型態", top_types, ""),
        ("降權型態", weak_types, ""),
        ("強勢類別", top_cats, ""),
    ]
