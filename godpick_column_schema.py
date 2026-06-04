# -*- coding: utf-8 -*-
"""股神推薦欄位標準化共用模組 v29

用途：
- 讓 7_股神推薦、8_股神推薦紀錄、10_推薦清單、12_股神管理中心使用同一套核心欄位與欄位順序。
- 不修改推薦分數邏輯，只處理欄位名稱、欄位順序、缺欄補值與 None/nan 顯示問題。
"""
from __future__ import annotations

from typing import Any, Iterable
import math
import json
import pandas as pd

BLANK_TEXTS = {"", "none", "nan", "nat", "null", "--", "-", "<na>"}

# 不應出現在資料表/匯出/管理中心的內部或過時欄位。
# 版本資訊只能放在程式註解或頁面說明，不可再生成資料欄位，避免欄位越來越多。
HIDDEN_INTERNAL_COLUMNS = {
    "V144專業決策版本",
    "實戰版本",
    "V139顯示分區",
    "V139主升起漲候選",
    "V139動態熱門族群版",
    "V134動態資金流版",
    "V133熱門流動性版",
    "V128實戰分流版本",
}


def drop_hidden_internal_columns(df: pd.DataFrame | None) -> pd.DataFrame:
    """移除不應顯示或保存的內部欄位，並保留其他既有資料欄位。"""
    if df is None:
        return pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)
    hidden = [c for c in df.columns if str(c) in HIDDEN_INTERNAL_COLUMNS or str(c).startswith("_internal_")]
    if hidden:
        df = df.drop(columns=hidden, errors="ignore")
    return df

