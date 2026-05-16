"""
Executive Procurement TCO & Should-Cost Dashboard
Version: v9 - Validation Defaults + Apples-to-Apples Cost Delta Logic

Run locally:
    pip install -r requirements.txt
    streamlit run app.py

Online deployment:
    Deploy this folder to Streamlit Community Cloud, Replit, Render or Hugging Face Spaces.
"""

from __future__ import annotations

from itertools import product
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except Exception:
    go = None
    PLOTLY_AVAILABLE = False


# =============================================================================
# Page setup
# =============================================================================

st.set_page_config(
    page_title="Executive Procurement TCO Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================================================================
# Constants
# =============================================================================

COUNTRIES = ["Brazil", "Mexico", "Argentina", "Colombia"]
LATAM_COUNTRIES = ["Mexico", "Argentina", "Colombia"]
SUPPLIERS = [
    "ChemPrime",
    "OleoGlobal",
    "Oleo Overseas Trading Co.",
    "Comercio de Oleos Nacional Distribuicao",
]
DEFAULT_RISK = {
    "ChemPrime": 2.0,
    "OleoGlobal": 3.0,
    "Oleo Overseas Trading Co.": 4.0,
    "Comercio de Oleos Nacional Distribuicao": 3.0,
}

# Dark graphite used in all Plotly chart text for better readability on white background.
GRAPHITE = "#1f2937"


def apply_graphite_chart_theme(fig):
    """Apply a consistent dark graphite text theme to Plotly charts."""
    if fig is None:
        return fig

    fig.update_layout(
        font=dict(color=GRAPHITE),
        title_font=dict(color=GRAPHITE),
        xaxis=dict(
            title_font=dict(color=GRAPHITE),
            tickfont=dict(color=GRAPHITE),
            color=GRAPHITE,
            gridcolor="rgba(31, 41, 55, 0.12)",
            zerolinecolor="rgba(31, 41, 55, 0.35)",
        ),
        yaxis=dict(
            title_font=dict(color=GRAPHITE),
            tickfont=dict(color=GRAPHITE),
            color=GRAPHITE,
            gridcolor="rgba(31, 41, 55, 0.12)",
            zerolinecolor="rgba(31, 41, 55, 0.35)",
        ),
        legend=dict(font=dict(color=GRAPHITE)),
        uniformtext=dict(minsize=11, mode="show"),
    )

    # Trace-level text is not fully covered by layout font in every Plotly version.
    for trace in fig.data:
        if hasattr(trace, "textfont"):
            trace.textfont = dict(color=GRAPHITE)
        if hasattr(trace, "insidetextfont"):
            trace.insidetextfont = dict(color=GRAPHITE)
        if hasattr(trace, "outsidetextfont"):
            trace.outsidetextfont = dict(color=GRAPHITE)

    return fig


# =============================================================================
# Styling
# =============================================================================

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 2.2rem;
            max-width: 1550px;
        }
        .executive-hero {
            background: linear-gradient(135deg, #020617 0%, #0f172a 45%, #1d4ed8 100%);
            padding: 30px 34px;
            border-radius: 28px;
            color: white;
            margin-bottom: 22px;
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.25);
        }
        .executive-hero h1 {
            font-size: 2.25rem;
            line-height: 1.1;
            margin-bottom: 0.35rem;
            font-weight: 850;
            color: #ffffff;
        }
        .executive-hero p {
            font-size: 1rem;
            color: rgba(255,255,255,0.88);
            margin-bottom: 0;
            max-width: 1050px;
        }
        .section-header {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 18px;
            padding: 14px 18px;
            margin-top: 10px;
            margin-bottom: 14px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
        }
        .section-title {
            font-size: 1.12rem;
            font-weight: 850;
            color: #bfdbfe;
            margin-bottom: 3px;
        }
        .section-subtitle {
            font-size: 0.90rem;
            color: #e2e8f0;
            margin-bottom: 0;
        }
        .kpi-card {
            background: #ffffff;
            border: 1px solid rgba(148, 163, 184, 0.26);
            border-radius: 22px;
            padding: 20px 22px;
            min-height: 138px;
            margin-bottom: 22px;
            box-shadow: 0 10px 28px rgba(15, 23, 42, 0.07);
        }
        .kpi-card.compact-card {
            min-height: 124px;
        }
        .executive-row-spacer {
            height: 14px;
        }
        .decision-card {
            clear: both;
        }
        .kpi-label {
            color: #64748b;
            font-size: 0.78rem;
            font-weight: 850;
            text-transform: uppercase;
            letter-spacing: 0.055em;
            margin-bottom: 8px;
        }
        .kpi-value {
            color: #0f172a;
            font-size: 1.56rem;
            font-weight: 850;
            line-height: 1.1;
            margin-bottom: 9px;
        }
        .kpi-helper {
            color: #64748b;
            font-size: 0.83rem;
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
            min-height: 160px;
        }
        .small-note {
            font-size: 0.82rem;
            color: #64748b;
            margin-top: 8px;
        }
        div[data-testid="stSidebar"] {
            background: #020617;
        }
        div[data-testid="stSidebar"] label,
        div[data-testid="stSidebar"] p,
        div[data-testid="stSidebar"] span,
        div[data-testid="stSidebar"] h1,
        div[data-testid="stSidebar"] h2,
        div[data-testid="stSidebar"] h3 {
            color: #e5e7eb !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# Utility helpers
# =============================================================================


def render_section_header(title: str, subtitle: str = "") -> None:
    st.markdown(
        f"""
        <div class="section-header">
            <div class="section-title">{title}</div>
            <div class="section-subtitle">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_card(label: str, value: str, helper: str, tone: str = "neutral", compact: bool = False) -> None:
    tone_class = {"good": "good", "bad": "bad", "neutral": "neutral"}.get(tone, "neutral")
    compact_class = " compact-card" if compact else ""
    st.markdown(
        f"""
        <div class="kpi-card{compact_class}">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value {tone_class}">{value}</div>
            <div class="kpi-helper">{helper}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def safe_divide(numerator: float, denominator: float) -> float:
    return 0.0 if abs(denominator) < 1e-12 else numerator / denominator


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


def format_delta(value: float, currency: str = "USD", compact: bool = False) -> str:
    """Format cost delta: negative is saving, positive is impact."""
    value = float(value)
    if abs(value) < 1e-9:
        return format_money(0.0, currency, compact)
    sign = "+" if value > 0 else "-"
    abs_value = abs(value)
    if compact:
        if abs_value >= 1_000_000_000:
            return f"{sign}{currency} {abs_value / 1_000_000_000:,.2f}B"
        if abs_value >= 1_000_000:
            return f"{sign}{currency} {abs_value / 1_000_000:,.2f}M"
        if abs_value >= 1_000:
            return f"{sign}{currency} {abs_value / 1_000:,.2f}K"
    return f"{sign}{currency} {abs_value:,.2f}"


def delta_tone(value: float) -> str:
    """Green for saving/cost reduction, red for cost increase."""
    return "good" if value <= 0 else "bad"


def delta_label(value: float) -> str:
    return "Saving" if value <= 0 else "Impact"


def format_percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def equivalent_rate(reference_rate_pct: float, reference_days: int, target_days: int, method: str) -> float:
    if reference_days <= 0:
        return 0.0
    reference_rate = reference_rate_pct / 100.0
    target_days = max(0, target_days)
    if method == "Linear simple":
        return reference_rate * (target_days / reference_days)
    return (1 + reference_rate) ** (target_days / reference_days) - 1


def normalize_with_minimums(raw_shares: Dict[str, float], minimums: Dict[str, float]) -> Dict[str, float]:
    """
    Normalize supplier shares so the final allocation always sums to 100%.

    Logic:
    - Supplier minimums are respected first.
    - Remaining share is distributed proportionally according to the raw desired shares
      above each minimum requirement.
    - If raw desired shares are all zero after minimums, remaining share is distributed equally.
    """
    total_min = sum(max(0.0, minimums.get(supplier, 0.0)) for supplier in SUPPLIERS)
    if total_min > 100.0:
        # Return minimums scaled down as a safety fallback, but the UI will also warn the user.
        return {supplier: 100.0 * max(0.0, minimums.get(supplier, 0.0)) / total_min for supplier in SUPPLIERS}

    remaining = 100.0 - total_min
    weights = {}
    for supplier in SUPPLIERS:
        raw = max(0.0, raw_shares.get(supplier, 0.0))
        minimum = max(0.0, minimums.get(supplier, 0.0))
        weights[supplier] = max(0.0, raw - minimum)

    total_weight = sum(weights.values())
    if total_weight <= 1e-9:
        non_min_suppliers = [s for s in SUPPLIERS if minimums.get(s, 0.0) < 100.0]
        if not non_min_suppliers:
            non_min_suppliers = SUPPLIERS
        weights = {s: 1.0 if s in non_min_suppliers else 0.0 for s in SUPPLIERS}
        total_weight = sum(weights.values())

    effective = {}
    for supplier in SUPPLIERS:
        minimum = max(0.0, minimums.get(supplier, 0.0))
        effective[supplier] = minimum + remaining * weights.get(supplier, 0.0) / total_weight

    # Numerical correction to sum exactly 100.
    correction = 100.0 - sum(effective.values())
    if abs(correction) > 1e-8:
        largest_supplier = max(effective, key=effective.get)
        effective[largest_supplier] += correction

    return effective


def initialize_share_projection_state() -> None:
    """Initialize supplier share sliders once per session."""
    for country in COUNTRIES:
        for supplier in SUPPLIERS:
            share_key = f"share_{country}_{supplier}"
            if share_key not in st.session_state:
                st.session_state[share_key] = 100.0 if supplier == "ChemPrime" else 0.0


def auto_adjust_supplier_share(country: str, changed_supplier: str) -> None:
    """
    Automatic Share Projection behavior.

    When one supplier's share is changed, the remaining suppliers are adjusted
    proportionally so that the visible slider values continue to sum to 100%.
    This is only active when the user selects Automatic mode.
    """
    if st.session_state.get("share_projection_mode", "Automatic") != "Automatic":
        return

    changed_key = f"share_{country}_{changed_supplier}"
    changed_value = float(st.session_state.get(changed_key, 0.0))
    changed_value = round(min(100.0, max(0.0, changed_value)), 1)
    st.session_state[changed_key] = changed_value

    other_suppliers = [supplier for supplier in SUPPLIERS if supplier != changed_supplier]
    remaining_share = max(0.0, 100.0 - changed_value)

    other_values = {
        supplier: float(st.session_state.get(f"share_{country}_{supplier}", 0.0))
        for supplier in other_suppliers
    }
    other_total = sum(max(0.0, value) for value in other_values.values())

    if other_total <= 1e-9:
        equal_share = remaining_share / len(other_suppliers) if other_suppliers else 0.0
        for supplier in other_suppliers:
            st.session_state[f"share_{country}_{supplier}"] = round(equal_share, 1)
    else:
        for supplier in other_suppliers:
            proportional_share = remaining_share * max(0.0, other_values[supplier]) / other_total
            st.session_state[f"share_{country}_{supplier}"] = round(proportional_share, 1)

    # Final numerical correction.
    total = sum(float(st.session_state.get(f"share_{country}_{supplier}", 0.0)) for supplier in SUPPLIERS)
    correction = 100.0 - total
    if abs(correction) > 1e-8:
        # Apply correction to the largest non-changed supplier when possible.
        correction_candidates = other_suppliers or [changed_supplier]
        target_supplier = max(correction_candidates, key=lambda supplier: st.session_state.get(f"share_{country}_{supplier}", 0.0))
        target_key = f"share_{country}_{target_supplier}"
        st.session_state[target_key] = min(100.0, max(0.0, float(st.session_state.get(target_key, 0.0)) + correction))


def get_slider_share_values(country: str) -> Dict[str, float]:
    """Read current supplier share slider values for one country."""
    return {
        supplier: float(st.session_state.get(f"share_{country}_{supplier}", 0.0))
        for supplier in SUPPLIERS
    }



# =============================================================================
# Calculation engine
# =============================================================================



def compute_country_baseline(
    country: str,
    current_spend: float,
    financial_assumptions: Dict[str, Dict[str, float]],
    method: str,
) -> Dict[str, float]:
    """
    Build an apples-to-apples current baseline.

    Current spend is treated as base spend, not as an already-financed number.
    Therefore, the baseline also receives the same payment-term logic used for proposals:

    Current adjusted baseline = current base spend
                              + current gross supplier financing cost
                              - current invested-cash capital gain offset
    """
    current_payment_days = int(financial_assumptions[country]["current_payment_days"])

    financing_rate_pct = financial_assumptions[country]["financing_rate_pct"]
    financing_days = int(financial_assumptions[country]["financing_days"])
    current_financing_rate = equivalent_rate(financing_rate_pct, financing_days, current_payment_days, method)

    return_rate_pct = financial_assumptions[country]["investment_return_rate_pct"]
    return_days = int(financial_assumptions[country]["investment_return_days"])
    current_return_rate = equivalent_rate(return_rate_pct, return_days, current_payment_days, method)

    current_gross_financial_cost = current_spend * current_financing_rate
    current_capital_gain_offset = current_spend * current_return_rate
    current_net_financial_impact = current_gross_financial_cost - current_capital_gain_offset
    current_adjusted_baseline = current_spend + current_net_financial_impact

    return {
        "current_payment_days": current_payment_days,
        "current_financing_rate": current_financing_rate,
        "current_return_rate": current_return_rate,
        "current_gross_financial_cost": current_gross_financial_cost,
        "current_capital_gain_offset": current_capital_gain_offset,
        "current_net_financial_impact": current_net_financial_impact,
        "current_adjusted_baseline": current_adjusted_baseline,
    }


def compute_country_proposal(
    country: str,
    current_spend: float,
    financial_assumptions: Dict[str, Dict[str, float]],
    supplier_inputs: Dict[str, Dict[str, Dict[str, float]]],
    effective_shares: Dict[str, Dict[str, float]],
    method: str,
) -> Dict[str, object]:
    """
    Computes country-level TCO on an apples-to-apples basis.

    Baseline and proposal are both adjusted with the same logic:
    - gross supplier financing cost increases cost according to payment term;
    - invested-cash return offsets this cost because retained cash works during the term;
    - adjusted cost = base spend + gross financing cost - capital gain offset.

    Cost delta = adjusted proposal - current adjusted baseline.
    Negative delta = saving / cost reduction / green.
    Positive delta = impact / cost increase / red.
    """
    baseline = compute_country_baseline(country, current_spend, financial_assumptions, method)

    rows = []
    adjusted_total = 0.0
    proposal_before_finance_total = 0.0
    gross_financial_cost_total = 0.0
    capital_gain_offset_total = 0.0
    net_financial_impact_total = 0.0
    risk_weighted_sum = 0.0

    for supplier in SUPPLIERS:
        supplier_data = supplier_inputs[country][supplier]
        spend = supplier_data["spend"]
        payment_days = int(supplier_data["payment_days"])
        risk_score = supplier_data["risk_score"]
        share_pct = effective_shares[country][supplier]
        share = share_pct / 100.0

        country_financing_rate = financial_assumptions[country]["financing_rate_pct"]
        country_financing_days = int(financial_assumptions[country]["financing_days"])
        supplier_financing_rate = equivalent_rate(country_financing_rate, country_financing_days, payment_days, method)

        country_return_rate = financial_assumptions[country]["investment_return_rate_pct"]
        country_return_days = int(financial_assumptions[country]["investment_return_days"])
        investment_return_rate = equivalent_rate(country_return_rate, country_return_days, payment_days, method)

        allocated_before_finance = spend * share
        gross_financial_cost = allocated_before_finance * supplier_financing_rate
        capital_gain_offset = allocated_before_finance * investment_return_rate
        net_financial_impact = gross_financial_cost - capital_gain_offset
        adjusted_spend = allocated_before_finance + net_financial_impact

        proposal_before_finance_total += allocated_before_finance
        gross_financial_cost_total += gross_financial_cost
        capital_gain_offset_total += capital_gain_offset
        net_financial_impact_total += net_financial_impact
        adjusted_total += adjusted_spend
        risk_weighted_sum += risk_score * max(adjusted_spend, 0.0)

        rows.append(
            {
                "Country": country,
                "Supplier": supplier,
                "Effective Share %": share_pct,
                "Proposal Spend": spend,
                "Payment Term Days": payment_days,
                "Supplier Financing Rate": supplier_financing_rate,
                "Investment Return Rate": investment_return_rate,
                "Allocated Spend Before Finance": allocated_before_finance,
                "Gross Financial Cost": gross_financial_cost,
                "Capital Gain Offset": capital_gain_offset,
                "Net Financial Impact": net_financial_impact,
                "Adjusted Proposal Spend": adjusted_spend,
                "Risk Score": risk_score,
                "Kraljic Minimum Required": supplier_data["kraljic_required"],
                "Minimum Share %": supplier_data["minimum_share"],
            }
        )

    cost_delta = adjusted_total - baseline["current_adjusted_baseline"]
    net_financial_delta = net_financial_impact_total - baseline["current_net_financial_impact"]

    return {
        "country": country,
        "current_base_spend": current_spend,
        "current_payment_days": baseline["current_payment_days"],
        "current_gross_financial_cost": baseline["current_gross_financial_cost"],
        "current_capital_gain_offset": baseline["current_capital_gain_offset"],
        "current_net_financial_impact": baseline["current_net_financial_impact"],
        "current_adjusted_baseline": baseline["current_adjusted_baseline"],
        "proposal_before_finance": proposal_before_finance_total,
        "gross_financial_cost": gross_financial_cost_total,
        "capital_gain_offset": capital_gain_offset_total,
        "net_financial_impact": net_financial_impact_total,
        "net_financial_delta": net_financial_delta,
        "adjusted_proposal": adjusted_total,
        "cost_delta": cost_delta,
        "cost_delta_pct": safe_divide(cost_delta, baseline["current_adjusted_baseline"]),
        "risk_score": safe_divide(risk_weighted_sum, adjusted_total) if adjusted_total else 0.0,
        "rows": rows,
    }


def compute_full_scenario(
    current_spend: Dict[str, float],
    financial_assumptions: Dict[str, Dict[str, float]],
    supplier_inputs: Dict[str, Dict[str, Dict[str, float]]],
    effective_shares: Dict[str, Dict[str, float]],
    method: str,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    country_results = []
    detail_rows = []

    for country in COUNTRIES:
        result = compute_country_proposal(
            country=country,
            current_spend=current_spend[country],
            financial_assumptions=financial_assumptions,
            supplier_inputs=supplier_inputs,
            effective_shares=effective_shares,
            method=method,
        )
        country_results.append(
            {
                "Region": country,
                "Current Base Spend": result["current_base_spend"],
                "Current Payment Term Days": result["current_payment_days"],
                "Current Gross Financial Cost": result["current_gross_financial_cost"],
                "Current Capital Gain Offset": result["current_capital_gain_offset"],
                "Current Net Financial Impact": result["current_net_financial_impact"],
                "Current Adjusted Baseline": result["current_adjusted_baseline"],
                # Backward-compatible alias used by charts.
                "Current Spend": result["current_adjusted_baseline"],
                "Proposal Before Finance": result["proposal_before_finance"],
                "Gross Financial Cost": result["gross_financial_cost"],
                "Capital Gain Offset": result["capital_gain_offset"],
                "Net Financial Impact": result["net_financial_impact"],
                "Net Financial Delta": result["net_financial_delta"],
                "Adjusted Proposal": result["adjusted_proposal"],
                # Cost delta convention: negative = saving; positive = impact.
                "Saving / Impact": result["cost_delta"],
                "Saving / Impact %": result["cost_delta_pct"],
                "Risk Score": result["risk_score"],
            }
        )
        detail_rows.extend(result["rows"])

    latam_rows = [row for row in country_results if row["Region"] in LATAM_COUNTRIES]
    latam_current_base = sum(row["Current Base Spend"] for row in latam_rows)
    latam_current_gross = sum(row["Current Gross Financial Cost"] for row in latam_rows)
    latam_current_offset = sum(row["Current Capital Gain Offset"] for row in latam_rows)
    latam_current_net = sum(row["Current Net Financial Impact"] for row in latam_rows)
    latam_current_adjusted = sum(row["Current Adjusted Baseline"] for row in latam_rows)
    latam_before = sum(row["Proposal Before Finance"] for row in latam_rows)
    latam_gross_finance = sum(row["Gross Financial Cost"] for row in latam_rows)
    latam_capital_offset = sum(row["Capital Gain Offset"] for row in latam_rows)
    latam_net_finance = sum(row["Net Financial Impact"] for row in latam_rows)
    latam_net_delta = latam_net_finance - latam_current_net
    latam_adjusted = sum(row["Adjusted Proposal"] for row in latam_rows)
    latam_risk_weight = sum(row["Risk Score"] * row["Adjusted Proposal"] for row in latam_rows)

    brazil_row = next(row for row in country_results if row["Region"] == "Brazil")
    total_current_base = sum(row["Current Base Spend"] for row in country_results)
    total_current_gross = sum(row["Current Gross Financial Cost"] for row in country_results)
    total_current_offset = sum(row["Current Capital Gain Offset"] for row in country_results)
    total_current_net = sum(row["Current Net Financial Impact"] for row in country_results)
    total_current_adjusted = sum(row["Current Adjusted Baseline"] for row in country_results)
    total_before = sum(row["Proposal Before Finance"] for row in country_results)
    total_gross_finance = sum(row["Gross Financial Cost"] for row in country_results)
    total_capital_offset = sum(row["Capital Gain Offset"] for row in country_results)
    total_net_finance = sum(row["Net Financial Impact"] for row in country_results)
    total_net_delta = total_net_finance - total_current_net
    total_adjusted = sum(row["Adjusted Proposal"] for row in country_results)
    total_risk_weight = sum(row["Risk Score"] * row["Adjusted Proposal"] for row in country_results)

    executive_rows = [
        brazil_row,
        {
            "Region": "LATAM",
            "Current Base Spend": latam_current_base,
            "Current Payment Term Days": None,
            "Current Gross Financial Cost": latam_current_gross,
            "Current Capital Gain Offset": latam_current_offset,
            "Current Net Financial Impact": latam_current_net,
            "Current Adjusted Baseline": latam_current_adjusted,
            "Current Spend": latam_current_adjusted,
            "Proposal Before Finance": latam_before,
            "Gross Financial Cost": latam_gross_finance,
            "Capital Gain Offset": latam_capital_offset,
            "Net Financial Impact": latam_net_finance,
            "Net Financial Delta": latam_net_delta,
            "Adjusted Proposal": latam_adjusted,
            "Saving / Impact": latam_adjusted - latam_current_adjusted,
            "Saving / Impact %": safe_divide(latam_adjusted - latam_current_adjusted, latam_current_adjusted),
            "Risk Score": safe_divide(latam_risk_weight, latam_adjusted) if latam_adjusted else 0.0,
        },
        {
            "Region": "Total",
            "Current Base Spend": total_current_base,
            "Current Payment Term Days": None,
            "Current Gross Financial Cost": total_current_gross,
            "Current Capital Gain Offset": total_current_offset,
            "Current Net Financial Impact": total_current_net,
            "Current Adjusted Baseline": total_current_adjusted,
            "Current Spend": total_current_adjusted,
            "Proposal Before Finance": total_before,
            "Gross Financial Cost": total_gross_finance,
            "Capital Gain Offset": total_capital_offset,
            "Net Financial Impact": total_net_finance,
            "Net Financial Delta": total_net_delta,
            "Adjusted Proposal": total_adjusted,
            "Saving / Impact": total_adjusted - total_current_adjusted,
            "Saving / Impact %": safe_divide(total_adjusted - total_current_adjusted, total_current_adjusted),
            "Risk Score": safe_divide(total_risk_weight, total_adjusted) if total_adjusted else 0.0,
        },
    ]

    return pd.DataFrame(executive_rows), pd.DataFrame(detail_rows)


# =============================================================================
# Optimization engine
# =============================================================================


def generate_share_combinations(step: int = 5) -> List[Tuple[int, int, int, int]]:
    values = list(range(0, 101, step))
    combinations = []
    for a in values:
        for b in values:
            for c in values:
                d = 100 - a - b - c
                if d >= 0 and d % step == 0:
                    combinations.append((a, b, c, d))
    return combinations


def compute_candidate_country_cost(
    country: str,
    current_spend: float,
    combo: Tuple[int, int, int, int],
    financial_assumptions: Dict[str, Dict[str, float]],
    supplier_inputs: Dict[str, Dict[str, Dict[str, float]]],
    method: str,
) -> Dict[str, object]:
    effective = {country: dict(zip(SUPPLIERS, [float(x) for x in combo]))}
    result = compute_country_proposal(
        country=country,
        current_spend=current_spend,
        financial_assumptions=financial_assumptions,
        supplier_inputs=supplier_inputs,
        effective_shares=effective,
        method=method,
    )
    return {
        "country": country,
        "combo": combo,
        "adjusted_proposal": result["adjusted_proposal"],
        # Cost delta convention: negative = saving, positive = impact.
        "saving": result["cost_delta"],
        "risk_score": result["risk_score"],
        "saving_pct": result["cost_delta_pct"],
    }


def run_cost_optimization(
    current_spend: Dict[str, float],
    financial_assumptions: Dict[str, Dict[str, float]],
    supplier_inputs: Dict[str, Dict[str, Dict[str, float]]],
    method: str,
    step: int = 5,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Dict[str, float]]]:
    """
    Cost x risk optimizer.

    This is an embedded heuristic optimizer, not an external API call.
    It searches allocation combinations by country while respecting Kraljic minimum shares.
    Primary objective: minimize cost delta. Negative deltas are savings and are preferred.
    Secondary objective: if savings are unavailable, minimize positive impact.
    Risk is used as the tie-breaker, so among economically similar options the optimizer chooses the lower-risk allocation.
    """
    all_combinations = generate_share_combinations(step=step)
    selected_country_rows = []
    optimized_shares = {}

    for country in COUNTRIES:
        minimums = {
            supplier: supplier_inputs[country][supplier]["minimum_share"]
            if supplier_inputs[country][supplier]["kraljic_required"]
            else 0.0
            for supplier in SUPPLIERS
        }
        total_min = sum(minimums.values())
        feasible = []

        for combo in all_combinations:
            combo_map = dict(zip(SUPPLIERS, combo))
            if total_min > 100.0:
                continue
            if any(combo_map[supplier] + 1e-9 < minimums[supplier] for supplier in SUPPLIERS):
                continue
            feasible.append(
                compute_candidate_country_cost(
                    country=country,
                    current_spend=current_spend[country],
                    combo=combo,
                    financial_assumptions=financial_assumptions,
                    supplier_inputs=supplier_inputs,
                    method=method,
                )
            )

        if not feasible:
            # fallback to current normalized shares in an impossible minimum case
            fallback = tuple([100, 0, 0, 0])
            best = compute_candidate_country_cost(
                country=country,
                current_spend=current_spend[country],
                combo=fallback,
                financial_assumptions=financial_assumptions,
                supplier_inputs=supplier_inputs,
                method=method,
            )
        else:
            candidate_df = pd.DataFrame(feasible)
            # Efficient frontier: remove candidates dominated by lower/equal risk and lower/equal cost delta.
            # Cost delta convention: negative = saving, positive = impact. Lower is better.
            frontier_indices = []
            for idx, row in candidate_df.iterrows():
                dominated = candidate_df[
                    (candidate_df["risk_score"] <= row["risk_score"] + 1e-9)
                    & (candidate_df["saving"] <= row["saving"] + 1e-9)
                    & (
                        (candidate_df["risk_score"] < row["risk_score"] - 1e-9)
                        | (candidate_df["saving"] < row["saving"] - 1e-9)
                    )
                ]
                if dominated.empty:
                    frontier_indices.append(idx)
            frontier = candidate_df.loc[frontier_indices].copy()

            # Optimization priority requested by Procurement:
            # 1) pick the strongest saving, represented by the most negative cost delta;
            # 2) if impact is unavoidable, pick the lowest positive impact;
            # 3) use lower weighted risk as the tie-breaker.
            best = frontier.sort_values(["saving", "risk_score"], ascending=[True, True]).iloc[0].to_dict()

        optimized_shares[country] = dict(zip(SUPPLIERS, [float(x) for x in best["combo"]]))
        selected_country_rows.append(
            {
                "Country": country,
                "Adjusted Proposal": best["adjusted_proposal"],
                "Saving / Impact": best["saving"],
                "Saving / Impact %": best["saving_pct"],
                "Risk Score": best["risk_score"],
                **{f"{supplier} Share %": optimized_shares[country][supplier] for supplier in SUPPLIERS},
            }
        )

    optimized_summary, optimized_details = compute_full_scenario(
        current_spend=current_spend,
        financial_assumptions=financial_assumptions,
        supplier_inputs=supplier_inputs,
        effective_shares=optimized_shares,
        method=method,
    )

    country_recommendation_df = pd.DataFrame(selected_country_rows)
    return optimized_summary, optimized_details.merge(country_recommendation_df[["Country"]], on="Country", how="inner"), optimized_shares


# =============================================================================
# Chart helpers
# =============================================================================


def plot_executive_comparison(summary_df: pd.DataFrame, currency: str) -> None:
    chart_df = summary_df[summary_df["Region"].isin(["Brazil", "LATAM"])].copy()
    if PLOTLY_AVAILABLE:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=chart_df["Region"],
                y=chart_df["Current Spend"],
                name="Current Adjusted Baseline",
                marker_color="#94a3b8",
                hovertemplate="Current Adjusted Baseline<br>" + currency + " %{y:,.2f}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Bar(
                x=chart_df["Region"],
                y=chart_df["Adjusted Proposal"],
                name="Adjusted Proposal",
                marker_color="#2563eb",
                hovertemplate="Adjusted Proposal<br>" + currency + " %{y:,.2f}<extra></extra>",
            )
        )
        fig.update_layout(
            title="Brazil and LATAM: Current Adjusted Baseline vs Adjusted Proposal",
            barmode="group",
            height=410,
            margin=dict(l=20, r=20, t=55, b=30),
            yaxis_title=f"Spend ({currency})",
            plot_bgcolor="white",
            paper_bgcolor="white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        apply_graphite_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.bar_chart(chart_df.set_index("Region")[["Current Spend", "Adjusted Proposal"]])


def plot_saving_impact(summary_df: pd.DataFrame, currency: str) -> None:
    chart_df = summary_df[summary_df["Region"].isin(["Brazil", "LATAM"])].copy()
    if PLOTLY_AVAILABLE:
        colors = ["#10b981" if x <= 0 else "#ef4444" for x in chart_df["Saving / Impact"]]
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=chart_df["Region"],
                y=chart_df["Saving / Impact"],
                marker_color=colors,
                text=[format_delta(v, currency, compact=True) for v in chart_df["Saving / Impact"]],
                textposition="outside",
                hovertemplate="%{x}<br>Cost Delta: " + currency + " %{y:,.2f}<br>Negative = saving<extra></extra>",
            )
        )
        fig.add_hline(y=0, line_dash="dash", line_color="#64748b")
        fig.update_layout(
            title="Cost Delta by Executive Region",
            height=410,
            margin=dict(l=20, r=20, t=55, b=30),
            yaxis_title=f"Cost Delta ({currency}) - negative = saving",
            plot_bgcolor="white",
            paper_bgcolor="white",
            showlegend=False,
        )
        apply_graphite_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.bar_chart(chart_df.set_index("Region")[["Saving / Impact"]])


