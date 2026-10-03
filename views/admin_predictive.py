from datetime import timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from erp.auth import require_role
from erp.db import session_scope
from erp.models import ROLE_ADMIN, ROLE_SALES_MANAGER
from erp.services import predictions as pr
from erp.ui.components import compact_currency, hint, kpi_row, page_header, section
from erp.ui.theme import AMBER, GREEN, NAVY_3, ORANGE, RED

user = require_role(ROLE_ADMIN, ROLE_SALES_MANAGER)
page_header("Predictive Insights", "Machine-learning forecasts and recommended actions.", "Administration")

SEGMENT_COLORS = {"Champions": GREEN, "Loyal": NAVY_3, "At risk": AMBER, "Dormant": RED}
MODEL_LABELS = {
    "churn": "Customer churn", "clv": "Customer lifetime value (90d)", "segmentation": "RFM segmentation",
    "payment_risk": "Late-payment risk", "quote_win": "Quotation win probability",
    "forecast": "Prophet demand forecast",
}


@st.cache_data(ttl=120, show_spinner="Loading predictions...")
def load() -> dict:
    with session_scope() as session:
        return {
            "customers": pr.customer_scores_frame(session),
            "reorder": pr.reorder_frame(session),
            "invoices": pr.invoice_risk_frame(session),
            "quotes": pr.quote_scores_frame(session),
            "health": pr.model_health(session),
            "trained_at": pr.last_trained_at(session),
        }


def retrain() -> None:
    with st.spinner("Training models on the latest data..."):
        with session_scope() as session:
            pr.train_all(session, user.id)
    load.clear()


def retrain_forecast() -> None:
    with st.spinner("Training Prophet on weekly product demand..."):
        with session_scope() as session:
            result = pr.train_forecast_only(session, user.id)
    load.clear()
    st.success(f"Prophet forecasts refreshed for {result.n_samples} products.")


data = load()
forecast_run = next(
    (run for run in data["health"] if run["model"] == "forecast"), None
)
forecast_is_prophet = forecast_run and forecast_run["method"] == "prophet"
top = st.columns([2.5, 1, 1.5])
with top[0]:
    if data["trained_at"] and forecast_is_prophet:
        hint(f"Scores last refreshed {data['trained_at']:%d %b %Y %H:%M}. Retrain after significant new activity.")
    elif data["trained_at"]:
        hint("Demand forecasts still use the previous model. Click Retrain models to refresh them with Prophet.", "warn")
    else:
        hint("Models have not been trained yet. Click Retrain to build them from current data.", "warn")
with top[1]:
    if st.button("Retrain all models", type="primary", width="stretch"):
        try:
            retrain()
            st.success("Models retrained.")
            st.rerun()
        except PermissionError as exc:
            st.error(str(exc))
with top[2]:
    if st.button("Retrain Prophet forecast", width="stretch"):
        try:
            retrain_forecast()
            st.rerun()
        except PermissionError as exc:
            st.error(str(exc))

customers = data["customers"]
if customers.empty:
    st.stop()

reorder, invoices, quotes = data["reorder"], data["invoices"], data["quotes"]
high = customers[customers["churn_probability"] >= pr.HIGH_CHURN]
kpi_row([
    ("High churn risk", str(len(high)), f"{len(high) / len(customers) * 100:.0f}% of active customers", "amber"),
    ("Revenue at risk (90d)", compact_currency(float(customers["value_at_risk"].sum())), "Churn probability × value"),
    ("Predicted 90d revenue", compact_currency(float(customers["clv_90d"].sum())), "Sum of customer CLV", "green"),
    ("Products to reorder", str(int((reorder["suggested_qty"] > 0).sum())) if not reorder.empty else "0",
     "Below forecast reorder point", "navy"),
    ("Weighted pipeline", compact_currency(float(quotes["expected_value"].sum())) if not quotes.empty else "₹0",
     f"{len(quotes)} open quotations", "navy"),
])
st.write("")

tabs = st.tabs(["Churn and Retention", "Segments and CLV", "Demand and Reorder", "Payment Risk",
                "Quotation Win", "Model Health"])