# 7 完整推薦表、8 推薦紀錄、10 推薦清單、12 管理中心共用的標準顯示順序。
# 特殊操作欄位如「勾選 / 匯入自選 / 刪除」由各頁自行放最前面，不放在這裡。
UNIFIED_RECOMMEND_DISPLAY_COLUMNS = [
    "v21操作優先順序", "追蹤分級", "今日操作建議", "品質分級", "品質建議",
    "資料來源", "資料來源檔", "record_id",
    '股神推薦層級', '候補等級', '是否主要顯示', '主表篩選', '股神輸出排序', '候補排序分', '股神實戰建議', '限制原因', '主表篩選說明', '顯示分區', '主升起漲候選', '主升量價檢查', '近期強勢狀態', '族群名稱', '資金流熱門族群', '族群熱度排名', '族群流動性分數', '族群樣本數', '族群判斷依據', '大盤趨勢模式', '人氣量能分', '成交額百萬', '20日均成交額百萬', '最新成交量_張', '20日均量_張', '近5日漲幅%', '近20日漲幅%', '流動性等級',
    "推薦日期", "推薦時間", "股票代號", "股票名稱", "市場別", "類別", "產業",
    "推薦模式", "推薦型態", "機會型態", "推薦等級", "推薦總分", "候選強度分", "股神實戰總分", "Alpha選股潛力分", "Entry進場買點分", "Risk風控安全分", "Feedback績效校正分", "選股潛力分", "進場買點分", "風控安全分", "績效校正分", "新買點分級", "推薦角色", "推薦分數", "推薦用途", "買進分數", "是否可直接買進", "盤中確認條件", "專業決策摘要", "決策版本", '股神輸出排序', '候補排序分', '族群熱度排名', '族群資金流分數', '族群流動性分數', '族群樣本數', '人氣量能分', '成交額百萬', '20日均成交額百萬', '最新成交量_張', '20日均量_張', '近5日漲幅%', '近20日漲幅%', "股神決策分數",
    "夜間股神總分", "隔日實戰排序分", "隔日進場分數", "波段潛力分數",
    "技術趨勢分數", "量價動能分數", "法人籌碼分數", "大戶鎖碼分數", "基本面成長分數",
    "營收成長分數", "EPS成長分數", "估值風險分數", "PER本益比", "估算EPS",
    "外資近1日買賣超", "投信近1日買賣超", "自營商近1日買賣超", "三大法人近1日合計", "法人買超占量比%",
    "法人連買推估", "籌碼資料來源", "籌碼資料日期", "基本面資料來源", "基本面資料日期", "資料完整度",
    "起漲等級", "買點分級", "推薦分桶", "信心等級", "上漲機率估計%", "上漲機率%", "上漲機率等級", "上漲機率信心",
    "進場時機", "進場型態_隔日", "隔日建議動作", "建議動作", "股神建議動作", "股神信心", "等待條件", "股神進場區間", "建議切入區", "操作區間",
    "推薦價格", "推薦日價格", "最新價", "建議價位", "預估進場點", "回測承接價", "推薦買點_拉回", "推薦買點_突破",
    "近端支撐", "主要支撐", "近端壓力", "突破確認價", "突破確認價_隔日", "停損參考", "停損價", "停損價_隔日", "第一壓力價", "賣出目標1", "賣出目標2", "觀察週期",
    "夜間股神建議", "隔日作戰策略", "進場條件說明", "不追高條件", "夜間風險提醒",
    "建議倉位", "建議倉位%", "動態建議倉位%", "建議部位%", "建議投入等級", "第一筆進場%", "分批策略", "第二筆加碼條件",
    "停利策略", "停損策略", "最大風險%", "單檔風險等級", "風險報酬比", "追價風險分", "追高風險等級", "是否建議追價",
    "大盤策略模式", "大盤策略建議", "大盤風控建議", "大盤情境分桶", "大盤情境調權說明",
    "大盤橋接分數", "大盤橋接狀態", "大盤橋接風控", "大盤橋接策略", "大盤交易時段", "大盤資料品質", "大盤影響加減分", "大盤影響說明",
    "強勢族群等級", "族群輪動狀態", "族群資金流分數", "族群資金流說明", "族群策略建議", "族群集中警示", "組合配置建議",
    "同類股領先幅度", "是否領先同類股", "類股內排名", "類股前3強", "類股熱度分數",
    "技術結構分數", "起漲前兆分數", "飆股起漲分數", "起漲摘要", "交易可行分數", "自動因子總分", "型態名稱", "型態突破分數", "爆發等級", "爆發力分數",
    "K線驗證標記", "K線檢視提示", "推薦日支撐壓力摘要", "K線查詢參數", "雷達訊號", "籌碼訊號", "量能訊號",
    "風險說明", "績效校正說明", "績效回饋建議", "過熱原因", "硬否決原因", "真禁買原因", "等待突破原因", "突破確認狀態", "突破確認條件", "假陰性檢討", "今日決策結論", "實戰過濾狀態", "主推薦降級原因", "冷卻提示", "小量試單建議", "加碼條件", "失效條件", "失效條件_績效回饋", "績效樣本數", "績效回饋版本", "決策版本", "股神推論", "股神推論邏輯", "推薦理由", "推薦原因", "推薦理由摘要", "推薦標籤", "備註",
    "目前狀態", "狀態", "是否已實際買進", "是否已買進", "實際買進價", "實際賣出價", "實際報酬%", "損益金額", "損益幅%", "損益%", "持有天數",
    "是否達停損", "是否達目標1", "是否達目標2", "命中結果", "績效評語", "追蹤更新時間", "最新更新時間",
    "推薦後1日%", "推薦後3日%", "推薦後5日%", "推薦後10日%", "推薦後20日%", "推薦後最大漲幅%", "推薦後最大回撤%", "即時追蹤報酬%", "績效資料型態", "績效資料來源", "是否達標_回測", "是否停損_回測",
    "3日績效%", "5日績效%", "10日績效%", "20日績效%",
]

# 欄位集合可能從多版規則累積；統一去重，避免 pandas 選欄時產生重複欄。
UNIFIED_RECOMMEND_DISPLAY_COLUMNS = list(dict.fromkeys(UNIFIED_RECOMMEND_DISPLAY_COLUMNS))
UNIFIED_MANAGEMENT_COLUMNS = UNIFIED_RECOMMEND_DISPLAY_COLUMNS.copy()

