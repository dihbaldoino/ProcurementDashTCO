"""
Executive TCO & Should-Cost Procurement Dashboard
Online-ready Streamlit app

Run locally:
    pip install -r requirements.txt
    streamlit run app.py

Deploy online:
    - Streamlit Community Cloud: push app.py + requirements.txt to GitHub
    - Replit: create a Python Repl, upload these files, run streamlit run app.py
    - Hugging Face Spaces: create a Streamlit Space and upload these files
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except Exception:
    go = None
    PLOTLY_AVAILABLE = False


st.set_page_config(
    page_title="Executive TCO Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.3rem;
            padding-bottom: 2.2rem;
            max-width: 1450px;
        }
        .executive-hero {
            background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #2563eb 100%);
            padding: 30px 34px;
            border-radius: 26px;
            color: white;
            margin-bottom: 22px;
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.22);
        }
        .executive-hero h1 {
            font-size: 2.2rem;
            line-height: 1.1;
            margin-bottom: 0.35rem;
            font-weight: 800;
        }
        .executive-hero p {
            font-size: 1rem;
            color: rgba(255,255,255,0.88);
            margin-bottom: 0;
            max-width: 980px;
        }
        .section-title {
            font-size: 1.18rem;
            font-weight: 800;
            color: #0f172a;
            margin-top: 12px;
            margin-bottom: 5px;
        }
        .section-subtitle {
            font-size: 0.92rem;
            color: #64748b;
            margin-bottom: 14px;
        }
        .kpi-card {
            background: #ffffff;
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 22px;
            padding: 20px 20px;
            min-height: 145px;
            box-shadow: 0 10px 28px rgba(15, 23, 42, 0.07);
        }
        .kpi-label {
            color: #64748b;
            font-size: 0.80rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.055em;
            margin-bottom: 8px;
        }
        .kpi-value {
            color: #0f172a;
            font-size: 1.65rem;
            font-weight: 850;
            line-height: 1.1;
            margin-bottom: 9px;
        }
        .kpi-helper {
            color: #64748b;
            font-size: 0.84rem;
            line-height: 1.32;
        }
        .good { color: #047857 !important; }
        .bad { color: #b91c1c !important; }
        .neutral { color: #1d4ed8 !important; }
        .decision-card {
            border-radius: 24px;
            padding: 22px 26px;
            margin: 14px 0 20px 0;
            box-shadow: 0 12px 35px rgba(15, 23, 42, 0.08);
        }
        .decision-good {
            background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
            border: 1px solid #a7f3d0;
        }
        .decision-bad {
            background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
            border: 1px solid #fecaca;
        }
        .decision-title {
            font-size: 1.25rem;
            font-weight: 850;
            color: #0f172a;
            margin-bottom: 5px;
        }
        .decision-body {
            font-size: 0.98rem;
            color: #334155;
            line-height: 1.45;
        }
        .insight-box {
            background: white;
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-left: 5px solid #2563eb;
            border-radius: 18px;
            padding: 18px 20px;
            color: #334155;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
            min-height: 170px;
        }
        .small-note {
            font-size: 0.82rem;
            color: #64748b;
            margin-top: 8px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def safe_divide(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def format_money(value: float, currency: str = "USD", compact: bool = False) -> str:
    sign = "-" if value < 0 else ""
    value = abs(float(value))
    if compact:
        if value >= 1_000_000_000:
            return f"{sign}{currency} {value / 1_000_000_000:,.2f}B"
        if value >= 1_000_000:
            return f"{sign}{currency} {value / 1_000_000:,.2f}M"
        if value >= 1_000:
            return f"{sign}{currency} {value / 1_000:,.2f}K"
    return f"{sign}{currency} {value:,.2f}"


def format_percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def equivalent_rate(reference_rate_pct: float, reference_days: int, target_days: int, method: str) -> float:
    if reference_days <= 0:
        return 0.0
    if target_days < 0:
        target_days = 0
    reference_rate = reference_rate_pct / 100
    if method == "Linear simples":
        return reference_rate * (target_days / reference_days)
    return (1 + reference_rate) ** (target_days / reference_days) - 1


def render_kpi_card(label: str, value: str, helper: str, tone: str = "neutral") -> None:
    tone_class = {"good": "good", "bad": "bad", "neutral": "neutral"}.get(tone, "neutral")
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value {tone_class}">{value}</div>
            <div class="kpi-helper">{helper}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def calculate_metrics(
    brazil_spend: float,
    mexico_spend: float,
    argentina_spend: float,
    colombia_spend: float,
    proposal_brazil: float,
    proposal_latam: float,
    reference_rate_pct: float,
    reference_days: int,
    proposal_payment_days: int,
    method: str,
    finance_mode: str,
) -> dict:
    latam_spend = mexico_spend + argentina_spend + colombia_spend
    current_total = brazil_spend + latam_spend
    proposal_before_finance = proposal_brazil + proposal_latam
    rate = equivalent_rate(reference_rate_pct, reference_days, proposal_payment_days, method)

    add_finance = finance_mode == "Adicionar custo financeiro na proposta"
    finance_brazil = proposal_brazil * rate if add_finance else 0.0
    finance_latam = proposal_latam * rate if add_finance else 0.0
    finance_total = finance_brazil + finance_latam

    proposal_adjusted_brazil = proposal_brazil + finance_brazil
    proposal_adjusted_latam = proposal_latam + finance_latam
    proposal_adjusted_total = proposal_before_finance + finance_total

    nominal_delta = current_total - proposal_before_finance
    saving = current_total - proposal_adjusted_total
    saving_pct = safe_divide(saving, current_total)

    if add_finance and rate > -1:
        break_even_before_finance = current_total / (1 + rate)
    else:
        break_even_before_finance = current_total

    return {
        "brazil_spend": brazil_spend,
        "mexico_spend": mexico_spend,
        "argentina_spend": argentina_spend,
        "colombia_spend": colombia_spend,
        "latam_spend": latam_spend,
        "current_total": current_total,
        "proposal_brazil": proposal_brazil,
        "proposal_latam": proposal_latam,
        "proposal_before_finance": proposal_before_finance,
        "equivalent_rate": rate,
        "finance_brazil": finance_brazil,
        "finance_latam": finance_latam,
        "finance_total": finance_total,
        "proposal_adjusted_brazil": proposal_adjusted_brazil,
        "proposal_adjusted_latam": proposal_adjusted_latam,
        "proposal_adjusted_total": proposal_adjusted_total,
        "nominal_delta": nominal_delta,
        "saving": saving,
        "saving_pct": saving_pct,
        "break_even_before_finance": break_even_before_finance,
        "gap_to_break_even": break_even_before_finance - proposal_before_finance,
    }


def build_region_table(metrics: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Region": "Brazil",
                "Current Spend": metrics["brazil_spend"],
                "Proposal Before Finance": metrics["proposal_brazil"],
                "Financial Cost": metrics["finance_brazil"],
                "Proposal Adjusted": metrics["proposal_adjusted_brazil"],
                "Saving / Impact": metrics["brazil_spend"] - metrics["proposal_adjusted_brazil"],
                "Saving / Impact %": safe_divide(
                    metrics["brazil_spend"] - metrics["proposal_adjusted_brazil"], metrics["brazil_spend"]
                ),
            },
            {
                "Region": "LATAM",
                "Current Spend": metrics["latam_spend"],
                "Proposal Before Finance": metrics["proposal_latam"],
                "Financial Cost": metrics["finance_latam"],
                "Proposal Adjusted": metrics["proposal_adjusted_latam"],
                "Saving / Impact": metrics["latam_spend"] - metrics["proposal_adjusted_latam"],
                "Saving / Impact %": safe_divide(
                    metrics["latam_spend"] - metrics["proposal_adjusted_latam"], metrics["latam_spend"]
                ),
            },
            {
                "Region": "Total",
                "Current Spend": metrics["current_total"],
                "Proposal Before Finance": metrics["proposal_before_finance"],
                "Financial Cost": metrics["finance_total"],
                "Proposal Adjusted": metrics["proposal_adjusted_total"],
                "Saving / Impact": metrics["saving"],
                "Saving / Impact %": metrics["saving_pct"],
            },
        ]
    )


def build_sensitivity_table(metrics: dict, variation_range_pct: int, finance_mode: str) -> pd.DataFrame:
    variations = [x / 100 for x in range(-variation_range_pct, variation_range_pct + 1, 2)]
    add_finance = finance_mode == "Adicionar custo financeiro na proposta"
    rows = []
    for variation in variations:
        simulated_before_finance = metrics["proposal_before_finance"] * (1 + variation)
        simulated_finance = simulated_before_finance * metrics["equivalent_rate"] if add_finance else 0.0
        simulated_adjusted = simulated_before_finance + simulated_finance
        saving = metrics["current_total"] - simulated_adjusted
        rows.append(
            {
                "Proposal Variation %": variation * 100,
                "Simulated Proposal Adjusted": simulated_adjusted,
                "Saving / Impact": saving,
                "Saving / Impact %": safe_divide(saving, metrics["current_total"]),
            }
        )
    return pd.DataFrame(rows)


def plot_spend_bridge(metrics: dict, currency: str) -> None:
    bridge_df = pd.DataFrame(
        {
            "Step": ["Current", "Proposal before finance", "Financial cost", "Adjusted proposal"],
            "Value": [
                metrics["current_total"],
                metrics["proposal_before_finance"],
                metrics["finance_total"],
                metrics["proposal_adjusted_total"],
            ],
        }
    )
    if PLOTLY_AVAILABLE:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=bridge_df["Step"],
                y=bridge_df["Value"],
                text=[format_money(v, currency, compact=True) for v in bridge_df["Value"]],
                textposition="outside",
                marker_color=["#64748b", "#2563eb", "#f97316", "#0f766e"],
                hovertemplate="%{x}<br>" + currency + " %{y:,.2f}<extra></extra>",
            )
        )
        fig.update_layout(
            title="Spend Bridge",
            height=420,
            margin=dict(l=20, r=20, t=55, b=30),
            yaxis_title=f"Spend ({currency})",
            plot_bgcolor="white",
            paper_bgcolor="white",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.bar_chart(bridge_df.set_index("Step"))


def plot_region_comparison(region_df: pd.DataFrame, currency: str) -> None:
    chart_df = region_df[region_df["Region"].isin(["Brazil", "LATAM"])].copy()
    if PLOTLY_AVAILABLE:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=chart_df["Region"],
                y=chart_df["Current Spend"],
                name="Current Spend",
                marker_color="#94a3b8",
                hovertemplate="Current<br>" + currency + " %{y:,.2f}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Bar(
                x=chart_df["Region"],
                y=chart_df["Proposal Adjusted"],
                name="Proposal Adjusted",
                marker_color="#2563eb",
                hovertemplate="Proposal adjusted<br>" + currency + " %{y:,.2f}<extra></extra>",
            )
        )
        fig.update_layout(
            title="Brazil vs LATAM",
            barmode="group",
            height=420,
            margin=dict(l=20, r=20, t=55, b=30),
            yaxis_title=f"Spend ({currency})",
            plot_bgcolor="white",
            paper_bgcolor="white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.bar_chart(chart_df.set_index("Region")[["Current Spend", "Proposal Adjusted"]])


def plot_sensitivity(sensitivity_df: pd.DataFrame, currency: str) -> None:
    if PLOTLY_AVAILABLE:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=sensitivity_df["Proposal Variation %"],
                y=sensitivity_df["Saving / Impact"],
                mode="lines+markers",
                line=dict(color="#2563eb", width=3),
                marker=dict(color="#1d4ed8", size=7),
                hovertemplate="Variation: %{x:.0f}%<br>Saving/Impact: " + currency + " %{y:,.2f}<extra></extra>",
            )
        )
        fig.add_hline(y=0, line_dash="dash", line_color="#ef4444")
        fig.update_layout(
            title="Sensitivity: proposal spend variation",
            height=420,
            margin=dict(l=20, r=20, t=55, b=30),
            xaxis_title="Proposal variation (%)",
            yaxis_title=f"Saving / Impact ({currency})",
            plot_bgcolor="white",
            paper_bgcolor="white",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.line_chart(sensitivity_df.set_index("Proposal Variation %")[["Saving / Impact"]])


def plot_current_mix(metrics: dict, currency: str) -> None:
    mix_df = pd.DataFrame(
        {
            "Region": ["Brazil", "LATAM"],
            "Current Spend": [metrics["brazil_spend"], metrics["latam_spend"]],
        }
    )
    if PLOTLY_AVAILABLE:
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=mix_df["Region"],
                    values=mix_df["Current Spend"],
                    hole=0.55,
                    marker=dict(colors=["#2563eb", "#14b8a6"]),
                    textinfo="label+percent",
                    hovertemplate="%{label}<br>" + currency + " %{value:,.2f}<extra></extra>",
                )
            ]
        )
        fig.update_layout(
            title="Current spend mix",
            height=420,
            margin=dict(l=20, r=20, t=55, b=30),
            plot_bgcolor="white",
            paper_bgcolor="white",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.bar_chart(mix_df.set_index("Region"))


with st.sidebar:
    st.markdown("## Executive Inputs")
    st.caption("Use one single currency for every spend input.")
    currency_symbol = st.text_input("Currency", value="USD")
    st.markdown("---")
    st.markdown("### Financial method")
    calculation_method = st.radio(
        "Equivalent rate calculation",
        options=["Composta equivalente", "Linear simples"],
        index=0,
    )
    financing_treatment = st.radio(
        "Financial cost treatment",
        options=["Adicionar custo financeiro na proposta", "Proposta já inclui custo financeiro"],
        index=0,
    )
    st.markdown("---")
    st.markdown("### Sensitivity")
    sensitivity_range_pct = st.slider(
        "Proposal variation range (%)",
        min_value=5,
        max_value=40,
        value=20,
        step=5,
    )

st.markdown(
    """
    <div class="executive-hero">
        <h1>Executive TCO & Should-Cost Dashboard</h1>
        <p>
            Compare current spend versus proposal spend, isolate payment-term financial impact,
            consolidate Mexico + Argentina + Colombia as LATAM, and quantify final saving or cost impact.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