def plot_supplier_mix(details_df: pd.DataFrame) -> None:
    mix_df = details_df.groupby("Supplier", as_index=False)["Adjusted Proposal Spend"].sum()
    if PLOTLY_AVAILABLE:
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=mix_df["Supplier"],
                    values=mix_df["Adjusted Proposal Spend"],
                    hole=0.55,
                    textinfo="label+percent",
                    textfont=dict(color=GRAPHITE),
                    hovertemplate="%{label}<br>%{value:,.2f}<extra></extra>",
                )
            ]
        )
        fig.update_layout(
            title="Adjusted Proposal Spend Mix by Supplier",
            height=410,
            margin=dict(l=20, r=20, t=55, b=30),
            plot_bgcolor="white",
            paper_bgcolor="white",
        )
        apply_graphite_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.bar_chart(mix_df.set_index("Supplier"))


def plot_risk_vs_saving(summary_df: pd.DataFrame) -> None:
    chart_df = summary_df[summary_df["Region"].isin(["Brazil", "LATAM"])].copy()
    if PLOTLY_AVAILABLE:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=chart_df["Risk Score"],
                y=chart_df["Saving / Impact"],
                mode="markers+text",
                text=chart_df["Region"],
                textposition="top center",
                marker=dict(size=18, color=["#2563eb", "#14b8a6"]),
                hovertemplate="Risk Score: %{x:.2f}<br>Cost Delta: %{y:,.2f}<br>Negative = saving<extra></extra>",
            )
        )
        fig.add_hline(y=0, line_dash="dash", line_color="#ef4444")
        fig.update_layout(
            title="Risk vs Cost Delta",
            height=410,
            margin=dict(l=20, r=20, t=55, b=30),
            xaxis_title="Weighted Risk Score - lower is better",
            yaxis_title="Cost Delta - negative = saving",
            plot_bgcolor="white",
            paper_bgcolor="white",
            showlegend=False,
        )
        apply_graphite_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.scatter_chart(chart_df, x="Risk Score", y="Saving / Impact")


