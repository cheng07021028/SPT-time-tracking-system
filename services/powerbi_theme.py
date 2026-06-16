from __future__ import annotations

from typing import Any, Iterable

import plotly.graph_objects as go
try:
    import streamlit as st
except Exception:  # allow non-Streamlit export tests
    st = None

POWERBI_COLORS = [
    "#66C7FF",  # luminous blue
    "#118DFF",  # Power BI blue
    "#744EC2",  # violet
    "#E66C37",  # orange
    "#E044A7",  # magenta
    "#D9B300",  # gold
    "#1AAB40",  # green
    "#D64550",  # red
    "#197278",  # teal
    "#12239E",  # deep blue
]
POWERBI_BG = "rgba(2, 6, 23, 0.98)"
POWERBI_PLOT = "rgba(10, 18, 34, 0.96)"
POWERBI_GRID = "rgba(148, 163, 184, 0.19)"
POWERBI_TEXT = "#FFFFFF"
POWERBI_MUTED = "#C8D7EA"
POWERBI_LABEL_BG = "rgba(2, 6, 23, 0.72)"


def _apply_trace_palette(fig: go.Figure) -> None:
    """Apply a Power BI inspired palette and subtle depth to every trace."""
    for idx, trace in enumerate(fig.data):
        color = POWERBI_COLORS[idx % len(POWERBI_COLORS)]
        if trace.type == "pie":
            raw_labels = getattr(trace, "labels", None)
            labels = [] if raw_labels is None else list(raw_labels)
            trace.update(
                marker=dict(colors=POWERBI_COLORS, line=dict(color="rgba(255,255,255,0.22)", width=1.4)),
                textfont=dict(color=POWERBI_TEXT, size=13),
                pull=[0.035] * len(labels),
                hole=0.40,
                sort=False,
                hoverlabel=dict(bgcolor="#07111F", bordercolor="#38BDF8", font=dict(color="#FFFFFF")),
            )
        elif trace.type in {"bar", "histogram"}:
            # Plotly does not support true gradient bars in ordinary traces, so use a crisp outline,
            # high-opacity color, and chart-card shadows from ui_theme.py for a Power BI 3D-like feel.
            trace.update(
                marker=dict(
                    color=color,
                    line=dict(color="rgba(255,255,255,0.30)", width=1.35),
                    opacity=0.98,
                ),
                hoverlabel=dict(bgcolor="#07111F", bordercolor=color, font=dict(color="#FFFFFF")),
            )
        elif trace.type in {"scatter", "scattergl"}:
            trace.update(
                line=dict(color=color, width=3.8, shape="spline"),
                marker=dict(color=color, size=9.5, line=dict(color="rgba(255,255,255,0.68)", width=1.25)),
                hoverlabel=dict(bgcolor="#07111F", bordercolor=color, font=dict(color="#FFFFFF")),
            )


def _format_label_value(value: Any, suffix: str = "") -> str:
    """Return a safe, visible label string. Avoid Plotly numeric texttemplate failures."""
    try:
        if value is None:
            return ""
        number = float(value)
        if suffix == "%":
            return f"{number:.1f}%"
        if abs(number) >= 1000:
            return f"{number:,.0f}"
        if abs(number - round(number)) > 0.01:
            return f"{number:,.1f}"
        return f"{number:,.0f}"
    except Exception:
        text = str(value).strip()
        return "" if text.lower() in {"nan", "none", "nat", "<na>"} else text


def _label_list(values: Iterable[Any], suffix: str = "") -> list[str]:
    iterable = [] if values is None else values
    return [_format_label_value(value, suffix=suffix) for value in iterable]


def _apply_data_labels(fig: go.Figure, show: bool) -> None:
    """Show or hide value labels for every chart type without changing source data."""
    for trace in fig.data:
        if trace.type == "pie":
            trace.update(
                textinfo="label+percent+value" if show else "percent",
                textposition="auto",
                textfont=dict(color=POWERBI_TEXT, size=13),
                insidetextfont=dict(color=POWERBI_TEXT, size=13),
                outsidetextfont=dict(color=POWERBI_TEXT, size=13),
            )
            continue
        if trace.type in {"bar", "histogram"}:
            orientation = str(getattr(trace, "orientation", None) or "v")
            values = getattr(trace, "x", None) if orientation == "h" else getattr(trace, "y", None)
            if show:
                trace.update(
                    text=_label_list(values),
                    texttemplate="%{text}",
                    textposition="outside",
                    cliponaxis=False,
                    constraintext="none",
                    insidetextanchor="middle",
                    textfont=dict(color="#FFFFFF", size=14, family="Microsoft JhengHei, Noto Sans TC, Arial"),
                    insidetextfont=dict(color="#FFFFFF", size=14),
                    outsidetextfont=dict(color="#FFFFFF", size=14),
                )
            else:
                trace.update(text=None, texttemplate=None, textposition=None)
            continue
        if trace.type in {"scatter", "scattergl"}:
            values = getattr(trace, "y", None)
            if show:
                mode = str(getattr(trace, "mode", "lines+markers") or "lines+markers")
                if "text" not in mode:
                    mode = f"{mode}+text"
                trace.update(
                    mode=mode,
                    text=_label_list(values),
                    texttemplate="%{text}",
                    textposition="top center",
                    textfont=dict(color="#FFFFFF", size=14, family="Microsoft JhengHei, Noto Sans TC, Arial"),
                )
            else:
                mode = str(getattr(trace, "mode", "lines+markers") or "lines+markers")
                mode = mode.replace("+text", "").replace("text+", "").replace("text", "lines+markers")
                trace.update(mode=mode, text=None, texttemplate=None)