input_tab_1, input_tab_2, input_tab_3 = st.tabs(
    ["1. Current Spend", "2. Financial Assumption", "3. Proposal"]
)

with input_tab_1:
    st.markdown('<div class="section-title">Current Spend by Locality</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Mexico, Argentina and Colombia are automatically consolidated as LATAM.</div>',
        unsafe_allow_html=True,
    )
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        brazil_spend = st.number_input("Brazil current spend", min_value=0.0, value=10_000_000.0, step=100_000.0, format="%.2f")
    with col2:
        mexico_spend = st.number_input("Mexico current spend", min_value=0.0, value=6_000_000.0, step=100_000.0, format="%.2f")
    with col3:
        argentina_spend = st.number_input("Argentina current spend", min_value=0.0, value=4_000_000.0, step=100_000.0, format="%.2f")
    with col4:
        colombia_spend = st.number_input("Colombia current spend", min_value=0.0, value=3_000_000.0, step=100_000.0, format="%.2f")

with input_tab_2:
    st.markdown('<div class="section-title">Financial Reference Rate</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Example: 7.35% for 180 days converted into the proposed payment term.</div>',
        unsafe_allow_html=True,
    )
    col5, col6, col7 = st.columns(3)
    with col5:
        reference_rate_pct = st.number_input("Reference financial rate (%)", min_value=0.0, value=7.35, step=0.05, format="%.4f")
    with col6:
        reference_days = st.number_input("Reference term days", min_value=1, value=180, step=1)
    with col7:
        proposal_payment_days = st.number_input("Proposal payment term days", min_value=0, value=120, step=1)

