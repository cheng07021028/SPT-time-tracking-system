# -*- coding: utf-8 -*-
"""VNext Phase 1 股神推薦決策引擎。

此模組只負責把既有推薦結果轉成可執行決策欄位：
- 不讀寫 JSON，不覆蓋正式推薦紀錄。
- 不刪除既有欄位，只補齊/同步決策欄位。
- 可接在 godpick_performance_feedback.apply_performance_feedback 之後使用。
"""
from __future__ import annotations

from typing import Any, Iterable
import math

import pandas as pd

DECISION_ENGINE_VERSION = "vnext_phase3_breakout_false_negative_20260604"

ROLE_MAIN = "A｜股神主推薦"
ROLE_CONFIRM = "B｜等突破確認"
ROLE_EARLY = "C+｜早期潛伏"
ROLE_WEAK = "C-｜弱勢觀察"
ROLE_OVERHEAT = "D｜過熱禁買"

DECISION_ROLE_VALUES = [
    ROLE_MAIN,
    ROLE_CONFIRM,
    ROLE_EARLY,
    ROLE_WEAK,
    ROLE_OVERHEAT,
]

DECISION_ENGINE_COLUMNS = [
    "股神實戰總分",
    "Alpha選股潛力分",
    "Entry進場買點分",
    "Risk風控安全分",
    "Feedback績效校正分",
    "選股潛力分",
    "進場買點分",
    "風控安全分",
    "績效校正分",
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
    "加碼條件",
    "失效條件",
    "決策版本",
]

NUMERIC_DECISION_COLUMNS = {
    "股神實戰總分",
    "Alpha選股潛力分",
    "Entry進場買點分",
    "Risk風控安全分",
    "Feedback績效校正分",
    "選股潛力分",
    "進場買點分",
    "風控安全分",
    "績效校正分",
    "候選強度分",
    "建議倉位%",
}

_BLANK_TEXTS = {"", "none", "nan", "nat", "null", "--", "-", "<na>"}


def _is_blank(v: Any) -> bool:
    try:
        if v is None:
            return True
        if isinstance(v, float) and math.isnan(v):
            return True
        if pd.isna(v):
            return True
    except Exception:
        pass
    return str(v).strip().lower() in _BLANK_TEXTS


def _safe_str(v: Any) -> str:
    if _is_blank(v):
        return ""
    return str(v).strip()


def _safe_float(v: Any, default: float | None = 0.0) -> float | None:
    if _is_blank(v):
        return default
    try:
        if isinstance(v, str):
            v = v.replace(",", "").replace("%", "").strip()
        f = float(v)
        if math.isnan(f):
            return default
        return f
    except Exception:
        return default


def _clip_series(s: pd.Series, low: float = 0.0, high: float = 100.0) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0.0).clip(low, high).astype(float)


def _first_numeric(out: pd.DataFrame, names: Iterable[str], default: float = 0.0, *, prefer_positive: bool = False) -> pd.Series:
    result = pd.Series([float("nan")] * len(out), index=out.index, dtype="float64")
    for name in names:
        if name not in out.columns:
            continue
        s = pd.to_numeric(out[name], errors="coerce")
        valid = s.notna()
        if prefer_positive:
            valid &= s.ne(0)
        mask = result.isna() & valid
        if mask.any():
            result.loc[mask] = s.loc[mask]
    return result.fillna(default).astype(float)


def _first_text(row: pd.Series, names: Iterable[str]) -> str:
    for name in names:
        v = row.get(name, "")
        if not _is_blank(v):
            return str(v).strip()
    return ""


def _blend_existing(out: pd.DataFrame, existing_col: str, computed: pd.Series, *, weight: float = 0.55) -> pd.Series:
    if existing_col not in out.columns:
        return computed.clip(0, 100).round(1)
    existing = pd.to_numeric(out[existing_col], errors="coerce")
    valid = existing.notna() & existing.gt(0)
    result = computed.copy().astype(float)
    if valid.any():
        result.loc[valid] = existing.loc[valid] * weight + computed.loc[valid] * (1.0 - weight)
    return result.clip(0, 100).round(1)


def _ret5_score(ret5: pd.Series) -> pd.Series:
    ret5 = pd.to_numeric(ret5, errors="coerce").fillna(0.0)
    s = pd.Series([62.0] * len(ret5), index=ret5.index)
    s = s.mask(ret5 < -8, 46)
    s = s.mask((ret5 >= -8) & (ret5 < -3), 58)
    s = s.mask((ret5 >= -3) & (ret5 <= 5), 82)
    s = s.mask((ret5 > 5) & (ret5 <= 10), 70)
    s = s.mask((ret5 > 10) & (ret5 <= 14), 52)
    s = s.mask(ret5 > 14, 32)
    return s.astype(float)


def _risk_reward_score(rr: pd.Series) -> pd.Series:
    rr = pd.to_numeric(rr, errors="coerce").fillna(0.0)
    s = pd.Series([55.0] * len(rr), index=rr.index)
    s = s.mask(rr >= 2.2, 86)
    s = s.mask((rr >= 1.8) & (rr < 2.2), 78)
    s = s.mask((rr >= 1.35) & (rr < 1.8), 65)
    s = s.mask((rr > 0) & (rr < 1.35), 44)
    return s.astype(float)