# 回補規則：target 欄空白時，從 sources 依序取第一個有值欄位。
ALIASES: dict[str, list[str]] = {

    "股神推薦層級": ["V127推薦層級", "V129顯示分區", "V132顯示分區", "V133顯示分區", "V134顯示分區", "V139顯示分區", "顯示分區"],
    "候補等級": ["V127候補等級", "V129候補等級", "V139主升起漲候選", "主升起漲候選"],
    "顯示分區": ["V139顯示分區", "V134顯示分區", "V133顯示分區", "股神推薦層級"],
    "主升起漲候選": ["V139主升起漲候選"],
    "是否主要顯示": ["V129主要表顯示", "V132主要表顯示", "V133主要表顯示", "V134主要表顯示"],
    "主表篩選": ["V133主表篩選", "V134主表篩選", "是否主要顯示"],
    "股神輸出排序": ["V134輸出排序", "V133輸出排序", "V129精簡輸出排序", "主推薦排序分", "實戰主推薦分"],
    "候補排序分": ["V127候補排序分", "V129候補排序分", "主推薦排序分"],
    "股神實戰建議": ["V129股神輸出建議", "V132股神實戰建議", "V133股神實戰建議", "V134股神實戰建議", "V125股神實戰建議", "夜間股神建議"],
    "限制原因": ["V134限制原因", "V133限制原因", "V129輸出限制原因", "V127候補限制原因", "主推薦不合格原因", "實戰排除原因"],
    "族群名稱": ["V134動態族群名稱", "V132熱門族群池", "V133真正熱門族群", "類別", "產業"],
    "資金流熱門族群": ["V134資金流熱門族群", "V132主流族群資格", "V133真正熱門族群"],
    "族群熱度排名": ["V134族群熱度排名"],
    "族群流動性分數": ["V134族群流動性分數"],
    "族群樣本數": ["V134族群樣本數"],
    "族群判斷依據": ["V134族群判斷依據"],
    "大盤趨勢模式": ["V134大盤趨勢模式", "大盤橋接狀態", "大盤策略模式"],
    "成交額百萬": ["V133成交額百萬"],
    "20日均成交額百萬": ["V133二十日均成交額百萬"],
    "最新成交量_張": ["最新成交量張", "最新成交量(張)"],
    "20日均量_張": ["20日均量張", "20日均量(張)"],
    "人氣量能分": ["量能人氣分", "資金人氣分"],
    "近5日漲幅%": ["5日漲幅%", "RET5"],
    "近20日漲幅%": ["20日漲幅%", "RET20"],
    "流動性等級": ["V133流動性等級"],
    "實戰版本": ["V139動態熱門族群版", "V134動態資金流版", "V133熱門流動性版", "V128實戰分流版本"],
    "股票代號": ["code", "stock_code", "symbol", "股票"],
    "股票名稱": ["name", "stock_name"],
    "市場別": ["market"],
    "類別": ["category", "產業", "industry", "sector"],
    "產業": ["類別", "category", "industry", "sector"],
    "推薦日期": ["date", "recommend_date", "created_at", "建立時間"],
    "推薦時間": ["time", "recommend_time"],
    "股神實戰總分": ["股神決策分數", "夜間股神總分", "隔日實戰排序分", "推薦總分"],
    "Alpha選股潛力分": ["選股潛力分", "技術結構分數", "技術趨勢分數", "股神輸出排序"],
    "Entry進場買點分": ["進場買點分", "買進分數", "實戰買點分數", "隔日進場分數"],
    "Risk風控安全分": ["風控安全分", "實戰品質分", "交易可行分數"],
    "Feedback績效校正分": ["績效校正分", "績效回饋分"],
    "候選強度分": ["推薦總分", "股神決策分數", "夜間股神總分"],
    "選股潛力分": ["Alpha選股潛力分", "技術結構分數", "股神輸出排序"],
    "進場買點分": ["Entry進場買點分", "買進分數", "實戰買點分數", "隔日進場分數"],
    "風控安全分": ["Risk風控安全分", "實戰品質分", "交易可行分數"],
    "績效校正分": ["Feedback績效校正分", "績效回饋分"],
    "新買點分級": ["買點分級", "推薦角色"],
    "推薦角色": ["新買點分級", "股神推薦層級", "推薦用途"],
    "硬否決原因": ["高分禁買原因", "不建議買進原因", "風險扣分原因", "過熱原因"],
    "真禁買原因": ["過熱原因", "硬否決原因", "高分禁買原因"],
    "等待突破原因": ["限制原因", "主推薦降級原因", "硬否決原因"],
    "突破確認狀態": ["實戰過濾狀態", "股神實戰建議"],
    "突破確認條件": ["加碼條件", "等待條件", "盤中確認條件"],
    "假陰性檢討": ["冷卻提示", "績效回饋建議"],
    "今日決策結論": ["建議動作", "今日操作建議", "股神實戰建議"],
    "主推薦降級原因": ["限制原因", "主推薦不合格原因", "實戰排除原因"],
    "實戰過濾狀態": ["主表篩選", "是否主要顯示", "顯示分區"],
    "冷卻提示": ["突破風險", "假突破風險", "風險說明"],
    "績效回饋建議": ["建議動作", "股神實戰建議", "專業決策摘要"],
    "建議動作": ["績效回饋建議", "隔日建議動作", "股神建議動作", "實戰操作建議", "股神進場建議", "今日操作建議"],
    "建議倉位": ["建議倉位%", "動態建議倉位%", "建議部位%"],
    "失效條件": ["失效條件_績效回饋", "轉弱條件", "失效價位"],
    "失效條件_績效回饋": ["失效條件", "轉弱條件", "失效價位"],
    "決策版本": ["績效回饋版本"],
    "推薦分數": ["推薦總分", "total_score", "score", "final_score"],
    "推薦總分": ["推薦分數", "total_score", "score", "final_score"],
    "股神決策分數": ["夜間股神總分", "隔日實戰排序分", "推薦總分", "推薦分數", '股神輸出排序', '候補排序分', '族群熱度排名', '族群資金流分數', '族群流動性分數', '族群樣本數', '成交額百萬', '20日均成交額百萬'],
    "買進分數": ["實戰買點分數", "隔日進場分數", "交易可行分數"],
    "推薦用途": ["推薦分層", "買點狀態", "股神進場建議"],
    "是否可直接買進": ["股神進場建議", "買點狀態"],
    "盤中確認條件": ["隔日作戰策略", "最佳操作劇本", "實戰操作建議"],
    "專業決策摘要": ["股神實戰建議", "股神推論邏輯", "實戰操作建議"],
    "夜間股神總分": ["隔日實戰排序分", "推薦總分"],
    "隔日實戰排序分": ["夜間股神總分", "推薦總分"],
    "股神建議動作": ["隔日建議動作", "建議動作", "實戰操作建議", "股神進場建議", "今日操作建議"],
    "隔日建議動作": ["股神建議動作", "建議動作", "實戰操作建議", "股神進場建議", "今日操作建議"],
    "預估進場點": ["股神進場區間", "建議切入區", "操作區間"],
    "停損價_隔日": ["停損價", "停損參考"],
    "突破確認價_隔日": ["突破確認價", "推薦買點_突破"],
    "回測承接價": ["推薦買點_拉回", "近端支撐"],
    "上漲機率%": ["上漲機率估計%"],
    "上漲機率估計%": ["上漲機率%"],
    "股神建議動作": ["隔日建議動作", "建議動作", "實戰操作建議", "股神進場建議", "今日操作建議"],
    "建議動作": ["績效回饋建議", "隔日建議動作", "股神建議動作", "實戰操作建議", "股神進場建議", "今日操作建議"],
    "今日操作建議": ["隔日建議動作", "股神建議動作", "建議動作", "v21操作優先順序"],
    "股神信心": ["信心等級", "上漲機率信心"],
    "信心等級": ["股神信心", "上漲機率信心"],
    "股神進場區間": ["建議切入區", "操作區間", "股神進場建議", "股神進場區間"],
    "建議切入區": ["股神進場區間", "操作區間"],
    "推薦價格": ["推薦日價格", "最新價", "建議價位"],
    "推薦日價格": ["推薦價格", "最新價", "建議價位"],
    "建議價位": ["推薦價格", "推薦日價格", "最新價"],
    "目前狀態": ["狀態", "status"],
    "狀態": ["目前狀態", "status"],
    "是否已實際買進": ["是否已買進"],
    "是否已買進": ["是否已實際買進"],
    "損益幅%": ["損益%"],
    "損益%": ["損益幅%"],
    "股神推論": ["股神推論邏輯", "推薦理由摘要", "推薦理由", "推薦原因"],
    "股神推論邏輯": ["股神推論", "推薦理由摘要", "推薦理由", "推薦原因"],
    "推薦理由": ["推薦原因", "推薦理由摘要", "股神推論", "股神推論邏輯"],
    "推薦原因": ["推薦理由", "推薦理由摘要", "股神推論", "股神推論邏輯"],
    "族群策略建議": ["族群資金流說明"],
    "族群資金流說明": ["族群策略建議"],
    "K線驗證標記": ["K線檢視提示"],
    "K線檢視提示": ["K線驗證標記"],
    "停損價": ["停損參考"],
    "停損參考": ["停損價"],
}