with input_tab_3:
    st.markdown('<div class="section-title">Proposal Spend</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Enter proposal spend before financial adjustment.</div>',
        unsafe_allow_html=True,
    )
    current_latam_preview = mexico_spend + argentina_spend + colombia_spend
    current_total_preview = brazil_spend + current_latam_preview
    proposal_input_mode = st.radio(
        "Proposal input mode",
        options=["Brazil + LATAM", "Consolidated total proposal"],
        horizontal=True,
    )
    if proposal_input_mode == "Brazil + LATAM":
        col8, col9 = st.columns(2)
        with col8:
            proposal_brazil = st.number_input("Brazil proposal spend", min_value=0.0, value=9_600_000.0, step=100_000.0, format="%.2f")
        with col9:
            proposal_latam = st.number_input("LATAM proposal spend", min_value=0.0, value=12_000_000.0, step=100_000.0, format="%.2f")
    else:
        consolidated_proposal = st.number_input("Consolidated proposal spend", min_value=0.0, value=21_600_000.0, step=100_000.0, format="%.2f")
        brazil_mix = safe_divide(brazil_spend, current_total_preview)
        latam_mix = safe_divide(current_latam_preview, current_total_preview)
        proposal_brazil = consolidated_proposal * brazil_mix
        proposal_latam = consolidated_proposal * latam_mix
        st.caption("The consolidated proposal is split by the current Brazil/LATAM spend mix.")

