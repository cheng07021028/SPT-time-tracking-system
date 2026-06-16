from __future__ import annotations

import hashlib
import html

import pandas as pd


def _safe_text(value: object, default: str = "未設定") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat", "<na>"}:
        return default
    return text


def _slug(value: object, prefix: str = "node") -> str:
    text = _safe_text(value, prefix)
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def build_people_frame(employees: pd.DataFrame, dispatch: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for source, df in [("超慧正職", employees), ("派遣/外包", dispatch)]:
        if df is None or df.empty:
            continue
        temp = df.copy()
        if "人力來源" not in temp.columns:
            temp["人力來源"] = source
        else:
            temp["人力來源"] = temp["人力來源"].fillna(source).replace("", source)
        frames.append(temp)

    base_columns = ["課別", "工段", "姓名", "職稱", "人力來源", "是否直接人力", "可用比例"]
    if not frames:
        return pd.DataFrame(columns=base_columns)

    people = pd.concat(frames, ignore_index=True)
    people = people.rename(columns={"職 稱": "職稱"})

    for col in ["課別", "工段", "姓名", "職稱", "人力來源", "是否直接人力"]:
        if col not in people.columns:
            people[col] = "未設定"
        people[col] = people[col].map(_safe_text)

    if "可用比例" not in people.columns:
        people["可用比例"] = 1.0
    people["可用比例"] = pd.to_numeric(people["可用比例"], errors="coerce").fillna(0)

    sort_cols = [col for col in ["課別", "工段", "人力來源", "姓名"] if col in people.columns]
    if sort_cols:
        people = people.sort_values(sort_cols, kind="stable").reset_index(drop=True)
    return people


def _person_card(row: pd.Series) -> str:
    direct = _safe_text(row.get("是否直接人力", "否"), "否")
    direct_class = "direct" if direct == "是" else "indirect"
    return (
        f'<div class="org-person-card {direct_class}">'
        f'<div class="org-person-name">{html.escape(_safe_text(row.get("姓名", ""), "未命名"))}</div>'
        f'<div class="org-person-meta">{html.escape(_safe_text(row.get("職稱", "未設定")))}</div>'
        f'</div>'
    )


def _normalize_people(people: pd.DataFrame) -> pd.DataFrame:
    people = build_people_frame(people, pd.DataFrame()) if "人力來源" not in people.columns else people.copy()
    for col in ["課別", "工段", "姓名", "職稱", "人力來源", "是否直接人力"]:
        if col not in people.columns:
            people[col] = "未設定"
        people[col] = people[col].map(_safe_text)
    if "可用比例" not in people.columns:
        people["可用比例"] = 0
    people["可用比例"] = pd.to_numeric(people["可用比例"], errors="coerce").fillna(0)
    return people


def render_org_html(people: pd.DataFrame) -> str:
    """卷軸式組織圖。卡片只顯示姓名與職稱，縮小後更接近提供的 Excel 組織圖檢視。"""
    if people is None or people.empty:
        return "<div class='tech-card'>目前沒有組織資料。</div>"

    people = _normalize_people(people)
    parts: list[str] = ["<div class='org-chart-wrap'>"]
    parts.append("<section class='org-dept-card breathing-glow'><div class='org-dept-title'>製造部<span>依課別 / 工段 / 人員呈現</span></div>")
    parts.append("<div class='org-group-grid'>")
    for dept in people["課別"].dropna().astype(str).drop_duplicates().tolist():
        dept_df = people[people["課別"].astype(str).eq(dept)].copy()
        total = len(dept_df)
        direct = int((dept_df["是否直接人力"].astype(str) == "是").sum()) if "是否直接人力" in dept_df.columns else total
        parts.append("<div class='org-group-card'>")
        parts.append(f"<div class='org-group-title'>{html.escape(dept)}<span>{total} 人｜直接 {direct}</span></div>")
        for group in dept_df["工段"].dropna().astype(str).drop_duplicates().tolist():
            group_df = dept_df[dept_df["工段"].astype(str).eq(group)].copy()
            parts.append(f"<div class='org-subgroup-title'>{html.escape(group)}<span>{len(group_df)} 人</span></div>")
            for _, row in group_df.sort_values(["人力來源", "姓名"], kind="stable").iterrows():
                parts.append(_person_card(row))
        parts.append("</div>")
    parts.append("</div></section></div>")
    return "".join(parts)


def _drag_person(row: pd.Series, index: int) -> str:
    direct = _safe_text(row.get("是否直接人力", "否"), "否")
    direct_class = "direct" if direct == "是" else "indirect"
    name = html.escape(_safe_text(row.get("姓名", ""), "未命名"))
    title = html.escape(_safe_text(row.get("職稱", "未設定")))
    return (
        f'<div class="tree-person-card {direct_class}" draggable="true" data-drag-type="person" data-card-id="person_{index}">'
        f'<span class="tree-handle">⋮⋮</span><b>{name}</b><em>{title}</em>'
        f'</div>'
    )


def _tree_inner(people: pd.DataFrame) -> str:
    if people is None or people.empty:
        return '<div class="tree-empty">目前沒有組織資料。</div>'
    people = _normalize_people(people)
    parts: list[str] = ['<div class="tree-org-root drop-zone" data-zone="root">']
    parts.append('<div class="tree-root-node"><div class="tree-root-title">製造部</div><div class="tree-root-sub">Manufacturing Department</div></div>')
    parts.append('<div class="tree-trunk"></div><div class="tree-dept-row drop-zone" data-zone="root">')
    person_idx = 0
    for dept in people["課別"].dropna().astype(str).drop_duplicates().tolist():
        dept_df = people[people["課別"].astype(str).eq(dept)].copy()
        total = len(dept_df)
        direct = int((dept_df["是否直接人力"].astype(str) == "是").sum()) if "是否直接人力" in dept_df.columns else total
        dept_id = _slug(dept, "dept")
        parts.append(f'<section class="tree-dept-card" draggable="true" data-drag-type="dept" data-card-id="{dept_id}">')
        parts.append(f'<div class="tree-dept-head"><span class="tree-handle">☰</span><div><b>{html.escape(dept)}</b><em>{total} 人｜直接 {direct}</em></div><button class="tree-expand" type="button">全螢幕</button></div>')
        parts.append('<div class="tree-branch-line"></div><div class="tree-group-row drop-zone" data-zone="dept">')
        for group in dept_df["工段"].dropna().astype(str).drop_duplicates().tolist():
            group_df = dept_df[dept_df["工段"].astype(str).eq(group)].copy()
            group_id = _slug(f"{dept}|{group}", "group")
            parts.append(f'<article class="tree-group-card" draggable="true" data-drag-type="group" data-card-id="{group_id}">')
            parts.append(f'<div class="tree-group-head"><span class="tree-handle">↕</span><b>{html.escape(group)}</b><em>{len(group_df)} 人</em></div>')
            parts.append('<div class="tree-person-zone drop-zone" data-zone="group">')
            for _, row in group_df.sort_values(["人力來源", "姓名"], kind="stable").iterrows():
                parts.append(_drag_person(row, person_idx))
                person_idx += 1
            parts.append('</div></article>')
        parts.append('</div></section>')
    parts.append('</div></div>')
    return "".join(parts)


def render_org_component_html(people: pd.DataFrame) -> str:
    """Return a self-contained tree org chart where dept/group/person cards can be dragged and reordered."""
    inner = _tree_inner(people)
    return f'''<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8" />
<style>
:root {{ --bg:#06111F; --panel:rgba(10,25,45,.86); --cyan:#00D4FF; --blue:#118DFF; --violet:#744EC2; --text:#E8F6FF; --muted:#9FB6C8; --orange:#FFB547; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:transparent; font-family:"Noto Sans TC","Microsoft JhengHei","Segoe UI",Arial,sans-serif; color:var(--text); }}
.tree-toolbar {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px; padding:10px 12px; border:1px solid rgba(0,212,255,.30); border-radius:18px; background:linear-gradient(135deg,rgba(17,141,255,.18),rgba(116,78,194,.14)); box-shadow:0 0 24px rgba(17,141,255,.16), inset 0 0 16px rgba(255,255,255,.03); }}
.tree-toolbar b {{ color:#fff; font-size:16px; }}
.tree-toolbar span {{ color:var(--muted); font-size:13px; }}
.tree-toolbar button {{ color:#fff; background:rgba(17,141,255,.20); border:1px solid rgba(0,212,255,.35); border-radius:11px; padding:7px 12px; cursor:pointer; font-weight:900; }}
.tree-shell {{ height:780px; margin-top:12px; overflow:auto; border:1px solid rgba(0,212,255,.30); border-radius:24px; padding:18px; background:radial-gradient(circle at 12% 18%, rgba(0,212,255,.16), transparent 24%), radial-gradient(circle at 88% 22%, rgba(116,78,194,.16), transparent 26%), linear-gradient(135deg, rgba(2,6,23,.96), rgba(8,13,27,.96)); box-shadow:0 0 34px rgba(17,141,255,.16), inset 0 0 30px rgba(255,255,255,.025); }}
.tree-shell::-webkit-scrollbar {{ height:12px; width:12px; }}
.tree-shell::-webkit-scrollbar-thumb {{ background:rgba(0,212,255,.36); border-radius:999px; }}
.tree-org-root {{ min-width:1180px; display:flex; flex-direction:column; align-items:center; gap:0; }}
.tree-root-node {{ min-width:240px; text-align:center; padding:16px 28px; border-radius:24px; border:1px solid rgba(0,212,255,.52); background:linear-gradient(145deg,rgba(17,141,255,.28),rgba(116,78,194,.16)); box-shadow:0 0 28px rgba(0,212,255,.24); }}
.tree-root-title {{ color:#fff; font-size:1.5rem; font-weight:950; }}
.tree-root-sub {{ color:#9FDFFF; font-size:.82rem; margin-top:4px; }}
.tree-trunk {{ width:2px; height:28px; background:linear-gradient(#00D4FF, rgba(0,212,255,.08)); box-shadow:0 0 12px #00D4FF; }}
.tree-dept-row {{ width:100%; display:grid; grid-template-columns:repeat(auto-fit,minmax(480px,1fr)); gap:22px; align-items:start; }}
.tree-dept-card {{ position:relative; border:1px solid rgba(0,212,255,.38); border-radius:24px; padding:14px; background:rgba(6,17,31,.84); box-shadow:0 0 24px rgba(0,212,255,.13); }}
.tree-dept-card::before {{ content:""; position:absolute; top:-20px; left:50%; width:2px; height:20px; background:rgba(0,212,255,.55); }}
.tree-dept-head {{ display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:10px; }}
.tree-dept-head b {{ display:block; color:#fff; font-size:1.16rem; }}
.tree-dept-head em, .tree-group-head em {{ display:block; color:#8FDFFF; font-size:.78rem; font-style:normal; font-weight:800; }}
.tree-expand {{ color:#fff; background:rgba(0,212,255,.14); border:1px solid rgba(0,212,255,.34); border-radius:10px; padding:6px 9px; cursor:pointer; font-size:.78rem; font-weight:900; }}
.tree-group-row {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px; min-height:44px; }}
.tree-group-card {{ border:1px solid rgba(116,78,194,.38); border-radius:18px; padding:9px; background:rgba(10,25,45,.80); box-shadow:inset 0 0 12px rgba(255,255,255,.025); }}
.tree-group-head {{ display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:8px; }}
.tree-group-head b {{ color:var(--cyan); font-size:.95rem; }}
.tree-person-zone {{ min-height:32px; padding:1px; border-radius:10px; }}
.tree-person-card {{ position:relative; display:flex; align-items:center; gap:8px; border-left:3px solid rgba(0,212,255,.86); background:rgba(255,255,255,.05); border-radius:11px; padding:6px 8px; margin:5px 0; box-shadow:0 0 12px rgba(17,141,255,.07), inset 0 0 8px rgba(255,255,255,.02); cursor:grab; min-height:34px; }}
.tree-person-card.indirect {{ border-left-color:rgba(255,181,71,.90); }}
.tree-person-card b {{ color:#fff; font-size:.9rem; white-space:nowrap; }}
.tree-person-card em {{ color:var(--muted); font-style:normal; font-size:.72rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.tree-handle {{ color:#8FDFFF; font-weight:900; cursor:grab; user-select:none; }}
.dragging {{ opacity:.46; transform:scale(.985); }}
.drop-active {{ outline:2px dashed rgba(0,212,255,.65); outline-offset:4px; background:rgba(0,212,255,.07); }}
.tree-dept-card.expanded {{ position:fixed; inset:16px; z-index:9999; overflow:auto; background:linear-gradient(145deg,rgba(2,6,23,.98),rgba(10,25,45,.98)); padding:22px; }}
.tree-dept-card.expanded .tree-group-row {{ grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); }}
.tree-empty {{ padding:18px; border:1px solid rgba(0,212,255,.26); border-radius:18px; background:rgba(10,25,45,.72); }}
.local-note {{ color:#FFECB0 !important; }}
</style>
</head>
<body>
  <div class="tree-toolbar">
    <b>樹枝圖組織圖</b>
    <span>架構：製造部 → 製一課 / 製二課 → 工段 → 人員。</span>
    <span class="local-note">可拖拉課別、工段、人員卡片調整展示位置；正式歸屬仍以 01/02 頁權威資料為準。</span>
    <button id="saveLayout" type="button">保存目前版面於瀏覽器</button>
    <button id="resetLayout" type="button">重置版面</button>
  </div>
  <div class="tree-shell"><div id="layoutSource" style="display:none">{inner}</div><div id="layoutMount">{inner}</div></div>
<script>
(function() {{
  const KEY = 'spt_capacity_org_tree_layout_v3';
  const mount = document.getElementById('layoutMount');
  const source = document.getElementById('layoutSource');
  const saved = localStorage.getItem(KEY);
  if (saved) {{ mount.innerHTML = saved; }}
  let dragged = null;
  function canDrop(card, zone) {{
    if (!card || !zone) return false;
    const t = card.dataset.dragType;
    const z = zone.dataset.zone;
    return (t === 'dept' && z === 'root') || (t === 'group' && z === 'dept') || (t === 'person' && z === 'group');
  }}
  document.addEventListener('click', function(e) {{
    const btn = e.target.closest('.tree-expand');
    if (!btn) return;
    const dept = btn.closest('.tree-dept-card');
    if (!dept) return;
    dept.classList.toggle('expanded');
    btn.textContent = dept.classList.contains('expanded') ? '還原' : '全螢幕';
  }});
  document.addEventListener('dragstart', function(e) {{
    const card = e.target.closest('[data-drag-type]');
    if (!card) return;
    dragged = card;
    card.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', card.dataset.cardId || 'card');
  }});
  document.addEventListener('dragend', function() {{
    if (dragged) dragged.classList.remove('dragging');
    dragged = null;
    document.querySelectorAll('.drop-active').forEach(x => x.classList.remove('drop-active'));
  }});
  document.addEventListener('dragover', function(e) {{
    const zone = e.target.closest('.drop-zone');
    if (canDrop(dragged, zone)) {{ e.preventDefault(); zone.classList.add('drop-active'); }}
  }});
  document.addEventListener('dragleave', function(e) {{
    const zone = e.target.closest('.drop-zone');
    if (zone) zone.classList.remove('drop-active');
  }});
  document.addEventListener('drop', function(e) {{
    const zone = e.target.closest('.drop-zone');
    if (!canDrop(dragged, zone)) return;
    e.preventDefault();
    zone.classList.remove('drop-active');
    const targetCard = e.target.closest('[data-drag-type]');
    if (targetCard && targetCard !== dragged && targetCard.parentElement === zone) {{
      const rect = targetCard.getBoundingClientRect();
      const before = (e.clientY - rect.top) < rect.height / 2;
      zone.insertBefore(dragged, before ? targetCard : targetCard.nextSibling);
    }} else {{ zone.appendChild(dragged); }}
  }});
  document.getElementById('saveLayout').addEventListener('click', function() {{
    localStorage.setItem(KEY, mount.innerHTML);
    this.textContent = '已保存於瀏覽器';
    setTimeout(() => this.textContent = '保存目前版面於瀏覽器', 1600);
  }});
  document.getElementById('resetLayout').addEventListener('click', function() {{
    localStorage.removeItem(KEY);
    mount.innerHTML = source.innerHTML;
  }});
}})();
</script>
</body>
</html>'''
