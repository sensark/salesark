from html import escape

import streamlit as st


def page_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    st.markdown(
        f"""<div class="erp-header">
            {f'<div class="eyebrow">{escape(eyebrow)}</div>' if eyebrow else ''}
            <h1>{escape(title)}</h1>
            {f'<p>{escape(subtitle)}</p>' if subtitle else ''}
        </div>""",
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: str, sub: str = "", variant: str = "") -> None:
    subtitle = f'<div class="sub">{escape(sub)}</div>' if sub else ""
    st.markdown(
        f"""<div class="kpi {escape(variant)}">
            <div class="label">{escape(label)}</div>
            <div class="value">{escape(value)}</div>{subtitle}
        </div>""",
        unsafe_allow_html=True,
    )


def kpi_row(cards: list[tuple]) -> None:
    for col, card in zip(st.columns(len(cards)), cards):
        with col:
            kpi_card(*card)


def badge(text: str, kind: str | None = None) -> str:
    return f'<span class="badge {escape(kind or text)}">{escape(text)}</span>'


def section(title: str) -> None:
    st.markdown(f'<div class="section-title">{escape(title)}</div>', unsafe_allow_html=True)


def hint(text: str, kind: str = "") -> None:
    st.markdown(f'<div class="hint {escape(kind)}">{escape(text)}</div>', unsafe_allow_html=True)


def currency(value: float) -> str:
    return f"₹{value:,.2f}"


def compact_currency(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"₹{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"₹{value / 1_000:.1f}K"
    return f"₹{value:,.0f}"