def _stop_distance_score(stop_dist: pd.Series) -> pd.Series:
    stop_dist = pd.to_numeric(stop_dist, errors="coerce").fillna(0.0)
    s = pd.Series([62.0] * len(stop_dist), index=stop_dist.index)
    s = s.mask((stop_dist > 0) & (stop_dist <= 4.5), 84)
    s = s.mask((stop_dist > 4.5) & (stop_dist <= 7.5), 70)
    s = s.mask((stop_dist > 7.5) & (stop_dist <= 10.0), 54)
    s = s.mask(stop_dist > 10.0, 38)
    return s.astype(float)


def _support_entry_score(support_dist: pd.Series, resistance_space: pd.Series) -> pd.Series:
    support_dist = pd.to_numeric(support_dist, errors="coerce").fillna(6.0)
    resistance_space = pd.to_numeric(resistance_space, errors="coerce").fillna(5.0)
    support_score = pd.Series([60.0] * len(support_dist), index=support_dist.index)
    support_score = support_score.mask((support_dist >= 0) & (support_dist <= 3.0), 86)
    support_score = support_score.mask((support_dist > 3.0) & (support_dist <= 6.0), 74)
    support_score = support_score.mask((support_dist > 6.0) & (support_dist <= 9.0), 58)
    support_score = support_score.mask(support_dist > 9.0, 40)

    resistance_score = pd.Series([58.0] * len(resistance_space), index=resistance_space.index)
    resistance_score = resistance_score.mask(resistance_space >= 10.0, 84)
    resistance_score = resistance_score.mask((resistance_space >= 6.0) & (resistance_space < 10.0), 74)
    resistance_score = resistance_score.mask((resistance_space >= 3.0) & (resistance_space < 6.0), 60)
    resistance_score = resistance_score.mask((resistance_space > 0) & (resistance_space < 3.0), 42)
    return (support_score * 0.55 + resistance_score * 0.45).clip(0, 100).astype(float)


def _distance_pct(price: pd.Series, ref: pd.Series, *, kind: str, default: float) -> pd.Series:
    price = pd.to_numeric(price, errors="coerce")
    ref = pd.to_numeric(ref, errors="coerce")
    valid = price.notna() & ref.notna() & price.gt(0) & ref.gt(0)
    out = pd.Series([default] * len(price), index=price.index, dtype="float64")
    if valid.any():
        if kind == "support":
            out.loc[valid] = ((price.loc[valid] - ref.loc[valid]) / price.loc[valid] * 100.0).clip(-10, 50)
        else:
            out.loc[valid] = ((ref.loc[valid] - price.loc[valid]) / price.loc[valid] * 100.0).clip(-10, 80)
    return out.astype(float)


def _profile_feedback_bias(feedback_profile: dict[str, Any] | None) -> float:
    if not feedback_profile or not feedback_profile.get("available"):
        return 0.0
    baseline = feedback_profile.get("baseline", {}) if isinstance(feedback_profile, dict) else {}
    sample = _safe_float(baseline.get("sample"), 0) or 0
    avg_return = _safe_float(baseline.get("avg_return"), 0) or 0
    win_rate = _safe_float(baseline.get("win_rate"), 0.5) or 0.5
    sample_weight = min(1.0, sample / 80.0)
    raw = avg_return * 0.25 + (win_rate - 0.5) * 10.0
    return max(-3.0, min(3.0, raw * sample_weight))


def _fmt_num(v: Any) -> str:
    f = _safe_float(v, None)
    if f is None:
        return ""
    if abs(f - round(f)) < 0.005:
        return str(int(round(f)))
    return f"{f:.2f}".rstrip("0").rstrip(".")


def _price_text(label: str, value: Any) -> str:
    n = _fmt_num(value)
    return f"{label}{n}" if n else ""


def _collect_overheat_reasons(row: pd.Series) -> list[str]:
    text_blob = "｜".join(
        _safe_str(row.get(c, ""))
        for c in [
            "推薦分層",
            "股神推薦層級",
            "高分禁買原因",
            "不建議買進原因",
            "風險扣分原因",
            "過熱原因",
        ]
    )
    reasons: list[str] = []
    chase = _safe_float(row.get("追價風險分", row.get("追高風險分數_決策", 50)), 50) or 50
    ret5 = _safe_float(row.get("近5日漲幅%"), 0) or 0
    ret20 = _safe_float(row.get("近20日漲幅%"), 0) or 0
    base_score = _safe_float(row.get("推薦總分"), 0) or 0
    total = _safe_float(row.get("股神實戰總分"), base_score) or 0
    entry = _safe_float(row.get("Entry進場買點分", row.get("進場買點分")), 0) or 0
    risk = _safe_float(row.get("Risk風控安全分", row.get("風控安全分")), 0) or 0

    if any(k in text_blob for k in ["高分但過熱", "過熱禁買", "禁買"]):
        reasons.append("原規則標記過熱/禁買")
    if chase >= 82:
        reasons.append(f"追高風險{chase:.1f}")
    elif chase >= 76 and ret5 >= 8:
        reasons.append(f"追高風險{chase:.1f}且短線漲幅偏大")
    if ret5 >= 14:
        reasons.append(f"近5日漲幅{ret5:.1f}%")
    if ret20 >= 32:
        reasons.append(f"近20日漲幅{ret20:.1f}%")
    if max(base_score, total) >= 92 and entry < 55:
        reasons.append("高分但進場買點不足")
    if max(base_score, total) >= 90 and risk < 50:
        reasons.append("高分但風控安全分不足")
    if _safe_str(row.get("是否建議追價")) in {"否", "不建議", "不追價"} and chase >= 72:
        reasons.append("系統不建議追價")

    # 保序去重。
    out: list[str] = []
    seen: set[str] = set()
    for r in reasons:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out[:5]