metrics = calculate_metrics(
    brazil_spend=brazil_spend,
    mexico_spend=mexico_spend,
    argentina_spend=argentina_spend,
    colombia_spend=colombia_spend,
    proposal_brazil=proposal_brazil,
    proposal_latam=proposal_latam,
    reference_rate_pct=reference_rate_pct,
    reference_days=reference_days,
    proposal_payment_days=proposal_payment_days,
    method=calculation_method,
    finance_mode=financing_treatment,
)

region_df = build_region_table(metrics)
sensitivity_df = build_sensitivity_table(metrics, sensitivity_range_pct, financing_treatment)

is_saving = metrics["saving"] >= 0
result_label = "Saving" if is_saving else "Impact"
result_tone = "good" if is_saving else "bad"

st.markdown('<div class="section-title">Executive Result</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-subtitle">Decision-ready view: spend, financial impact and final saving/impact.</div>',
    unsafe_allow_html=True,
)

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
with kpi1:
    render_kpi_card("Current Spend", format_money(metrics["current_total"], currency_symbol, compact=True), "Brazil + consolidated LATAM", "neutral")
with kpi2:
    render_kpi_card("Proposal Adjusted", format_money(metrics["proposal_adjusted_total"], currency_symbol, compact=True), "Proposal plus financial adjustment", "neutral")