def style_powerbi_figure(
    fig: go.Figure,
    *,
    height: int = 420,
    title: str | None = None,
    legend_title: str | None = None,
    yaxis_title: str | None = None,
    xaxis_title: str | None = None,
) -> go.Figure:
    """Apply a polished Power BI inspired dark visual style to a Plotly figure."""
    fig = go.Figure(fig)
    _apply_trace_palette(fig)
    if title:
        fig.update_layout(title=title)
    fig.update_layout(
        height=height,
        paper_bgcolor=POWERBI_BG,
        plot_bgcolor=POWERBI_PLOT,
        colorway=POWERBI_COLORS,
        font=dict(family="Noto Sans TC, Microsoft JhengHei, Segoe UI, Arial", color=POWERBI_TEXT, size=13),
        title=dict(font=dict(size=20, color=POWERBI_TEXT), x=0.02, xanchor="left", y=0.98),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.05,
            xanchor="left",
            x=0.0,
            bgcolor="rgba(2,6,23,0.58)",
            bordercolor="rgba(56,189,248,0.25)",
            borderwidth=1,
            font=dict(color=POWERBI_TEXT, size=12),
            title=dict(text=legend_title or "", font=dict(color=POWERBI_MUTED, size=12)),
            itemwidth=30,
        ),
        margin=dict(l=54, r=70, t=118, b=62),
        hoverlabel=dict(bgcolor="#07111F", bordercolor="#38BDF8", font=dict(color="#FFFFFF", size=12)),
        bargap=0.24,
        bargroupgap=0.08,
        separators=".,",
        uniformtext=dict(minsize=10, mode="show"),
        transition=dict(duration=180),
    )
    fig.update_xaxes(
        title_text=xaxis_title,
        showgrid=False,
        zeroline=False,
        showline=True,
        linecolor="rgba(203,213,225,.36)",
        tickfont=dict(color=POWERBI_TEXT, size=12),
        title_font=dict(color=POWERBI_MUTED, size=13),
        automargin=True,
    )
    fig.update_yaxes(
        title_text=yaxis_title,
        gridcolor=POWERBI_GRID,
        zerolinecolor="rgba(148,163,184,0.22)",
        showline=True,
        linecolor="rgba(203,213,225,.25)",
        tickfont=dict(color=POWERBI_TEXT, size=12),
        title_font=dict(color=POWERBI_MUTED, size=13),
        automargin=True,
    )
    return fig


def render_powerbi_chart(
    fig: go.Figure,
    *,
    key: str | None = None,
    height: int | None = None,
    label_toggle: bool = True,
    default_show_values: bool = False,
) -> None:
    """Render a Power BI-like chart with an optional show/hide data-label checkbox."""
    fig_to_render = go.Figure(fig)
    if height:
        fig_to_render.update_layout(height=height)
    if st is None:
        return
    show_values = False
    if label_toggle:
        control_key = f"{key or 'powerbi_chart'}_show_values"
        st.markdown('<div class="chart-label-control">', unsafe_allow_html=True)
        show_values = st.checkbox("顯示圖表數據標籤", value=default_show_values, key=control_key)
        st.markdown('</div>', unsafe_allow_html=True)
    _apply_data_labels(fig_to_render, show_values)
    st.plotly_chart(
        fig_to_render,
        use_container_width=True,
        config={"displayModeBar": False, "responsive": True},
        key=key,
    )


def chart_spec(
    chart_type: str,
    title: str,
    data_sheet: str,
    category_col: str,
    value_cols: list[str],
    **kwargs: Any,
) -> dict[str, Any]:
    """Create an Excel report chart specification."""
    spec = {
        "type": chart_type,
        "title": title,
        "data_sheet": data_sheet,
        "category_col": category_col,
        "value_cols": value_cols,
    }
    spec.update(kwargs)
    return spec