def _text_blob(row: pd.Series, names: Iterable[str]) -> str:
    return "｜".join(_safe_str(row.get(c, "")) for c in names)


def _row_chase(row: pd.Series) -> float:
    return _safe_float(row.get("_phase2_追價風險分", row.get("追價風險分", row.get("追高風險分數_決策", 50))), 50) or 50


def _row_ret5(row: pd.Series) -> float:
    return _safe_float(row.get("_phase2_近5日漲幅%", row.get("近5日漲幅%", row.get("5日漲幅%", 0))), 0) or 0


def _row_ret20(row: pd.Series) -> float:
    return _safe_float(row.get("近20日漲幅%", row.get("20日漲幅%", 0)), 0) or 0


def _row_stop_distance(row: pd.Series) -> float:
    return _safe_float(row.get("_phase2_停損距離%", row.get("停損距離%", row.get("最大風險%", 0))), 0) or 0


def _row_rr(row: pd.Series) -> float:
    return _safe_float(row.get("_phase2_風險報酬比", row.get("風險報酬比", row.get("風險報酬比_決策", 0))), 0) or 0


def _row_pressure_space(row: pd.Series) -> float:
    return _safe_float(row.get("_phase2_壓力空間%", row.get("壓力空間%", row.get("目標報酬%", 0))), 0) or 0


def _row_price(row: pd.Series) -> float:
    return _safe_float(row.get("最新價", row.get("推薦價格", row.get("推薦日價格", row.get("建議價位", 0)))), 0) or 0


def _row_breakout_price(row: pd.Series) -> float:
    return _safe_float(row.get("突破確認價", row.get("突破確認價_隔日", row.get("近端壓力", row.get("第一壓力價", 0)))), 0) or 0


def _row_breakout_distance(row: pd.Series) -> float:
    price = _row_price(row)
    breakout = _row_breakout_price(row)
    if price <= 0 or breakout <= 0:
        return 999.0
    return ((breakout - price) / price) * 100.0


def _has_breakout_reference(row: pd.Series) -> bool:
    return _row_breakout_price(row) > 0 or bool(_first_text(row, ["突破確認價", "突破確認價_隔日", "近端壓力", "第一壓力價"]))


def _has_pullback_only_signal(row: pd.Series) -> bool:
    blob = _text_blob(row, ["推薦型態", "機會型態", "推薦分層", "買點分級", "進場型態", "股神進場建議"])
    return any(k in blob for k in ["止跌反彈", "跌深反彈", "弱勢反彈", "反彈觀察"])


def _collect_hard_veto_reasons(row: pd.Series) -> list[str]:
    """Phase 3：收集會阻擋 A 主推薦的硬風控原因。

    注意：這裡仍保留「阻擋 A」的原因，但後續會再區分：
    - 真 D：確定過熱禁買。
    - 假 D：高 Alpha 但買點/風控暫不合格，改列 B 等突破確認。
    """
    text_blob = _text_blob(row, [
        "推薦分層", "股神推薦層級", "高分禁買原因", "不建議買進原因", "風險扣分原因",
        "過熱原因", "過熱風險", "風險說明", "股神實戰建議", "專業決策摘要",
    ])
    reasons: list[str] = []
    chase = _row_chase(row)
    ret5 = _row_ret5(row)
    ret20 = _row_ret20(row)
    stop_dist = _row_stop_distance(row)
    rr = _row_rr(row)
    entry = _safe_float(row.get("Entry進場買點分", row.get("進場買點分")), 0) or 0
    risk = _safe_float(row.get("Risk風控安全分", row.get("風控安全分")), 0) or 0
    total = _safe_float(row.get("股神實戰總分", row.get("推薦總分")), 0) or 0

    if any(k in text_blob for k in ["高分但過熱", "過熱禁買", "禁買"]):
        reasons.append("原規則已標記過熱/禁買")
    if any(k in text_blob for k in ["追價風險過高", "不建議追價"]):
        reasons.append("追價風險過高")
    if chase >= 82:
        reasons.append(f"追價風險分{chase:.1f}過高")
    elif chase >= 74 and ret5 >= 8:
        reasons.append(f"追價風險{chase:.1f}且近5日已漲{ret5:.1f}%")
    if ret5 >= 14:
        reasons.append(f"近5日漲幅{ret5:.1f}%過熱")
    if ret20 >= 35:
        reasons.append(f"近20日漲幅{ret20:.1f}%過熱")
    if stop_dist >= 15:
        reasons.append(f"停損距離{stop_dist:.1f}%過大")
    if rr > 0 and rr < 0.75 and any(k in text_blob for k in ["風險報酬比不足", "RR", "風險報酬"]):
        reasons.append(f"風險報酬比{rr:.2f}明顯不足")
    if total >= 88 and entry < 48:
        reasons.append("高分但進場買點嚴重不足")
    if total >= 88 and risk < 45:
        reasons.append("高分但風控安全分嚴重不足")

    out: list[str] = []
    seen: set[str] = set()
    for r in reasons:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out[:6]