with tabs[0]:
    c1, c2 = st.columns([1, 1.4])
    with c1:
        fig = px.histogram(customers, x="churn_probability", nbins=20, title="Churn probability distribution")
        fig.update_traces(marker_color=ORANGE)
        fig.add_vline(x=pr.HIGH_CHURN, line_dash="dash", line_color=RED)
        fig.update_layout(height=340, xaxis_tickformat=".0%", xaxis_title=None, yaxis_title="Customers")
        st.plotly_chart(fig)
    with c2:
        fig = px.scatter(customers, x="churn_probability", y="monetary", size="value_at_risk", color="segment",
                         hover_name="customer", color_discrete_map=SEGMENT_COLORS, size_max=36,
                         title="Risk vs historical value")
        fig.update_layout(height=340, xaxis_tickformat=".0%", yaxis_tickprefix="₹", xaxis_title="Churn probability",
                          yaxis_title="Lifetime revenue")
        st.plotly_chart(fig)
    section("Retention action list")
    actions = customers[customers["churn_probability"] >= pr.MEDIUM_CHURN] \
        .sort_values("value_at_risk", ascending=False)
    if actions.empty:
        st.info("No customers above the medium churn threshold.")
    else:
        st.dataframe(
            actions[["customer", "company", "region", "sales_person", "churn_probability", "value_at_risk",
                     "recency_days", "segment", "drivers", "action", "phone"]],
            hide_index=True, height=420,
            column_config={
                "churn_probability": st.column_config.ProgressColumn("Churn risk", format="percent", min_value=0, max_value=1),
                "value_at_risk": st.column_config.NumberColumn("Value at risk", format="₹%.0f"),
                "recency_days": st.column_config.NumberColumn("Days since order"),
                "drivers": st.column_config.TextColumn("Why", width="large"),
                "action": st.column_config.TextColumn("Recommended action", width="large"),
            },
        )
        st.download_button("Download action list", actions.drop(columns=["scored_at"]).to_csv(index=False),
                           "retention-actions.csv", "text/csv")

with tabs[1]:
    seg = customers.groupby("segment").agg(
        customers=("customer_id", "count"), revenue=("monetary", "sum"), clv=("clv_90d", "sum"),
        churn=("churn_probability", "mean"), recency=("recency_days", "mean"),
    ).reindex(list(SEGMENT_COLORS)).dropna(how="all").reset_index()
    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(seg, x="segment", y="customers", color="segment", color_discrete_map=SEGMENT_COLORS,
                     title="Customers per segment")
        fig.update_layout(height=340, showlegend=False, xaxis_title=None)
        st.plotly_chart(fig)
    with c2:
        fig = px.bar(seg, x="segment", y=["revenue", "clv"], barmode="group", title="Historical revenue vs predicted 90d")
        fig.update_layout(height=340, yaxis_tickprefix="₹", xaxis_title=None, legend_title=None)
        st.plotly_chart(fig)
    st.dataframe(seg, hide_index=True, column_config={
        "revenue": st.column_config.NumberColumn("Lifetime revenue", format="₹%.0f"),
        "clv": st.column_config.NumberColumn("Predicted 90d", format="₹%.0f"),
        "churn": st.column_config.NumberColumn("Avg churn risk", format="percent"),
        "recency": st.column_config.NumberColumn("Avg days since order", format="%.0f"),
    })
    section("Top customers by predicted 90-day value")
    st.dataframe(
        customers.sort_values("clv_90d", ascending=False).head(15)[
            ["customer", "company", "region", "segment", "clv_90d", "monetary", "frequency", "churn_probability"]],
        hide_index=True,
        column_config={
            "clv_90d": st.column_config.NumberColumn("Predicted 90d", format="₹%.0f"),
            "monetary": st.column_config.NumberColumn("Lifetime revenue", format="₹%.0f"),
            "churn_probability": st.column_config.NumberColumn("Churn risk", format="percent"),
        },
    )

with tabs[2]:
    if reorder.empty:
        st.info("No forecasts available.")
    else:
        need = reorder[reorder["suggested_qty"] > 0].sort_values("days_of_cover", na_position="first")
        section(f"Reorder recommendations ({len(need)})")
        st.dataframe(
            need[["sku", "product", "category", "stock", "weekly_demand", "days_of_cover", "reorder_point",
                  "suggested_qty", "method"]],
            hide_index=True,
            column_config={
                "weekly_demand": st.column_config.NumberColumn("Forecast / week", format="%.1f"),
                "days_of_cover": st.column_config.NumberColumn("Days of cover", format="%.0f"),
                "reorder_point": st.column_config.NumberColumn("Reorder point"),
                "suggested_qty": st.column_config.NumberColumn("Order qty"),
            },
        )
        section("Product forecast")
        pick = st.selectbox("Product", reorder["product"].tolist())
        row = reorder[reorder["product"] == pick].iloc[0]
        series = row["series"]
        if series:
            start = pd.Timestamp(series["history_start"])
            hist_x = [start + timedelta(weeks=i) for i in range(len(series["history"]))]
            fut_x = [hist_x[-1] + timedelta(weeks=i + 1) for i in range(len(series["forecast"]))]
            fig = go.Figure()
            fig.add_bar(x=hist_x, y=series["history"], name="Units sold", marker_color=NAVY_3)
            fig.add_scatter(x=fut_x, y=series["forecast"], name="Forecast", mode="lines+markers",
                            line=dict(color=ORANGE, width=3, dash="dash"))
            fig.update_layout(height=360, title=f"Weekly demand · {pick} ({row['method'].replace('_', ' ')})",
                              legend=dict(orientation="h", y=1.1))
            st.plotly_chart(fig)