# =============================================================================
# Sidebar inputs
# =============================================================================

with st.sidebar:
    st.markdown("## Executive Settings")
    currency_symbol = st.text_input("Currency", value="USD")
    calculation_method = st.radio(
        "Equivalent rate method",
        options=["Compound equivalent", "Linear simple"],
        index=0,
    )
    optimization_step = st.selectbox(
        "Optimization allocation step",
        options=[10, 5],
        index=1,
        help="5% is more precise. 10% is faster for online environments.",
    )
    st.markdown("---")
    st.caption("The optimizer is an embedded heuristic engine. It does not call any external API.")


# =============================================================================
# Header
# =============================================================================

st.markdown(
    """
    <div class="executive-hero">
        <h1>Executive Procurement TCO & Should-Cost Dashboard</h1>
        <p>
            Country-level financial assumptions, supplier-level proposal inputs, automatic allocation normalization,
            Kraljic minimum-share protection, invested-cash return offset, risk scoring and cost optimization for Brazil and consolidated LATAM.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# Main inputs
# =============================================================================

initialize_share_projection_state()

# Apply optimizer recommendations before Share Projection slider widgets are instantiated.
# Streamlit does not allow changing st.session_state values tied to already-created widgets
# later in the same run. The Cost Optimization button therefore stores recommendations
# in a neutral key and triggers a rerun; this block safely pushes them into slider keys
# at the beginning of the next run.
if "pending_optimized_shares" in st.session_state:
    pending_optimized_shares = st.session_state.pop("pending_optimized_shares")
    for country in COUNTRIES:
        for supplier in SUPPLIERS:
            if country in pending_optimized_shares and supplier in pending_optimized_shares[country]:
                st.session_state[f"share_{country}_{supplier}"] = float(pending_optimized_shares[country][supplier])
    st.session_state["share_projection_mode"] = "Automatic"
    st.session_state["optimization_message"] = "Cost Optimization applied automatically to Share Projection sliders."

input_tab_1, input_tab_2, input_tab_3, input_tab_4 = st.tabs(
    [
        "1. Current Spend",
        "2. Financial Assumptions",
        "3. Supplier Proposals",
        "4. Share Projection & Kraljic Risk",
    ]
)

current_spend: Dict[str, float] = {}
financial_assumptions: Dict[str, Dict[str, float]] = {}
supplier_inputs: Dict[str, Dict[str, Dict[str, float]]] = {country: {} for country in COUNTRIES}
raw_shares: Dict[str, Dict[str, float]] = {country: {} for country in COUNTRIES}
minimums: Dict[str, Dict[str, float]] = {country: {} for country in COUNTRIES}
effective_shares: Dict[str, Dict[str, float]] = {country: {} for country in COUNTRIES}

with input_tab_1:
    render_section_header(
        "Current Spend by Locality",
        "Mexico, Argentina and Colombia are automatically consolidated as LATAM in the executive view.",
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        current_spend["Brazil"] = st.number_input("Brazil current spend", min_value=0.0, value=13_000_000.0, step=100_000.0, format="%.2f")
    with c2:
        current_spend["Mexico"] = st.number_input("Mexico current spend", min_value=0.0, value=1_500_000.0, step=100_000.0, format="%.2f")
    with c3:
        current_spend["Argentina"] = st.number_input("Argentina current spend", min_value=0.0, value=2_500_000.0, step=100_000.0, format="%.2f")
    with c4:
        current_spend["Colombia"] = st.number_input("Colombia current spend", min_value=0.0, value=3_000_000.0, step=100_000.0, format="%.2f")

with input_tab_2:
    render_section_header(
        "Financial Assumptions by Country",
        "Each country has its own supplier financing rate and investment return assumption. The investment return offsets the payment-term financing cost because the retained cash works during the payment term.",
    )
    for country in COUNTRIES:
        st.markdown(f"**{country}**")
        fc1, fc2, fc3, fc4, fc5 = st.columns(5)
        default_financing_rate = {"Brazil": 15.23, "Mexico": 7.10, "Argentina": 35.00, "Colombia": 9.50}[country]
        default_investment_return = {"Brazil": 15.23, "Mexico": 7.10, "Argentina": 35.00, "Colombia": 9.50}[country]
        default_days = {"Brazil": 360, "Mexico": 360, "Argentina": 360, "Colombia": 360}[country]
        default_current_payment_days = {"Brazil": 360, "Mexico": 360, "Argentina": 360, "Colombia": 360}[country]
        with fc1:
            financing_rate = st.number_input(
                f"{country} supplier financing rate (%)",
                min_value=0.0,
                value=float(default_financing_rate),
                step=0.05,
                format="%.4f",
                key=f"financing_rate_{country}",
                help="Reference rate charged by suppliers for payment term financing.",
            )
        with fc2:
            financing_days = st.number_input(
                f"{country} financing reference days",
                min_value=1,
                value=int(default_days),
                step=1,
                key=f"financing_days_{country}",
            )
        with fc3:
            investment_return_rate = st.number_input(
                f"{country} investment return rate (%)",
                min_value=0.0,
                value=float(default_investment_return),
                step=0.05,
                format="%.4f",
                key=f"investment_return_rate_{country}",
                help="Expected return earned by keeping cash invested until supplier payment date.",
            )
        with fc4:
            investment_return_days = st.number_input(
                f"{country} return reference days",
                min_value=1,
                value=int(default_days),
                step=1,
                key=f"investment_return_days_{country}",
            )
        with fc5:
            current_payment_days = st.number_input(
                f"{country} current payment term days",
                min_value=0,
                value=int(default_current_payment_days),
                step=1,
                key=f"current_payment_days_{country}",
                help="Used to build the adjusted current baseline, so current and proposal are compared under the same financial logic.",
            )
        financial_assumptions[country] = {
            "financing_rate_pct": financing_rate,
            "financing_days": financing_days,
            "investment_return_rate_pct": investment_return_rate,
            "investment_return_days": investment_return_days,
            "current_payment_days": current_payment_days,
        }
        st.caption(
            f"{country}: current baseline and supplier proposals are both adjusted with financing cost minus invested-cash return."
        )

with input_tab_3:
    render_section_header(
        "Supplier Proposal Inputs by Country",
        "For each country and supplier, enter expected spend and expected payment term. Financial cost will be calculated from the country rate.",
    )
    for country in COUNTRIES:
        with st.expander(f"{country} supplier proposals", expanded=(country == "Brazil")):
            for supplier in SUPPLIERS:
                st.markdown(f"**{supplier}**")
                pc1, pc2 = st.columns(2)
                # Default proposal multipliers mirror the validation spreadsheet shared by the user:
                # ChemPrime = 125% of current spend, OleoGlobal = 75%, Overseas = 78.75%, Distribuicao = 81%.
                proposal_spend_multiplier = {
                    "ChemPrime": 1.25,
                    "OleoGlobal": 0.75,
                    "Oleo Overseas Trading Co.": 0.7875,
                    "Comercio de Oleos Nacional Distribuicao": 0.81,
                }[supplier]
                proposal_payment_days = {
                    "ChemPrime": 90,
                    "OleoGlobal": 70,
                    "Oleo Overseas Trading Co.": 150,
                    "Comercio de Oleos Nacional Distribuicao": 120,
                }[supplier]
                default_spend = current_spend.get(country, 0.0) * proposal_spend_multiplier
                default_payment = proposal_payment_days
                with pc1:
                    spend = st.number_input(
                        f"{country} | {supplier} | Expected spend",
                        min_value=0.0,
                        value=float(default_spend),
                        step=100_000.0,
                        format="%.2f",
                        key=f"spend_{country}_{supplier}",
                    )
                with pc2:
                    payment_days = st.number_input(
                        f"{country} | {supplier} | Expected payment term days",
                        min_value=0,
                        value=int(default_payment),
                        step=1,
                        key=f"pay_{country}_{supplier}",
                    )
                # Placeholder fields filled in tab 4.
                supplier_inputs[country][supplier] = {
                    "spend": spend,
                    "payment_days": payment_days,
                    "risk_score": DEFAULT_RISK[supplier],
                    "kraljic_required": False,
                    "minimum_share": 0.0,
                }

with input_tab_4:
    render_section_header(
        "Share Projection and Kraljic Risk Controls",
        "Use the sliders as a scenario gadget. Supplier proposal fields remain fully editable in the Supplier Proposals tab.",
    )

    if "share_projection_mode" not in st.session_state:
        st.session_state["share_projection_mode"] = "Automatic"

    mode_col_1, mode_col_2, mode_col_3 = st.columns([1, 1, 4])
    with mode_col_1:
        if st.button(
            "Automatic",
            type="primary" if st.session_state["share_projection_mode"] == "Automatic" else "secondary",
            use_container_width=True,
            help="When one supplier share is changed, the other supplier shares are automatically rebalanced proportionally to keep the country total at 100%.",
        ):
            st.session_state["share_projection_mode"] = "Automatic"
    with mode_col_2:
        if st.button(
            "Manual",
            type="primary" if st.session_state["share_projection_mode"] == "Manual" else "secondary",
            use_container_width=True,
            help="Each supplier share can be moved independently. The effective model share is normalized for calculation if the visible total is different from 100%.",
        ):
            st.session_state["share_projection_mode"] = "Manual"
    with mode_col_3:
        if st.session_state["share_projection_mode"] == "Automatic":
            st.info(
                "Automatic mode is active: change one supplier slider and the other shares will rebalance proportionally. "
                "This is only a projection gadget; spend and payment terms remain controlled in Supplier Proposals."
            )
        else:
            st.warning(
                "Manual mode is active: sliders do not modify each other. If the visible total is not 100%, "
                "the model uses the normalized Effective Share % shown below."
            )

    for country in COUNTRIES:
        with st.expander(f"{country} share projection and risk", expanded=(country == "Brazil")):
            st.caption(
                "Projected shares drive the scenario calculation in real time. Supplier expected spend and payment terms remain editable in the Supplier Proposals tab."
            )

            # First row: share projection sliders only.
            st.markdown("**Share Projection**")
            share_cols = st.columns(4)
            for idx_supplier, supplier in enumerate(SUPPLIERS):
                share_key = f"share_{country}_{supplier}"
                with share_cols[idx_supplier]:
                    if st.session_state["share_projection_mode"] == "Automatic":
                        st.slider(
                            supplier,
                            min_value=0.0,
                            max_value=100.0,
                            step=0.1,
                            key=share_key,
                            on_change=auto_adjust_supplier_share,
                            args=(country, supplier),
                            help="Automatic mode: changing this supplier rebalances the remaining suppliers proportionally.",
                        )
                    else:
                        st.slider(
                            supplier,
                            min_value=0.0,
                            max_value=100.0,
                            step=0.1,
                            key=share_key,
                            help="Manual mode: this supplier can be moved independently. The effective model share is normalized below.",
                        )

            raw_shares[country] = get_slider_share_values(country)
            visible_total = sum(raw_shares[country].values())

            if st.session_state["share_projection_mode"] == "Manual" and abs(visible_total - 100.0) > 0.01:
                st.caption(
                    f"Visible manual share total: {visible_total:.1f}%. The calculation will use normalized Effective Share % to keep the scenario at 100%."
                )
            else:
                st.caption(f"Visible share total: {visible_total:.1f}%")

            st.markdown("**Kraljic Minimum and Risk Controls**")
            for supplier in SUPPLIERS:
                ac1, ac2, ac3 = st.columns([1.25, 1, 1])
                with ac1:
                    kraljic_required = st.checkbox(
                        f"{supplier} | Kraljic minimum required",
                        value=False,
                        key=f"kraljic_{country}_{supplier}",
                    )
                with ac2:
                    min_share = st.number_input(
                        f"{supplier} | Minimum share %",
                        min_value=0.0,
                        max_value=100.0,
                        value=20.0 if kraljic_required else 0.0,
                        step=1.0,
                        key=f"min_{country}_{supplier}",
                        disabled=not kraljic_required,
                    )
                with ac3:
                    risk_score = st.slider(
                        f"{supplier} | Risk score",
                        min_value=1.0,
                        max_value=5.0,
                        value=float(DEFAULT_RISK[supplier]),
                        step=0.5,
                        key=f"risk_{country}_{supplier}",
                        help="1 = lowest risk, 5 = highest risk.",
                    )

                minimums[country][supplier] = min_share if kraljic_required else 0.0
                supplier_inputs[country][supplier]["risk_score"] = risk_score
                supplier_inputs[country][supplier]["kraljic_required"] = kraljic_required
                supplier_inputs[country][supplier]["minimum_share"] = min_share if kraljic_required else 0.0

            total_min = sum(minimums[country].values())
            if total_min > 100.0:
                st.error(f"{country}: Kraljic minimum shares sum to {total_min:.1f}%. Reduce minimum requirements to 100% or less.")

            effective_shares[country] = normalize_with_minimums(raw_shares[country], minimums[country])
            effective_df = pd.DataFrame(
                {
                    "Supplier": SUPPLIERS,
                    "Projected Slider Share %": [raw_shares[country][s] for s in SUPPLIERS],
                    "Kraljic Minimum Share %": [minimums[country][s] for s in SUPPLIERS],
                    "Effective Model Share %": [effective_shares[country][s] for s in SUPPLIERS],
                }
            )
            st.dataframe(
                effective_df.style.format(
                    {
                        "Projected Slider Share %": "{:.1f}",
                        "Kraljic Minimum Share %": "{:.1f}",
                        "Effective Model Share %": "{:.1f}",
                    }
                ),
                use_container_width=True,
            )

# Ensure effective shares exist when tab 4 was not interacted with in a fresh rerun.
for country in COUNTRIES:
    if not effective_shares[country]:
        raw_shares[country] = {supplier: 100.0 if supplier == "ChemPrime" else 0.0 for supplier in SUPPLIERS}
        minimums[country] = {supplier: 0.0 for supplier in SUPPLIERS}
        effective_shares[country] = normalize_with_minimums(raw_shares[country], minimums[country])


# =============================================================================
# Results
# =============================================================================

summary_df, details_df = compute_full_scenario(
    current_spend=current_spend,
    financial_assumptions=financial_assumptions,
    supplier_inputs=supplier_inputs,
    effective_shares=effective_shares,
    method=calculation_method,
)

total_row = summary_df[summary_df["Region"] == "Total"].iloc[0]
brazil_row = summary_df[summary_df["Region"] == "Brazil"].iloc[0]
latam_row = summary_df[summary_df["Region"] == "LATAM"].iloc[0]
is_saving = total_row["Saving / Impact"] <= 0
result_label = "Saving" if is_saving else "Impact"
result_tone = delta_tone(total_row["Saving / Impact"])

render_section_header(
    "Executive Result",
    "Decision-ready view shown separately for Brazil and consolidated LATAM, plus total scenario impact.",
)

k1, k2, k3, k4, k5 = st.columns(5)
with k1:
    render_kpi_card("Current Adjusted Baseline", format_money(total_row["Current Spend"], currency_symbol, True), "Current base spend + current net financial effect", "neutral")
with k2:
    render_kpi_card("Total Adjusted Proposal", format_money(total_row["Adjusted Proposal"], currency_symbol, True), "Weighted by supplier shares", "neutral")
with k3:
    render_kpi_card(result_label, format_delta(total_row["Saving / Impact"], currency_symbol, True), f"{format_percent(abs(total_row['Saving / Impact %']))} vs adjusted baseline", result_tone)
with k4:
    render_kpi_card("Net Financial Delta", format_delta(total_row["Net Financial Delta"], currency_symbol, True), "Proposal net finance minus current net finance", delta_tone(total_row["Net Financial Delta"]))
with k5:
    render_kpi_card("Weighted Risk", f"{total_row['Risk Score']:.2f}/5", "Lower is better", "neutral")

# Visual breathing room between the total KPI row and the Brazil/LATAM result row.
st.markdown('<div class="executive-row-spacer"></div>', unsafe_allow_html=True)

r1c1, r1c2 = st.columns(2)
with r1c1:
    render_kpi_card(
        "Brazil Result",
        format_delta(brazil_row["Saving / Impact"], currency_symbol, True),
        f"{delta_label(brazil_row['Saving / Impact'])} | Risk {brazil_row['Risk Score']:.2f}/5",
        delta_tone(brazil_row["Saving / Impact"]),
        compact=True,
    )
with r1c2:
    render_kpi_card(
        "LATAM Result",
        format_delta(latam_row["Saving / Impact"], currency_symbol, True),
        f"{delta_label(latam_row['Saving / Impact'])} | Risk {latam_row['Risk Score']:.2f}/5",
        delta_tone(latam_row["Saving / Impact"]),
        compact=True,
    )

if is_saving:
    st.markdown(
        f"""
        <div class="decision-card decision-good">
            <div class="decision-title">Recommended scenario is financially attractive under the current allocation</div>
            <div class="decision-body">
                The adjusted proposal is below the current adjusted baseline by
                <b>{format_delta(total_row['Saving / Impact'], currency_symbol)}</b>, equivalent to
                <b>{format_percent(abs(total_row['Saving / Impact %']))}</b>, with a weighted risk score of
                <b>{total_row['Risk Score']:.2f}/5</b>.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"""
        <div class="decision-card decision-bad">
            <div class="decision-title">Current allocation creates a cost impact under the current assumptions</div>
            <div class="decision-body">
                The adjusted proposal is above the current adjusted baseline by
                <b>{format_delta(total_row['Saving / Impact'], currency_symbol)}</b>, equivalent to
                <b>{format_percent(abs(total_row['Saving / Impact %']))}</b>. Use Cost Optimization to search for a better cost x risk allocation.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

chart_col1, chart_col2 = st.columns(2)
with chart_col1:
    plot_executive_comparison(summary_df, currency_symbol)
with chart_col2:
    plot_saving_impact(summary_df, currency_symbol)

chart_col3, chart_col4 = st.columns(2)
with chart_col3:
    plot_supplier_mix(details_df)
with chart_col4:
    plot_risk_vs_saving(summary_df)

render_section_header("Scenario Breakdown", "Proposal comparison by Brazil, LATAM and total scenario.")
display_summary = summary_df.copy()
if "Financial Cost" in display_summary.columns:
    display_summary = display_summary.drop(columns=["Financial Cost"])
# Avoid banana-vs-orange confusion: show both the base spend and the adjusted current baseline.
if "Current Spend" in display_summary.columns:
    display_summary = display_summary.drop(columns=["Current Spend"])
ordered_summary_columns = [
    "Region",
    "Current Base Spend",
    "Current Gross Financial Cost",
    "Current Capital Gain Offset",
    "Current Net Financial Impact",
    "Current Adjusted Baseline",
    "Proposal Before Finance",
    "Gross Financial Cost",
    "Capital Gain Offset",
    "Net Financial Impact",
    "Net Financial Delta",
    "Adjusted Proposal",
    "Saving / Impact",
    "Saving / Impact %",
    "Risk Score",
]
display_summary = display_summary[[col for col in ordered_summary_columns if col in display_summary.columns]]
for column in [
    "Current Base Spend",
    "Current Gross Financial Cost",
    "Current Capital Gain Offset",
    "Current Adjusted Baseline",
    "Proposal Before Finance",
    "Gross Financial Cost",
    "Capital Gain Offset",
    "Adjusted Proposal",
]:
    display_summary[column] = display_summary[column].map(lambda x: format_money(x, currency_symbol))
for column in ["Current Net Financial Impact", "Net Financial Impact", "Net Financial Delta", "Saving / Impact"]:
    if column in display_summary.columns:
        display_summary[column] = display_summary[column].map(lambda x: format_delta(x, currency_symbol))
display_summary["Saving / Impact %"] = display_summary["Saving / Impact %"].map(format_percent)
display_summary["Risk Score"] = display_summary["Risk Score"].map(lambda x: f"{x:.2f}/5")
st.dataframe(display_summary, use_container_width=True)

with st.expander("Supplier-level proposal details"):
    display_details = details_df.copy()
    for money_col in ["Proposal Spend", "Allocated Spend Before Finance", "Gross Financial Cost", "Capital Gain Offset", "Net Financial Impact", "Adjusted Proposal Spend"]:
        display_details[money_col] = display_details[money_col].map(lambda x: format_money(x, currency_symbol))
    display_details["Supplier Financing Rate"] = display_details["Supplier Financing Rate"].map(format_percent)
    display_details["Investment Return Rate"] = display_details["Investment Return Rate"].map(format_percent)
    display_details["Effective Share %"] = display_details["Effective Share %"].map(lambda x: f"{x:.1f}%")
    display_details["Minimum Share %"] = display_details["Minimum Share %"].map(lambda x: f"{x:.1f}%")
    display_details["Risk Score"] = display_details["Risk Score"].map(lambda x: f"{x:.1f}/5")
    st.dataframe(display_details, use_container_width=True)


# =============================================================================
# Cost Optimization
# =============================================================================

render_section_header(
    "Cost Optimization",
    "Searches the best allocation considering supplier proposal cost, country financial cost, Kraljic minimum shares and weighted risk score.",
)

opt_col1, opt_col2 = st.columns([1, 3])
with opt_col1:
    run_optimizer = st.button("Cost Optimization", type="primary", use_container_width=True)
with opt_col2:
    st.markdown(
        """
        <div class="small-note">
        Optimization objective: minimize total cost delta versus the adjusted current baseline while respecting Kraljic minimum requirements. Negative cost delta = saving.
        This is an embedded heuristic optimizer, not an external API call.
        </div>
        """,
        unsafe_allow_html=True,
    )

if run_optimizer:
    optimized_summary, optimized_details, optimized_shares = run_cost_optimization(
        current_spend=current_spend,
        financial_assumptions=financial_assumptions,
        supplier_inputs=supplier_inputs,
        method=calculation_method,
        step=int(optimization_step),
    )

    # Store optimized allocation in a neutral key, then rerun.
    # The values are applied to the actual slider widget keys at the top of the next run,
    # before those widgets are created. This avoids StreamlitAPIException.
    st.session_state["pending_optimized_shares"] = optimized_shares
    st.rerun()

if st.session_state.get("optimization_message"):
    st.success(st.session_state["optimization_message"])
    del st.session_state["optimization_message"]

    # Recompute after the optimized sliders have been applied.
    optimized_summary = summary_df
    optimized_details = details_df
    optimized_total = optimized_summary[optimized_summary["Region"] == "Total"].iloc[0]

    st.info(
        f"Optimized scenario now active: {format_delta(optimized_total['Saving / Impact'], currency_symbol)} cost delta, "
        f"{format_percent(abs(optimized_total['Saving / Impact %']))}, weighted risk {optimized_total['Risk Score']:.2f}/5."
    )

    o1, o2 = st.columns(2)
    with o1:
        opt_display = optimized_summary.copy()
        if "Financial Cost" in opt_display.columns:
            opt_display = opt_display.drop(columns=["Financial Cost"])
        if "Current Spend" in opt_display.columns:
            opt_display = opt_display.drop(columns=["Current Spend"])
        opt_display = opt_display[[col for col in ordered_summary_columns if col in opt_display.columns]]
        for column in [
            "Current Base Spend",
            "Current Gross Financial Cost",
            "Current Capital Gain Offset",
            "Current Adjusted Baseline",
            "Proposal Before Finance",
            "Gross Financial Cost",
            "Capital Gain Offset",
            "Adjusted Proposal",
        ]:
            if column in opt_display.columns:
                opt_display[column] = opt_display[column].map(lambda x: format_money(x, currency_symbol))
        for column in ["Current Net Financial Impact", "Net Financial Impact", "Net Financial Delta", "Saving / Impact"]:
            if column in opt_display.columns:
                opt_display[column] = opt_display[column].map(lambda x: format_delta(x, currency_symbol))
        opt_display["Saving / Impact %"] = opt_display["Saving / Impact %"].map(format_percent)
        opt_display["Risk Score"] = opt_display["Risk Score"].map(lambda x: f"{x:.2f}/5")
        st.markdown("**Optimized executive summary**")
        st.dataframe(opt_display, use_container_width=True)
    with o2:
        allocation_view = optimized_details[["Country", "Supplier", "Effective Share %", "Adjusted Proposal Spend", "Risk Score"]].copy()
        allocation_view["Effective Share %"] = allocation_view["Effective Share %"].map(lambda x: f"{x:.1f}%")
        allocation_view["Adjusted Proposal Spend"] = allocation_view["Adjusted Proposal Spend"].map(lambda x: format_money(x, currency_symbol))
        allocation_view["Risk Score"] = allocation_view["Risk Score"].map(lambda x: f"{x:.1f}/5")
        st.markdown("**Optimized supplier allocation now applied**")
        st.dataframe(allocation_view, use_container_width=True)

    st.markdown(
        f"""
        <div class="insight-box">
            <b>Automatic optimization reading</b><br><br>
            The optimizer searched allocation combinations in {optimization_step}% increments by country, respected all Kraljic minimum-share constraints,
            applied each country's supplier financing assumption, offset it with each country's invested-cash return assumption,
            and selected the allocation with the lowest cost delta. Risk was used as the tie-breaker.
            <br><br>
            Best total adjusted proposal now active: <b>{format_money(optimized_total['Adjusted Proposal'], currency_symbol)}</b><br>
            Best total cost delta now active: <b>{format_delta(optimized_total['Saving / Impact'], currency_symbol)}</b><br>
            Weighted risk score: <b>{optimized_total['Risk Score']:.2f}/5</b>
        </div>
        """,
        unsafe_allow_html=True,
    )

# =============================================================================
# Export
# =============================================================================

export_summary = summary_df.copy()
if "Financial Cost" in export_summary.columns:
    export_summary = export_summary.drop(columns=["Financial Cost"])
export_details = details_df.copy()

csv_summary = export_summary.to_csv(index=False).encode("utf-8")
csv_details = export_details.to_csv(index=False).encode("utf-8")

download_col1, download_col2 = st.columns(2)
with download_col1:
    st.download_button(
        "Download executive summary CSV",
        data=csv_summary,
        file_name="executive_tco_summary.csv",
        mime="text/csv",
        use_container_width=True,
    )
with download_col2:
    st.download_button(
        "Download supplier details CSV",
        data=csv_details,
        file_name="supplier_tco_details.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.markdown(
    """
    <div class="small-note">
        Governance note: this model is based on user-entered assumptions. Final sourcing decisions should also consider supplier capacity,
        quality, logistics, tax treatment, compliance, contractual exposure, supply continuity and Kraljic category strategy.
    </div>
    """,
    unsafe_allow_html=True,
)