def _collect_main_block_reasons(row: pd.Series) -> list[str]:
    """不一定禁買，但不得列 A 主推薦的降級條件。"""
    text_blob = _text_blob(row, [
        "高分禁買原因", "不建議買進原因", "風險扣分原因", "風險說明", "買點分級", "推薦型態", "機會型態",
    ])
    reasons: list[str] = []
    entry = _safe_float(row.get("Entry進場買點分", row.get("進場買點分")), 0) or 0
    risk = _safe_float(row.get("Risk風控安全分", row.get("風控安全分")), 0) or 0
    stop_dist = _row_stop_distance(row)
    rr = _row_rr(row)
    pressure_space = _row_pressure_space(row)

    if entry < 70:
        reasons.append(f"Entry進場買點分{entry:.1f}未達70")
    if risk < 70:
        reasons.append(f"Risk風控安全分{risk:.1f}未達70")
    if stop_dist > 10:
        reasons.append(f"停損距離{stop_dist:.1f}%超過10%")
    if rr > 0 and rr < 1.35:
        reasons.append(f"風險報酬比{rr:.2f}未達1.35")
    if pressure_space > 0 and pressure_space < 3:
        reasons.append(f"上方空間僅{pressure_space:.1f}%")
    if any(k in text_blob for k in ["買點仍需確認", "買點條件尚未完整", "等待突破", "等突破", "待確認"]):
        reasons.append("買點尚需確認")
    if any(k in text_blob for k in ["風險報酬比不足", "停損距離偏大", "停損距離過大"]):
        reasons.append("既有風控原因未解除")
    if _has_pullback_only_signal(row):
        reasons.append("止跌/跌深反彈不得列A主推薦")

    out: list[str] = []
    seen: set[str] = set()
    for r in reasons:
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out[:6]


def _is_true_overheat_veto(row: pd.Series, reasons: list[str] | None = None) -> bool:
    reasons = reasons if reasons is not None else _collect_hard_veto_reasons(row)
    blob = _text_blob(row, [
        "推薦分層", "股神推薦層級", "高分禁買原因", "不建議買進原因", "風險扣分原因",
        "過熱原因", "風險說明", "是否建議追價",
    ])
    chase = _row_chase(row)
    ret5 = _row_ret5(row)
    ret20 = _row_ret20(row)
    stop_dist = _row_stop_distance(row)
    entry = _safe_float(row.get("Entry進場買點分", row.get("進場買點分")), 0) or 0
    risk = _safe_float(row.get("Risk風控安全分", row.get("風控安全分")), 0) or 0
    total = _safe_float(row.get("股神實戰總分", row.get("推薦總分")), 0) or 0

    if chase >= 84:
        return True
    if ret5 >= 16 or ret20 >= 38:
        return True
    if stop_dist >= 22:
        return True
    if total >= 88 and entry < 40 and risk < 40:
        return True
    if any(k in blob for k in ["過熱禁買", "高分但過熱", "禁買"]) and (chase >= 76 or ret5 >= 8 or stop_dist >= 15):
        return True
    if any("追價風險" in r for r in reasons) and (chase >= 80 or ret5 >= 10):
        return True
    return False


def _is_breakout_wait_candidate(row: pd.Series, reasons: list[str] | None = None) -> bool:
    """判斷 Phase 2 被打成 D 的標的，是否其實應該分流到 B 等突破確認。"""
    reasons = reasons if reasons is not None else _collect_hard_veto_reasons(row)
    if _is_true_overheat_veto(row, reasons):
        return False
    total = _safe_float(row.get("股神實戰總分", row.get("推薦總分")), 0) or 0
    base_total = _safe_float(row.get("推薦總分", total), 0) or 0
    alpha = _safe_float(row.get("Alpha選股潛力分", row.get("選股潛力分")), 0) or 0
    entry = _safe_float(row.get("Entry進場買點分", row.get("進場買點分")), 0) or 0
    risk = _safe_float(row.get("Risk風控安全分", row.get("風控安全分")), 0) or 0
    feedback = _safe_float(row.get("Feedback績效校正分", row.get("績效校正分")), 50) or 50
    rr = _row_rr(row)
    stop_dist = _row_stop_distance(row)
    chase = _row_chase(row)
    ret5 = _row_ret5(row)
    pressure_space = _row_pressure_space(row)
    breakout_dist = _row_breakout_distance(row)
    has_breakout = _has_breakout_reference(row)
    strong_text = _text_blob(row, ["推薦型態", "機會型態", "近期強勢狀態", "股神推薦層級", "推薦分層", "買點分級"])
    has_turning_signal = any(k in strong_text for k in ["初步轉強", "剛起漲", "主升", "突破", "轉強", "強勢", "尚未起漲"])

    alpha_ok = alpha >= 68 or base_total >= 86 or total >= 66
    entry_near = entry >= 42 or (has_breakout and -1.0 <= breakout_dist <= 5.5) or pressure_space >= 2.0 or has_turning_signal
    risk_survivable = risk >= 34 and chase < 82 and ret5 < 14 and stop_dist < 22
    rr_not_fatal = rr == 0 or rr >= 0.18 or pressure_space >= 2.0 or has_breakout
    feedback_ok = feedback >= 24
    return bool(alpha_ok and entry_near and risk_survivable and rr_not_fatal and feedback_ok)


def _true_veto_reason_text(row: pd.Series) -> str:
    reasons = _collect_hard_veto_reasons(row)
    if not reasons:
        return ""
    if _is_true_overheat_veto(row, reasons):
        return "、".join(reasons)
    return ""


def _wait_breakout_reason_text(row: pd.Series) -> str:
    reasons = _collect_hard_veto_reasons(row)
    if not reasons:
        return ""
    if _is_breakout_wait_candidate(row, reasons):
        return "高Alpha但買點/風控尚未通過A門檻；Phase3改列B等突破確認：" + "、".join(reasons[:4])
    if _safe_str(row.get("推薦角色")) == ROLE_CONFIRM:
        return "高潛力但尚未達主推薦買點，需等突破或回測支撐確認。"
    return ""