with tabs[3]:
    if invoices.empty:
        st.info("No open invoices have been scored.")
    else:
        band = invoices.groupby("risk_band").agg(invoices=("invoice", "count"), outstanding=("outstanding", "sum")) \
            .reindex(["HIGH", "MEDIUM", "LOW"]).fillna(0).reset_index()
        c1, c2 = st.columns([1, 1.6])
        with c1:
            fig = px.bar(band, x="risk_band", y="outstanding", color="risk_band", title="Outstanding by risk band",
                         color_discrete_map={"HIGH": RED, "MEDIUM": AMBER, "LOW": GREEN})
            fig.update_layout(height=340, showlegend=False, yaxis_tickprefix="₹", xaxis_title=None)
            st.plotly_chart(fig)
        with c2:
            st.metric("Expected late amount", compact_currency(float(invoices["expected_late_amount"].sum())))
            hint("Prioritise collection calls for HIGH-risk invoices before their due date; consider "
                 "shortening credit terms for customers with repeated HIGH scores.")
        st.dataframe(
            invoices.sort_values("expected_late_amount", ascending=False), hide_index=True, height=380,
            column_config={
                "due_date": st.column_config.DateColumn("Due", format="DD MMM YYYY"),
                "outstanding": st.column_config.NumberColumn(format="₹%.2f"),
                "late_probability": st.column_config.ProgressColumn("Late risk", format="percent", min_value=0, max_value=1),
                "expected_late_amount": st.column_config.NumberColumn("Expected late", format="₹%.0f"),
            },
        )

with tabs[4]:
    if quotes.empty:
        st.info("No open quotations have been scored.")
    else:
        st.dataframe(
            quotes.sort_values("expected_value", ascending=False), hide_index=True,
            column_config={
                "total": st.column_config.NumberColumn(format="₹%.2f"),
                "valid_until": st.column_config.DatetimeColumn(format="DD MMM YYYY"),
                "win_probability": st.column_config.ProgressColumn("Win probability", format="percent", min_value=0, max_value=1),
                "expected_value": st.column_config.NumberColumn("Expected value", format="₹%.0f"),
            },
        )
        hint("Follow up first on high-value quotes with 30–70% win probability; they gain most from attention.")

with tabs[5]:
    for run in data["health"]:
        metrics = run["metrics"]
        with st.container(border=True):
            st.markdown(f"**{MODEL_LABELS.get(run['model'], run['model'])}** · `{run['method']}` · "
                        f"{run['samples']:,} training rows · {run['trained_at']:%d %b %Y %H:%M} by {run['trained_by']}")
            simple = {k: v for k, v in metrics.items() if isinstance(v, (int, float)) and v is not None}
            if simple:
                cols = st.columns(min(len(simple), 5))
                for col, (key, value) in zip(cols, list(simple.items())[:5]):
                    shown = f"{value:.3f}" if isinstance(value, float) and abs(value) < 10 else f"{value:,.0f}"
                    col.metric(key.replace("_", " ").upper() if len(key) <= 5 else key.replace("_", " ").title(), shown)
            nested = metrics.get("importance") or metrics.get("coefficients")
            if nested:
                frame = pd.DataFrame({"feature": list(nested), "weight": list(nested.values())})
                fig = px.bar(frame, x="weight", y="feature", orientation="h", height=220,
                             title="Feature importance" if "importance" in metrics else "Coefficients (standardised)")
                fig.update_traces(marker_color=NAVY_3)
                fig.update_layout(yaxis_title=None, xaxis_title=None, margin=dict(t=40, b=10))
                st.plotly_chart(fig)
    hint("AUC: 0.5 = random, above 0.7 is useful. Forecast WAPE is measured on an 8-week holdout.")