with kpi3:
    render_kpi_card(result_label, format_money(abs(metrics["saving"]), currency_symbol, compact=True), f"{format_percent(abs(metrics['saving_pct']))} versus current spend", result_tone)
with kpi4:
    render_kpi_card("Equivalent Rate", format_percent(metrics["equivalent_rate"]), f"{reference_rate_pct:.2f}% / {reference_days}dd to {proposal_payment_days}dd", "neutral")
with kpi5:
    render_kpi_card("Financial Cost", format_money(metrics["finance_total"], currency_symbol, compact=True), "Payment-term cost applied to proposal", "neutral")

if is_saving:
    st.markdown(
        f"""
        <div class="decision-card decision-good">
            <div class="decision-title">Proposal is financially attractive under the current assumptions</div>
            <div class="decision-body">
                The adjusted proposal generates an estimated saving of
                <b>{format_money(metrics['saving'], currency_symbol)}</b>, equivalent to
                <b>{format_percent(metrics['saving_pct'])}</b> versus the current spend.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"""
        <div class="decision-card decision-bad">
            <div class="decision-title">Proposal creates a cost impact under the current assumptions</div>
            <div class="decision-body">
                The adjusted proposal is above current spend by
                <b>{format_money(abs(metrics['saving']), currency_symbol)}</b>, equivalent to
                <b>{format_percent(abs(metrics['saving_pct']))}</b>. A lower price, better payment term,
                or lower financial charge is required to reach break-even.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

chart_col1, chart_col2 = st.columns([1.35, 1])
with chart_col1:
    plot_spend_bridge(metrics, currency_symbol)
with chart_col2:
    plot_current_mix(metrics, currency_symbol)

chart_col3, chart_col4 = st.columns([1, 1.25])
with chart_col3:
    plot_region_comparison(region_df, currency_symbol)
with chart_col4:
    plot_sensitivity(sensitivity_df, currency_symbol)

st.markdown('<div class="section-title">Detailed Breakdown</div>', unsafe_allow_html=True)
display_region_df = region_df.copy()
for money_col in ["Current Spend", "Proposal Before Finance", "Financial Cost", "Proposal Adjusted", "Saving / Impact"]:
    display_region_df[money_col] = display_region_df[money_col].apply(lambda x: format_money(x, currency_symbol))
display_region_df["Saving / Impact %"] = display_region_df["Saving / Impact %"].apply(format_percent)
st.dataframe(display_region_df, use_container_width=True)

st.markdown('<div class="section-title">Procurement Interpretation</div>', unsafe_allow_html=True)
insight_col1, insight_col2 = st.columns(2)
with insight_col1:
    st.markdown(
        f"""
        <div class="insight-box">
            <b>Financial assumption</b><br><br>
            Reference rate: <b>{reference_rate_pct:.2f}% for {reference_days} days</b><br>
            Proposal payment term: <b>{proposal_payment_days} days</b><br>
            Equivalent rate: <b>{format_percent(metrics['equivalent_rate'])}</b><br>
            Method: <b>{calculation_method}</b><br>
            Treatment: <b>{financing_treatment}</b>
        </div>
        """,
        unsafe_allow_html=True,
    )
with insight_col2:
    st.markdown(
        f"""
        <div class="insight-box">
            <b>Break-even reading</b><br><br>
            To break even after the financial adjustment, proposal spend before finance should be at or below
            <b>{format_money(metrics['break_even_before_finance'], currency_symbol)}</b>.<br><br>
            Current gap to break-even:
            <b>{format_money(metrics['gap_to_break_even'], currency_symbol)}</b>.
        </div>
        """,
        unsafe_allow_html=True,
    )

with st.expander("Show sensitivity data"):
    display_sensitivity_df = sensitivity_df.copy()
    display_sensitivity_df["Proposal Variation %"] = display_sensitivity_df["Proposal Variation %"].map(lambda x: f"{x:.0f}%")
    display_sensitivity_df["Simulated Proposal Adjusted"] = display_sensitivity_df["Simulated Proposal Adjusted"].apply(lambda x: format_money(x, currency_symbol))
    display_sensitivity_df["Saving / Impact"] = display_sensitivity_df["Saving / Impact"].apply(lambda x: format_money(x, currency_symbol))
    display_sensitivity_df["Saving / Impact %"] = display_sensitivity_df["Saving / Impact %"].apply(format_percent)
    st.dataframe(display_sensitivity_df, use_container_width=True)

export_df = region_df.copy()
export_df["Equivalent Rate"] = metrics["equivalent_rate"]
export_df["Reference Rate %"] = reference_rate_pct
export_df["Reference Days"] = reference_days
export_df["Proposal Payment Days"] = proposal_payment_days
export_df["Calculation Method"] = calculation_method
export_df["Financing Treatment"] = financing_treatment

csv_data = export_df.to_csv(index=False).encode("utf-8")
st.download_button(
    label="Download executive breakdown as CSV",
    data=csv_data,
    file_name="executive_tco_procurement_breakdown.csv",
    mime="text/csv",
)

st.markdown(
    """
    <div class="small-note">
        Note: this model is based on user-entered assumptions. Final sourcing decisions should also consider supply risk,
        quality, capacity, logistics constraints, taxes, compliance and business continuity.
    </div>
    """,
    unsafe_allow_html=True,
)