NUMERIC_LIKE_COLUMNS = {
    "推薦總分", "推薦分數", "股神實戰總分", "Alpha選股潛力分", "Entry進場買點分", "Risk風控安全分", "Feedback績效校正分", "選股潛力分", "進場買點分", "風控安全分", "績效校正分", "績效樣本數", "買進分數", '股神輸出排序', '候補排序分', '族群熱度排名', '族群資金流分數', '族群流動性分數', '族群樣本數', '人氣量能分', '成交額百萬', '20日均成交額百萬', '最新成交量_張', '20日均量_張', '近5日漲幅%', '近20日漲幅%', "股神決策分數", "夜間股神總分", "隔日實戰排序分", "隔日進場分數", "波段潛力分數",
    "技術趨勢分數", "量價動能分數", "法人籌碼分數", "大戶鎖碼分數", "基本面成長分數", "營收成長分數", "EPS成長分數", "估值風險分數",
    "PER本益比", "估算EPS", "外資近1日買賣超", "投信近1日買賣超", "自營商近1日買賣超", "三大法人近1日合計", "法人買超占量比%",
    "上漲機率估計%", "上漲機率%", "推薦價格", "推薦日價格", "最新價", "建議價位", "回測承接價",
    "近端支撐", "主要支撐", "近端壓力", "突破確認價", "突破確認價_隔日", "停損參考", "停損價", "停損價_隔日", "第一壓力價", "賣出目標1", "賣出目標2",
    "建議倉位%", "動態建議倉位%", "建議部位%", "第一筆進場%", "最大風險%", "風險報酬比", "追價風險分",
    "大盤橋接分數", "大盤影響加減分", "族群資金流分數", "同類股領先幅度", "類股熱度分數", "技術結構分數", "起漲前兆分數", "飆股起漲分數", "交易可行分數", "自動因子總分", "爆發力分數",
    "實際買進價", "實際賣出價", "實際報酬%", "損益金額", "損益幅%", "損益%", "持有天數",
    "推薦後1日%", "推薦後3日%", "推薦後5日%", "推薦後10日%", "推薦後20日%", "推薦後最大漲幅%", "推薦後最大回撤%", "即時追蹤報酬%", "3日績效%", "5日績效%", "10日績效%", "20日績效%",
}


