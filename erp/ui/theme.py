import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

NAVY = "#0B1F3A"
NAVY_2 = "#14305A"
NAVY_3 = "#1F4A85"
ORANGE = "#FF7A00"
ORANGE_2 = "#FFA24D"
GREEN = "#1E9E5A"
RED = "#D64545"
AMBER = "#F2B138"
SLATE = "#5B6B82"
BG = "#F4F6FA"

CHART_COLORS = [ORANGE, NAVY_3, "#2BB3C0", AMBER, "#7B61FF", GREEN, "#E0567A", NAVY, ORANGE_2, SLATE]

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea, select {{
    font-family: 'Inter', 'Segoe UI', sans-serif !important;
}}
.block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1400px; }}
h1, h2, h3 {{ color: {NAVY}; font-weight: 700; }}
h2 {{ font-size: 24px; }}
h3 {{ font-size: 18px; }}
p, li {{ line-height: 1.55; }}
[data-testid="stCaptionContainer"] {{ color: {SLATE}; }}

/* Shared control rhythm */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button,
div[data-testid="stLinkButton"] > a {{
    min-height: 42px; height: 42px; box-sizing: border-box; padding: 0 16px;
    border-radius: 8px; font-size: 14px; font-weight: 600; line-height: 1.2;
    letter-spacing: 0; border: 1px solid #CBD4E1; background: #FFFFFF; color: {NAVY};
    box-shadow: 0 1px 2px rgba(11,31,58,.06);
    transition: background .15s ease, border-color .15s ease, box-shadow .15s ease;
}}
.stButton > button:hover, .stFormSubmitButton > button:hover,
.stDownloadButton > button:hover, div[data-testid="stLinkButton"] > a:hover {{
    border-color: {NAVY_3}; color: {NAVY}; background: #F7F9FC;
    box-shadow: 0 2px 6px rgba(11,31,58,.10);
}}
.stButton > button:focus-visible, .stFormSubmitButton > button:focus-visible,
.stDownloadButton > button:focus-visible {{ outline: 3px solid rgba(255,122,0,.28); outline-offset: 2px; }}
.stButton > button:disabled, .stFormSubmitButton > button:disabled {{
    opacity: .48; box-shadow: none; cursor: not-allowed;
}}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"],
.stDownloadButton > button[kind="primary"] {{
    background: linear-gradient(135deg, {ORANGE} 0%, #F05A24 100%);
    border: 1px solid {ORANGE}; color: #FFFFFF; box-shadow: 0 2px 7px rgba(255,122,0,.24);
}}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover,
.stDownloadButton > button[kind="primary"]:hover {{
    background: #EA6500; border-color: #EA6500; color: #FFFFFF;
    box-shadow: 0 3px 10px rgba(255,122,0,.30);
}}

/* Shared surface sizes */
div[data-testid="stVerticalBlockBorderWrapper"] {{
    border-radius: 10px; border: 1px solid #E0E6EF; background: #FFFFFF;
}}
div[data-testid="stVerticalBlockBorderWrapper"] > div {{ padding: 16px 18px; }}
div[data-testid="stForm"] {{
    border-radius: 10px; border-color: #E0E6EF; background: #FFFFFF; padding: 18px 20px;
}}
div[data-testid="stExpander"] details {{
    border-radius: 10px; border: 1px solid #E0E6EF; background: #FFFFFF;
}}
div[data-testid="stDataFrame"] {{ border-radius: 10px; overflow: hidden; border: 1px solid #E0E6EF; }}
div[data-testid="stTable"] {{ border-radius: 10px; overflow: hidden; }}
div[data-baseweb="input"] > div, div[data-baseweb="select"] > div,
div[data-baseweb="textarea"] > div {{
    min-height: 42px; border-radius: 8px !important; border-color: #C9D3E1 !important;
}}
div[data-baseweb="textarea"] > div {{ min-height: 84px; }}
label[data-testid="stWidgetLabel"] p {{ color: {NAVY}; font-size: 13px; font-weight: 600; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid #DCE3ED; }}
.stTabs [data-baseweb="tab"] {{
    min-height: 42px; padding: 9px 16px; border-radius: 8px 8px 0 0;
    font-weight: 600; color: {SLATE};
}}
.stTabs [aria-selected="true"] {{ color: {NAVY} !important; background: #FFFFFF; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: {ORANGE}; height: 3px; }}
div[data-testid="stAlert"] {{ border-radius: 8px; }}
div[data-testid="stProgress"] > div > div {{ background-color: {ORANGE}; }}

/* Sidebar */
section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {NAVY} 0%, {NAVY_2} 100%);
    border-right: 4px solid {ORANGE};
}}
section[data-testid="stSidebar"] * {{ color: #E6ECF5 !important; }}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"] {{
    border-radius: 8px; margin: 2px 0; transition: all .15s ease;
}}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"]:hover {{
    background: rgba(255,122,0,.18);
}}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"][aria-current="page"] {{
    background: {ORANGE}; box-shadow: 0 4px 14px rgba(255,122,0,.35);
}}
section[data-testid="stSidebar"] a[aria-current="page"] span {{ color: #FFFFFF !important; font-weight: 700; }}
section[data-testid="stSidebar"] button {{
    background: transparent !important; border: 1px solid rgba(255,255,255,.35) !important;
    min-height: 42px; height: 42px;
}}
section[data-testid="stSidebar"] button:hover {{ border-color: {ORANGE} !important; }}

/* Custom components */
.erp-header {{
    background: linear-gradient(120deg, {NAVY} 0%, {NAVY_2} 55%, {NAVY_3} 100%);
    border-radius: 14px; padding: 26px 30px; margin-bottom: 22px; position: relative; overflow: hidden;
    box-shadow: 0 10px 30px rgba(11,31,58,.18);
}}
.erp-header::after {{
    content: ""; position: absolute; right: -60px; top: -60px; width: 240px; height: 240px;
    background: radial-gradient(circle, rgba(255,122,0,.55) 0%, rgba(255,122,0,0) 70%);
}}
.erp-header .eyebrow {{
    color: {ORANGE}; font-size: 12px; font-weight: 700; letter-spacing: 2.5px; text-transform: uppercase;
}}
.erp-header h1 {{ color: #FFFFFF; font-size: 30px; font-weight: 800; margin: 4px 0 2px 0; padding: 0; }}
.erp-header p {{ color: #B8C6DB; margin: 0; font-size: 15px; }}

.kpi {{
    background: #FFFFFF; border-radius: 10px; padding: 18px 20px; border: 1px solid #E0E6EF;
    border-top: 3px solid {ORANGE}; box-shadow: 0 2px 8px rgba(11,31,58,.05);
    min-height: 112px; height: 100%;
}}
.kpi.navy {{ border-top-color: {NAVY_3}; }}
.kpi.green {{ border-top-color: {GREEN}; }}
.kpi.amber {{ border-top-color: {AMBER}; }}
.kpi .label {{ color: {SLATE}; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; }}
.kpi .value {{ color: {NAVY}; font-size: 28px; font-weight: 800; margin-top: 6px; line-height: 1.1; }}
.kpi .sub {{ color: {SLATE}; font-size: 13px; margin-top: 4px; }}

.badge {{
    display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 700;
    letter-spacing: .8px; text-transform: uppercase;
}}
.badge.PENDING {{ background: #FFF4E0; color: #B86E00; border: 1px solid #F2C27A; }}
.badge.APPROVED {{ background: #E3F6EC; color: #17804A; border: 1px solid #9BD8B6; }}
.badge.REJECTED {{ background: #FDE8E8; color: #B13232; border: 1px solid #F0A9A9; }}
.badge.LOW {{ background: #FFE9D6; color: #C25A00; border: 1px solid #FFB877; }}
.badge.SENT {{ background: #E3F6EC; color: #17804A; }}
.badge.FAILED {{ background: #FDE8E8; color: #B13232; }}
.badge.SKIPPED {{ background: #EEF1F6; color: {SLATE}; }}

.section-title {{
    font-size: 18px; font-weight: 800; color: {NAVY}; margin: 18px 0 10px 0;
    padding-left: 12px; border-left: 4px solid {ORANGE};
}}
.approval-card-head {{
    display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;
    margin-bottom: 12px;
}}
.approval-card-title {{ color: {NAVY}; font-size: 17px; font-weight: 700; line-height: 1.35; }}
.approval-card-meta {{ color: {SLATE}; font-size: 13px; line-height: 1.5; margin-top: 4px; }}
.approval-card-total {{ color: {ORANGE}; font-size: 21px; font-weight: 800; white-space: nowrap; text-align: right; }}
.approval-card-discount {{ color: {GREEN}; font-size: 12px; font-weight: 600; text-align: right; }}
.hint {{
    background: linear-gradient(90deg, #FFF4E8 0%, #FFFFFF 100%); border-left: 4px solid {ORANGE};
    padding: 10px 14px; border-radius: 8px; color: {NAVY}; font-size: 14px; margin: 6px 0;
}}
.hint.ok {{ background: linear-gradient(90deg, #E8F7EF 0%, #FFFFFF 100%); border-left-color: {GREEN}; }}
.hint.warn {{ background: linear-gradient(90deg, #FDECEC 0%, #FFFFFF 100%); border-left-color: {RED}; }}

.tier-row {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 4px 0 8px 0; }}
.tier {{
    border: 1px solid #D7DEEA; border-radius: 8px; padding: 6px 12px; font-size: 13px; background: #FFFFFF;
    color: {NAVY};
}}
.tier.active {{ background: {NAVY}; color: #FFFFFF; border-color: {NAVY}; }}
.tier.next {{ border: 2px dashed {ORANGE}; }}

.summary-card {{
    background: linear-gradient(160deg, {NAVY} 0%, {NAVY_3} 100%); color: #FFFFFF; border-radius: 14px;
    padding: 22px; box-shadow: 0 10px 30px rgba(11,31,58,.2);
}}
.summary-card .row {{ display: flex; justify-content: space-between; margin: 6px 0; color: #C9D5E6; }}
.summary-card .total {{
    display: flex; justify-content: space-between; margin-top: 12px; padding-top: 12px;
    border-top: 1px solid rgba(255,255,255,.2); font-size: 22px; font-weight: 800; color: #FFFFFF;
}}
.summary-card .total span:last-child {{ color: {ORANGE}; }}
.summary-card .save {{ color: #7BE0A8; }}

.login-brand {{ text-align: center; margin: 30px 0 10px 0; }}
.login-brand .logo {{
    display: inline-block; width: 64px; height: 64px; line-height: 64px; border-radius: 16px;
    background: linear-gradient(135deg, {ORANGE}, #FF5A1F); color: white; font-weight: 800; font-size: 26px;
    box-shadow: 0 8px 24px rgba(255,122,0,.4);
}}
.login-brand h2 {{ color: {NAVY}; font-weight: 800; margin: 14px 0 0 0; }}
.login-brand p {{ color: {SLATE}; margin: 4px 0 0 0; }}

.side-user {{
    background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.12); border-radius: 10px;
    padding: 12px 14px; margin-bottom: 10px;
}}
.side-user .n {{ font-weight: 700; font-size: 15px; }}
.side-user .r {{ font-size: 12px; opacity: .75; text-transform: uppercase; letter-spacing: 1px; }}
.side-brand {{ font-size: 20px; font-weight: 800; margin: 0 0 12px 0; }}
.side-brand span {{ color: {ORANGE} !important; }}
.bell {{
    display: inline-block; background: {ORANGE}; color: #FFFFFF !important; border-radius: 999px;
    padding: 1px 9px; font-size: 12px; font-weight: 800; margin-left: 6px;
}}

@media (max-width: 768px) {{
    .block-container {{ padding: 1rem .75rem 2rem; }}
    .erp-header {{ padding: 20px 22px; margin-bottom: 16px; }}
    .erp-header h1 {{ font-size: 25px; }}
    .kpi {{ min-height: 100px; padding: 16px; }}
    .kpi .value {{ font-size: 24px; }}
    .approval-card-head {{ flex-direction: column; gap: 6px; }}
    .approval-card-total, .approval-card-discount {{ text-align: left; }}
}}
</style>
"""


def apply_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def _plotly_template() -> None:
    template = go.layout.Template(pio.templates["plotly_white"])
    template.layout.colorway = CHART_COLORS
    template.layout.font = dict(family="Inter, Segoe UI, sans-serif", color=NAVY, size=13)
    template.layout.title = dict(font=dict(size=16, color=NAVY))
    template.layout.paper_bgcolor = "#FFFFFF"
    template.layout.plot_bgcolor = "#FFFFFF"
    template.layout.margin = dict(l=20, r=20, t=50, b=20)
    template.layout.hoverlabel = dict(bgcolor=NAVY, font=dict(color="#FFFFFF"))
    template.layout.xaxis = dict(gridcolor="#EEF1F6", linecolor="#D7DEEA")
    template.layout.yaxis = dict(gridcolor="#EEF1F6", linecolor="#D7DEEA")
    pio.templates["erp"] = template
    pio.templates.default = "erp"


_plotly_template()