def _breakout_status_for(row: pd.Series, role: str) -> str:
    if role == ROLE_MAIN:
        return "已通過主推薦門檻"
    if role == ROLE_CONFIRM:
        dist = _row_breakout_distance(row)
        if dist == 999.0:
            return "WAIT｜等放量突破或回測支撐"
        if dist <= 0:
            return "WAIT｜已接近/碰觸突破價，需收盤站穩確認"
        if dist <= 3:
            return f"WAIT｜距突破確認約{dist:.1f}%"
        if dist <= 6:
            return f"WAIT｜距突破確認約{dist:.1f}%，需量能放大"
        return "WAIT｜距突破仍遠，先列觀察"
    if role == ROLE_EARLY:
        return "EARLY｜潛伏期，等量價轉強"
    if role == ROLE_OVERHEAT:
        return "BLOCK｜真過熱/風控失衡"
    return "WATCH｜訊號不足"


def _today_conclusion_for(row: pd.Series, role: str) -> str:
    if role == ROLE_MAIN:
        return "可進攻｜小倉分批，嚴守失效條件"
    if role == ROLE_CONFIRM:
        return "不先買｜等突破確認後再轉進攻"
    if role == ROLE_EARLY:
        return "可潛伏觀察｜最多小量試單"
    if role == ROLE_OVERHEAT:
        return "不開新倉｜過熱禁買"
    return "僅觀察｜訊號不足"


def _false_negative_review_for(row: pd.Series) -> str:
    reasons = _collect_hard_veto_reasons(row)
    if not reasons:
        return ""
    if _is_breakout_wait_candidate(row, reasons):
        return "Phase2可能假陰性：有硬風控原因但未達真過熱，改列B等突破確認。"
    if _is_true_overheat_veto(row, reasons):
        return "真D：追價/過熱/風控條件未解除前不追。"
    return "保守降級：需等買點與風控修復。"


def _cooldown_hint(row: pd.Series) -> str:
    blob = _text_blob(row, ["連續推薦", "推薦次數", "冷卻提示", "突破風險", "假突破風險", "近期強勢狀態"])
    if any(k in blob for k in ["假突破", "突破後量價無法延續", "未突破", "弱勢"]):
        return "若連續推薦但未放量突破，先冷卻觀察，不追價。"
    if _safe_float(row.get("推薦次數"), 0) and (_safe_float(row.get("推薦次數"), 0) or 0) >= 3:
        return "同檔多次出現，需確認突破或回測成功後才升級。"
    return ""


def _status_for_role(role: str) -> str:
    if role == ROLE_MAIN:
        return "PASS｜可列主推薦"
    if role == ROLE_CONFIRM:
        return "WAIT｜等突破確認"
    if role == ROLE_EARLY:
        return "EARLY｜早期潛伏小量"
    if role == ROLE_OVERHEAT:
        return "BLOCK｜硬否決/過熱禁買"
    return "WATCH｜弱勢觀察"


def _is_early_candidate(row: pd.Series) -> bool:
    blob = "｜".join(
        _safe_str(row.get(c, ""))
        for c in [
            "推薦型態",
            "機會型態",
            "推薦分層",
            "股神推薦層級",
            "買點分級",
            "進場型態",
            "近期強勢狀態",
        ]
    )
    keywords = ["初步轉強", "尚未起漲", "早期", "潛伏", "剛起漲", "低位", "轉強觀察", "低檔"]
    return any(k in blob for k in keywords)


def _decide_role(row: pd.Series) -> str:
    total = _safe_float(row.get("股神實戰總分"), 0) or 0
    alpha = _safe_float(row.get("Alpha選股潛力分"), 0) or 0
    entry = _safe_float(row.get("Entry進場買點分"), 0) or 0
    risk = _safe_float(row.get("Risk風控安全分"), 0) or 0
    feedback = _safe_float(row.get("Feedback績效校正分"), 50) or 50
    hard_veto = _collect_hard_veto_reasons(row)
    main_blocks = _collect_main_block_reasons(row)
    early = _is_early_candidate(row)
    pullback_only = _has_pullback_only_signal(row)

    # Phase 3：硬否決不再一律 D。先分辨真過熱 vs 假陰性等待突破。
    if hard_veto:
        if _is_true_overheat_veto(row, hard_veto):
            return ROLE_OVERHEAT
        if _is_breakout_wait_candidate(row, hard_veto):
            return ROLE_CONFIRM
        # 有硬風控但未達突破確認，先弱勢觀察，不再直接包裝為禁買。
        return ROLE_WEAK

    # A 主推薦維持嚴格；只有買點與風控都過門檻才給倉位。
    if total >= 84 and alpha >= 76 and entry >= 70 and risk >= 70 and not main_blocks:
        return ROLE_MAIN

    # 高 Alpha 但買點或風控未完全通過時，進 B，不進 D。
    if total >= 66 and alpha >= 68 and risk >= 38 and (entry >= 42 or feedback >= 35 or _has_breakout_reference(row)):
        return ROLE_CONFIRM

    # 早期潛伏只給小量追蹤；止跌反彈只能觀察，不直接主推。
    if early and not pullback_only and total >= 60 and alpha >= 64 and risk >= 42 and entry >= 38:
        return ROLE_EARLY

    if total >= 64 and alpha >= 70 and risk >= 38 and entry < 58:
        return ROLE_CONFIRM

    return ROLE_WEAK