def dedupe_keep_order(seq: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for x in seq:
        k = str(x)
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def is_blank(v: Any) -> bool:
    try:
        if v is None:
            return True
        if isinstance(v, float) and math.isnan(v):
            return True
        if pd.isna(v):
            return True
    except Exception:
        pass
    s = str(v).strip()
    return s.lower() in BLANK_TEXTS


def clean_value(v: Any) -> Any:
    if is_blank(v):
        return ""
    if isinstance(v, (dict, list, tuple, set)):
        try:
            import json
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return str(v)
    return v


def _coalesce_series(target: pd.Series, source: pd.Series) -> pd.Series:
    # Pandas 3.x 不再允許把字串 / 混合型別別名直接塞進 float/int 欄位。
    # 只在 target 空白且 source 有值時回補，並在需要回補時轉成 object，避免 dtype upcast 例外。
    source = source.reindex(target.index)
    mask = target.map(is_blank) & source.map(lambda v: not is_blank(v))
    if mask.any():
        target = target.astype("object").copy()
        target.loc[mask] = source.astype("object").loc[mask]
    return target


def normalize_godpick_dataframe(df: pd.DataFrame | None, *, add_missing: bool = True, clean_none: bool = True) -> pd.DataFrame:
    """回補欄位別名、去除重複欄、清理 None/nan，並依共用欄位排序。"""
    if df is None:
        return pd.DataFrame(columns=UNIFIED_RECOMMEND_DISPLAY_COLUMNS if add_missing else [])
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)
    x = drop_hidden_internal_columns(df.copy())
    x = x.loc[:, ~pd.Index(x.columns).duplicated()].copy()

    # 先補標準欄位，確保後續 alias target 存在。
    # V144：一次性 concat 補欄，避免逐欄 insert 造成 DataFrame fragmentation 與頁面變慢。
    if add_missing:
        missing_cols = [col for col in UNIFIED_RECOMMEND_DISPLAY_COLUMNS if col not in x.columns]
        if missing_cols:
            missing_df = pd.DataFrame("", index=x.index, columns=missing_cols)
            x = pd.concat([x, missing_df], axis=1)

    for target, sources in ALIASES.items():
        if target not in x.columns:
            x[target] = ""
        for src in sources:
            if src in x.columns:
                x[target] = _coalesce_series(x[target], x[src])

    if "股票代號" in x.columns:
        x["股票代號"] = x["股票代號"].map(lambda v: str(v).strip().replace(".0", "") if not is_blank(v) else "")

    if clean_none:
        for col in x.columns:
            if col not in NUMERIC_LIKE_COLUMNS:
                x[col] = x[col].map(clean_value).astype("object")
            else:
                # 數值欄保留數字；空值顯示時再由各頁 format 函式處理。
                pass

    ordered = [c for c in UNIFIED_RECOMMEND_DISPLAY_COLUMNS if c in x.columns]
    extras = [c for c in x.columns if c not in ordered and not str(c).startswith("_")]
    return x[ordered + extras].reset_index(drop=True)


def unified_display_columns(df: pd.DataFrame | None = None, *, include_extras: bool = True, prefix: list[str] | None = None) -> list[str]:
    base = list(prefix or []) + UNIFIED_RECOMMEND_DISPLAY_COLUMNS
    base = dedupe_keep_order(base)
    if df is None or not isinstance(df, pd.DataFrame):
        return base
    cols = [c for c in base if c in df.columns]
    if include_extras:
        cols += [c for c in df.columns if c not in cols and not str(c).startswith("_") and str(c) not in HIDDEN_INTERNAL_COLUMNS]
    return dedupe_keep_order(cols)


# ------------------------------
# v29 storage / display safety helpers
# ------------------------------
def safe_for_json(v: Any) -> Any:
    """把 pandas/numpy/list/dict/NaN 轉成 JSON 可安全寫入的值。"""
    if is_blank(v):
        return ""
    try:
        import numpy as np  # type: ignore
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            f = float(v)
            return "" if math.isnan(f) else f
        if isinstance(v, (np.bool_,)):
            return bool(v)
    except Exception:
        pass
    if isinstance(v, (pd.Timestamp,)):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, (dict, list, tuple, set)):
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            return str(v)
    return v


def standardize_records_for_storage(df: pd.DataFrame | None, *, keep_extras: bool = True) -> pd.DataFrame:
    """寫入 JSON / GitHub / Firestore 前使用：統一欄位、保留資料、不讓 NaN 進 JSON。"""
    x = normalize_godpick_dataframe(df, add_missing=True, clean_none=True)
    if x is None:
        x = pd.DataFrame(columns=UNIFIED_RECOMMEND_DISPLAY_COLUMNS)
    cols = [c for c in UNIFIED_RECOMMEND_DISPLAY_COLUMNS if c in x.columns]
    if keep_extras:
        cols += [c for c in x.columns if c not in cols and not str(c).startswith("_") and str(c) not in HIDDEN_INTERNAL_COLUMNS]
    x = x.loc[:, dedupe_keep_order(cols)].copy()
    for c in x.columns:
        x[c] = x[c].map(safe_for_json)
    return x.reset_index(drop=True)