def _position_pct(role: str, row: pd.Series) -> int:
    total = _safe_float(row.get("股神實戰總分"), 0) or 0
    entry = _safe_float(row.get("Entry進場買點分"), 0) or 0
    risk = _safe_float(row.get("Risk風控安全分"), 0) or 0
    if role == ROLE_OVERHEAT:
        return 0
    if role == ROLE_MAIN:
        pct = 15
        if total >= 92 and entry >= 78 and risk >= 78:
            pct = 25
        elif total >= 88 and entry >= 74 and risk >= 74:
            pct = 20
    elif role == ROLE_CONFIRM:
        pct = 0
    elif role == ROLE_EARLY:
        pct = 3 if entry < 55 else 5
    else:
        pct = 0
    if risk < 60:
        pct = min(pct, 3)
    elif risk < 70:
        pct = min(pct, 5 if role == ROLE_EARLY else 0)
    return int(max(0, min(25, pct)))


def _action_for(role: str) -> str:
    return {
        ROLE_MAIN: "主推薦；只依支撐/突破條件分批進場，嚴禁開高追滿倉。",
        ROLE_CONFIRM: "等待突破確認；突破前不主動買，放量站上確認價或回測支撐守穩後再轉進攻。",
        ROLE_EARLY: "早期潛伏；只允許小量試單，未放量前不追高。",
        ROLE_WEAK: "弱勢觀察；保留追蹤，不主動買進。",
        ROLE_OVERHEAT: "真過熱禁買；不追價，等待拉回降溫或重新整理。",
    }.get(role, "觀察；等待條件確認。")


def _add_condition_for(row: pd.Series, role: str) -> str:
    if role == ROLE_OVERHEAT:
        return "無；需先解除過熱、追高風險下降後再重新評估。"
    if role == ROLE_CONFIRM:
        breakout = _first_text(row, ["突破確認價", "突破確認價_隔日", "近端壓力", "第一壓力價"])
        support = _first_text(row, ["近端支撐", "主要支撐", "回測承接價", "推薦買點_拉回"])
        pieces: list[str] = []
        btxt = _price_text("突破確認價", breakout)
        stxt = _price_text("支撐", support)
        if btxt:
            pieces.append(f"盤中放量站上{btxt}且收盤不跌破")
        if stxt:
            pieces.append(f"或回測{stxt}守穩後轉強")
        pieces.append("Entry/Risk 分數同步改善後才升級")
        return "；".join(pieces[:3]) + "。"
    breakout = _first_text(row, ["突破確認價", "突破確認價_隔日", "近端壓力", "第一壓力價"])
    support = _first_text(row, ["近端支撐", "主要支撐", "回測承接價", "推薦買點_拉回"])
    pieces: list[str] = []
    btxt = _price_text("突破確認價", breakout)
    stxt = _price_text("支撐", support)
    if btxt:
        pieces.append(f"放量站上{btxt}且收盤不跌破")
    if stxt:
        pieces.append(f"回測{stxt}守穩後轉強")
    pieces.append("量能續強且大盤風控未轉弱")
    return "；".join(pieces[:3]) + "。"


def _invalid_condition_for(row: pd.Series) -> str:
    stop = _first_text(row, ["停損價", "停損參考", "停損價_隔日"])
    support = _first_text(row, ["近端支撐", "主要支撐", "回測承接價"])
    pieces: list[str] = []
    stop_txt = _price_text("停損價", stop)
    support_txt = _price_text("支撐", support)
    if stop_txt:
        pieces.append(f"跌破{stop_txt}")
    elif support_txt:
        pieces.append(f"跌破{support_txt}")
    else:
        pieces.append("跌破近端支撐")
    pieces.append("量縮跌破MA20")
    pieces.append("大盤風控轉弱")
    return "；".join(pieces) + "，取消推薦。"


def _decision_summary(row: pd.Series) -> str:
    return (
        f"{_safe_str(row.get('推薦角色'))}｜實戰{_safe_float(row.get('股神實戰總分'), 0):.1f}｜"
        f"Alpha{_safe_float(row.get('Alpha選股潛力分'), 0):.1f}/"
        f"Entry{_safe_float(row.get('Entry進場買點分'), 0):.1f}/"
        f"Risk{_safe_float(row.get('Risk風控安全分'), 0):.1f}/"
        f"Feedback{_safe_float(row.get('Feedback績效校正分'), 0):.1f}"
    )