def smart_backfill_management_fields(df: pd.DataFrame | None) -> pd.DataFrame:
    """讓舊資料在 8/10/12 顯示時有一致的管理欄位。只補畫面欄位，不改推薦分數邏輯。"""
    x = normalize_godpick_dataframe(df, add_missing=True, clean_none=True)
    if x.empty:
        return x
    def score(row, *names):
        for n in names:
            v = row.get(n, "")
            try:
                if not is_blank(v):
                    return float(v)
            except Exception:
                continue
        return 0.0
    def text(row, *names):
        for n in names:
            v = row.get(n, "")
            if not is_blank(v):
                return str(v).strip()
        return ""
    for idx, row in x.iterrows():
        s = score(row, "推薦總分", "推薦分數", '股神輸出排序', '候補排序分', '族群熱度排名', '族群資金流分數', '族群流動性分數', '族群樣本數', '成交額百萬', '20日均成交額百萬', "股神決策分數")
        action = text(row, "建議動作", "股神建議動作", "今日操作建議")
        buy_grade = text(row, "買點分級", "起漲等級", "推薦等級")
        risk = text(row, "風險說明", "單檔風險等級", "追高風險等級")
        entry = text(row, "股神進場區間", "建議切入區", "操作區間")
        if is_blank(row.get("v21操作優先順序", "")):
            x.at[idx, "v21操作優先順序"] = action or ("拉回可布局" if s >= 85 else "觀察等待")
        if is_blank(row.get("追蹤分級", "")):
            x.at[idx, "追蹤分級"] = "A｜優先追蹤" if s >= 88 else ("B｜觀察確認" if s >= 80 else "C｜風險控管")
        if is_blank(row.get("今日操作建議", "")):
            x.at[idx, "今日操作建議"] = action or ("拉回可布局" if s >= 85 else "等待確認")
        if is_blank(row.get("品質分級", "")):
            x.at[idx, "品質分級"] = "A｜高分待驗證" if s >= 88 else ("B｜中高分待驗證" if s >= 80 else "C｜風險待驗證")
        if is_blank(row.get("品質建議", "")):
            if risk:
                x.at[idx, "品質建議"] = risk
            elif entry:
                x.at[idx, "品質建議"] = f"依等待條件進場：{entry}"
            else:
                x.at[idx, "品質建議"] = "依趨勢與量能確認後再操作"
        if is_blank(row.get("建議倉位%", "")):
            x.at[idx, "建議倉位%"] = 15 if s >= 90 else (10 if s >= 85 else (8 if s >= 80 else 5))
        if is_blank(row.get("動態建議倉位%", "")):
            x.at[idx, "動態建議倉位%"] = x.at[idx, "建議倉位%"]
        if is_blank(row.get("第一筆進場%", "")):
            try:
                x.at[idx, "第一筆進場%"] = round(float(x.at[idx, "建議倉位%"] or 0) * 0.5, 2)
            except Exception:
                x.at[idx, "第一筆進場%"] = ""
        if is_blank(row.get("建議投入等級", "")):
            x.at[idx, "建議投入等級"] = "高" if s >= 90 else ("中高" if s >= 85 else "中")
        if is_blank(row.get("分批策略", "")):
            x.at[idx, "分批策略"] = "先小部位試單，突破確認再加碼" if "突破" in (entry + action + buy_grade) else "分批低接，跌破支撐停止加碼"
        if is_blank(row.get("第二筆加碼條件", "")):
            x.at[idx, "第二筆加碼條件"] = "站穩突破價且量能續強" if s >= 85 else "等待量價轉強再評估"
        if is_blank(row.get("族群策略建議", "")):
            cat = text(row, "類別", "產業") or "同族群"
            x.at[idx, "族群策略建議"] = f"觀察{cat}族群強弱與資金延續性"
        if is_blank(row.get("K線驗證標記", "")):
            x.at[idx, "K線驗證標記"] = "待K線確認"
        if is_blank(row.get("K線檢視提示", "")):
            x.at[idx, "K線檢視提示"] = "檢查支撐、壓力、量能與長上影風險"
    return standardize_records_for_storage(x, keep_extras=True)