def apply_godpick_decision_engine(df: pd.DataFrame | None, feedback_profile: dict[str, Any] | None = None) -> pd.DataFrame:
    """套用 VNext Phase 1 股神推薦決策引擎。

    Parameters
    ----------
    df:
        既有推薦結果。函式會回傳 copy，不會改動原 DataFrame。
    feedback_profile:
        godpick_performance_feedback.load_godpick_performance_profile 的結果；可省略。
    """
    if df is None:
        return pd.DataFrame(columns=DECISION_ENGINE_COLUMNS)
    if not isinstance(df, pd.DataFrame):
        out = pd.DataFrame(df)
    else:
        out = df.copy()
    out = out.loc[:, ~pd.Index(out.columns).duplicated()].copy()
    if out.empty:
        for col in DECISION_ENGINE_COLUMNS:
            if col not in out.columns:
                out[col] = pd.Series(dtype="float64" if col in NUMERIC_DECISION_COLUMNS else "object")
        return out.drop(columns=[c for c in out.columns if str(c).startswith("_phase2_")], errors="ignore")

    base_total = _first_numeric(out, ["推薦總分", "推薦分數", "股神決策分數"], 50, prefer_positive=True).clip(0, 100)
    tech = _first_numeric(out, ["技術結構分數", "技術趨勢分數", "均線轉強分", "動能翻多分", "推薦總分"], 50, prefer_positive=True).clip(0, 100)
    pre = _first_numeric(out, ["起漲前兆分數", "飆股起漲分數", "突破準備分", "型態突破分數"], 50, prefer_positive=True).clip(0, 100)
    volume = _first_numeric(out, ["量價動能分數", "量能啟動分", "人氣量能分", "量能人氣分"], 50, prefer_positive=True).clip(0, 100)
    group = _first_numeric(out, ["類股熱度分數", "族群資金流分數", "族群流動性分數", "強勢族群分數"], 50, prefer_positive=True).clip(0, 100)
    factor = _first_numeric(out, ["官方因子總分", "自動因子總分", "基本面成長分數", "營收成長分數"], 50, prefer_positive=True).clip(0, 100)
    leader = _first_numeric(out, ["同類股領先幅度", "類股內排名分數"], 50, prefer_positive=True).clip(0, 100)

    lead_bonus = pd.Series([0.0] * len(out), index=out.index)
    if "是否領先同類股" in out.columns:
        lead_bonus += out["是否領先同類股"].map(lambda v: 4.0 if _safe_str(v) == "是" else 0.0)
    if "類股前3強" in out.columns:
        lead_bonus += out["類股前3強"].map(lambda v: 3.0 if _safe_str(v) == "是" else 0.0)

    computed_alpha = (tech * 0.24 + pre * 0.22 + volume * 0.17 + group * 0.18 + factor * 0.12 + leader * 0.07 + lead_bonus).clip(0, 100)
    alpha = _blend_existing(out, "選股潛力分", computed_alpha, weight=0.55)

    buy_score = _first_numeric(out, ["買進分數", "進場時機分數", "實戰買點分數", "交易可行分數", "隔日進場分數"], 50, prefer_positive=True).clip(0, 100)
    chase = _first_numeric(out, ["追價風險分", "追高風險分數_決策"], 50, prefer_positive=True).clip(0, 100)
    ret5 = _first_numeric(out, ["近5日漲幅%", "5日漲幅%", "RET5"], 0)
    price = _first_numeric(out, ["最新價", "推薦價格", "推薦日價格", "建議價位"], 0, prefer_positive=True)
    support_price = _first_numeric(out, ["近端支撐", "主要支撐", "回測承接價", "推薦買點_拉回"], 0, prefer_positive=True)
    resistance_price = _first_numeric(out, ["近端壓力", "突破確認價", "突破確認價_隔日", "第一壓力價"], 0, prefer_positive=True)
    support_dist = _first_numeric(out, ["支撐距離%"], float("nan"))
    support_dist = support_dist.where(support_dist.notna(), _distance_pct(price, support_price, kind="support", default=6.0))
    resistance_space = _first_numeric(out, ["壓力空間%", "目標報酬%"], float("nan"))
    resistance_space = resistance_space.where(resistance_space.notna(), _distance_pct(price, resistance_price, kind="resistance", default=5.0))

    computed_entry = (
        buy_score * 0.38
        + (100 - chase).clip(0, 100) * 0.20
        + _ret5_score(ret5) * 0.16
        + _support_entry_score(support_dist, resistance_space) * 0.18
        + volume * 0.08
    ).clip(0, 100)
    entry = _blend_existing(out, "進場買點分", computed_entry, weight=0.55)

    rr = _first_numeric(out, ["風險報酬比", "風險報酬比_決策"], 0)
    stop_dist = _first_numeric(out, ["停損距離%", "最大風險%"], float("nan"))
    stop_price = _first_numeric(out, ["停損價", "停損參考", "停損價_隔日"], 0, prefer_positive=True)
    derived_stop = _distance_pct(price, stop_price, kind="support", default=6.0)
    stop_dist = stop_dist.where(stop_dist.notna(), derived_stop)
    liquidity = _first_numeric(out, ["流動性分數", "族群流動性分數", "人氣量能分"], 60, prefer_positive=True).clip(0, 100)
    market = _first_numeric(out, ["大盤橋接分數", "大盤影響加減分"], 55, prefer_positive=True).clip(0, 100)
    no_buy_text = out.apply(lambda r: _first_text(r, ["高分禁買原因", "不建議買進原因", "風險扣分原因"]), axis=1)
    no_buy_score = no_buy_text.map(lambda v: 40.0 if _safe_str(v) else 78.0).astype(float)

    computed_risk = (
        (100 - chase).clip(0, 100) * 0.30
        + _stop_distance_score(stop_dist) * 0.22
        + _risk_reward_score(rr) * 0.22
        + liquidity * 0.12
        + market * 0.06
        + no_buy_score * 0.08
    ).clip(0, 100)
    risk = _blend_existing(out, "風控安全分", computed_risk, weight=0.55)

    # Phase 2 硬否決需要用到計算後的交易指標；先用暫存欄，回傳前移除。
    out["_phase2_停損距離%"] = pd.to_numeric(stop_dist, errors="coerce").fillna(0).round(2)
    out["_phase2_風險報酬比"] = pd.to_numeric(rr, errors="coerce").fillna(0).round(2)
    out["_phase2_追價風險分"] = pd.to_numeric(chase, errors="coerce").fillna(50).round(1)
    out["_phase2_近5日漲幅%"] = pd.to_numeric(ret5, errors="coerce").fillna(0).round(2)
    out["_phase2_壓力空間%"] = pd.to_numeric(resistance_space, errors="coerce").fillna(0).round(2)

    correction_delta = _first_numeric(out, ["績效校正分"], 0).clip(-15, 15)
    profile_bias = _profile_feedback_bias(feedback_profile)
    feedback_component = (50 + correction_delta * 3.0 + profile_bias).clip(0, 100).round(1)
    if "Feedback績效校正分" in out.columns:
        old_feedback = pd.to_numeric(out["Feedback績效校正分"], errors="coerce")
        valid_old = old_feedback.notna() & old_feedback.between(0, 100) & old_feedback.ne(0)
        feedback_component.loc[valid_old] = (old_feedback.loc[valid_old] * 0.45 + feedback_component.loc[valid_old] * 0.55).clip(0, 100)
    feedback_component = feedback_component.round(1)

    quality_total = (alpha * 0.46 + entry * 0.28 + risk * 0.18 + feedback_component * 0.08).clip(0, 100)
    # 原始推薦總分代表既有掃描架構的多因子共識；這裡只當加減分，避免覆蓋 Entry/Risk。
    base_boost = ((base_total - 60.0) * 0.35).clip(-8.0, 12.0)
    engine_total = (quality_total + base_boost).clip(0, 100)
    existing_practical = _first_numeric(out, ["股神實戰總分"], float("nan"), prefer_positive=True)
    practical = engine_total.copy()
    valid_existing = existing_practical.notna() & existing_practical.gt(0)
    if valid_existing.any():
        practical.loc[valid_existing] = existing_practical.loc[valid_existing] * 0.50 + engine_total.loc[valid_existing] * 0.50
    # 保留原推薦總分的訊號，但不讓單一高總分蓋掉過熱/風控。
    practical = (practical * 0.82 + base_total * 0.18).clip(0, 100).round(1)

    out["Alpha選股潛力分"] = alpha
    out["Entry進場買點分"] = entry
    out["Risk風控安全分"] = risk
    out["Feedback績效校正分"] = feedback_component
    # 同步舊欄名，讓既有頁面排序、匯出與紀錄欄位不需要改架構。
    out["選股潛力分"] = alpha
    out["進場買點分"] = entry
    out["風控安全分"] = risk
    out["績效校正分"] = correction_delta.round(1)
    out["股神實戰總分"] = practical
    out["候選強度分"] = pd.to_numeric(base_total, errors="coerce").fillna(0).round(1)

    roles = out.apply(_decide_role, axis=1)
    out["推薦角色"] = roles
    out["新買點分級"] = roles
    hard_veto_text = out.apply(lambda r: "、".join(_collect_hard_veto_reasons(r)), axis=1)
    main_block_text = out.apply(lambda r: "、".join(_collect_main_block_reasons(r)), axis=1)
    overheat_text = out.apply(lambda r: "、".join(_collect_overheat_reasons(r)), axis=1)
    out["硬否決原因"] = hard_veto_text
    out["真禁買原因"] = out.apply(_true_veto_reason_text, axis=1)
    out["等待突破原因"] = out.apply(_wait_breakout_reason_text, axis=1)
    out["主推薦降級原因"] = main_block_text
    out["過熱原因"] = out["真禁買原因"].where(out["真禁買原因"].map(lambda x: bool(_safe_str(x))), overheat_text)
    out["突破確認狀態"] = out.apply(lambda r: _breakout_status_for(r, _safe_str(r.get("推薦角色"))), axis=1)
    out["突破確認條件"] = out.apply(lambda r: _add_condition_for(r, _safe_str(r.get("推薦角色"))), axis=1)
    out["假陰性檢討"] = out.apply(_false_negative_review_for, axis=1)
    out["今日決策結論"] = out.apply(lambda r: _today_conclusion_for(r, _safe_str(r.get("推薦角色"))), axis=1)
    out["實戰過濾狀態"] = roles.map(_status_for_role)
    out["冷卻提示"] = out.apply(_cooldown_hint, axis=1)
    out["建議動作"] = roles.map(_action_for)

    position_pct = out.apply(lambda r: _position_pct(_safe_str(r.get("推薦角色")), r), axis=1).astype(int)
    out["建議倉位%"] = position_pct
    out["建議倉位"] = position_pct.map(lambda p: "0%（不進場）" if p <= 0 else f"{int(p)}%（分批）")
    out["加碼條件"] = out.apply(lambda r: _add_condition_for(r, _safe_str(r.get("推薦角色"))), axis=1)
    out["失效條件"] = out.apply(_invalid_condition_for, axis=1)
    # 舊欄位同步，不刪除、不改動其他歷史欄。
    if "失效條件_績效回饋" not in out.columns:
        out["失效條件_績效回饋"] = out["失效條件"]
    else:
        blank = out["失效條件_績效回饋"].map(_is_blank)
        out.loc[blank, "失效條件_績效回饋"] = out.loc[blank, "失效條件"]
    if "績效回饋建議" in out.columns:
        blank = out["績效回饋建議"].map(_is_blank)
        out.loc[blank, "績效回饋建議"] = out.loc[blank, "建議動作"]
    else:
        out["績效回饋建議"] = out["建議動作"]

    out["決策版本"] = DECISION_ENGINE_VERSION
    if "專業決策摘要" in out.columns:
        blank = out["專業決策摘要"].map(_is_blank)
        out.loc[blank, "專業決策摘要"] = out.loc[blank].apply(_decision_summary, axis=1)
    else:
        out["專業決策摘要"] = out.apply(_decision_summary, axis=1)

    out = out.drop(columns=[c for c in out.columns if str(c).startswith("_phase2_") or str(c).startswith("_phase3_")], errors="ignore")
    return out
