"""
Executive Procurement TCO & Should-Cost Dashboard
Version: v14 - Working Capital Carry + Advanced Optimization

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
            min-height: 156px;
            height: 156px;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
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
            font-size: 0.82rem;
            line-height: 1.28;
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


def annualized_rate_from_period(period_rate: float, period_days: int, method: str) -> float:
    """Return a 360-day annualized rate from a period rate."""
    if period_days <= 0:
        return 0.0
    if method == "Linear simple":
        return period_rate * (360 / period_days)
    return (1 + period_rate) ** (360 / period_days) - 1


def working_capital_net_effect(base_amount: float, financing_rate: float, investment_return_rate: float) -> Dict[str, float]:
    """
    Procurement payment-term economics.

    Gross supplier financing cost is the cost charged by the supplier for the term.
    Capital gain offset is the return earned by keeping cash invested until payment.
    Net financial impact is what remains after offset.

    Positive net impact increases cost. Negative net impact creates financial benefit.
    """
    gross_financial_cost = base_amount * financing_rate
    capital_gain_offset = base_amount * investment_return_rate
    net_financial_impact = gross_financial_cost - capital_gain_offset
    economic_total = base_amount + net_financial_impact
    gross_total = base_amount + gross_financial_cost
    return {
        "gross_financial_cost": gross_financial_cost,
        "capital_gain_offset": capital_gain_offset,
        "net_financial_impact": net_financial_impact,
        "economic_total": economic_total,
        "gross_total": gross_total,
    }


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


def get_country_minimums_from_state(country: str) -> Dict[str, float]:
    """Read Kraljic minimum-share requirements from Streamlit session state."""
    minimums = {}
    for supplier in SUPPLIERS:
        required = bool(st.session_state.get(f"kraljic_{country}_{supplier}", False))
        if required:
            minimum_value = float(st.session_state.get(f"min_{country}_{supplier}", 20.0))
            minimums[supplier] = min(100.0, max(0.0, minimum_value))
        else:
            minimums[supplier] = 0.0
    return minimums


def enforce_kraljic_minimums_on_slider_state(country: str, minimums: Dict[str, float]) -> None:
    """
    Push Kraljic minimum-share requirements into the visible Share Projection sliders.

    Streamlit does not allow changing a slider key after the slider is rendered.
    This function is therefore called immediately before the share sliders are created.
    """
    total_min = sum(max(0.0, minimums.get(supplier, 0.0)) for supplier in SUPPLIERS)
    if total_min > 100.0:
        # Invalid Kraljic configuration. Let the UI warning handle it and do not mutate sliders.
        return

    raw_shares = {
        supplier: max(0.0, float(st.session_state.get(f"share_{country}_{supplier}", 0.0)))
        for supplier in SUPPLIERS
    }

    changed = False
    for supplier in SUPPLIERS:
        minimum = max(0.0, minimums.get(supplier, 0.0))
        if raw_shares[supplier] < minimum:
            raw_shares[supplier] = minimum
            changed = True

    current_total = sum(raw_shares.values())
    if changed or abs(current_total - 100.0) > 0.01:
        normalized = normalize_with_minimums(raw_shares, minimums)
        for supplier in SUPPLIERS:
            st.session_state[f"share_{country}_{supplier}"] = round(normalized[supplier], 1)


def auto_adjust_supplier_share(country: str, changed_supplier: str) -> None:
    """
    Automatic Share Projection behavior.

    When one supplier's share is changed, the remaining suppliers are adjusted
    proportionally so that the visible slider values continue to sum to 100%.
    Kraljic minimum shares are treated as locked floors.
    """
    if st.session_state.get("share_projection_mode", "Automatic") != "Automatic":
        return

    minimums = get_country_minimums_from_state(country)
    total_min = sum(max(0.0, minimums.get(supplier, 0.0)) for supplier in SUPPLIERS)
    if total_min > 100.0:
        return

    changed_key = f"share_{country}_{changed_supplier}"
    changed_min = max(0.0, minimums.get(changed_supplier, 0.0))
    other_suppliers = [supplier for supplier in SUPPLIERS if supplier != changed_supplier]
    other_min_total = sum(max(0.0, minimums.get(supplier, 0.0)) for supplier in other_suppliers)

    max_allowed_for_changed = max(changed_min, 100.0 - other_min_total)
    changed_value = float(st.session_state.get(changed_key, changed_min))
    changed_value = min(max_allowed_for_changed, max(changed_min, changed_value))
    changed_value = round(changed_value, 1)
    st.session_state[changed_key] = changed_value

    remaining_share = max(0.0, 100.0 - changed_value)
    remaining_after_other_minimums = max(0.0, remaining_share - other_min_total)

    other_excess_values = {}
    for supplier in other_suppliers:
        current_value = float(st.session_state.get(f"share_{country}_{supplier}", 0.0))
        supplier_min = max(0.0, minimums.get(supplier, 0.0))
        other_excess_values[supplier] = max(0.0, current_value - supplier_min)

    total_excess = sum(other_excess_values.values())
    if total_excess <= 1e-9:
        adjustable_suppliers = [s for s in other_suppliers if minimums.get(s, 0.0) < 100.0]
        equal_extra = remaining_after_other_minimums / len(adjustable_suppliers) if adjustable_suppliers else 0.0
        for supplier in other_suppliers:
            supplier_min = max(0.0, minimums.get(supplier, 0.0))
            extra = equal_extra if supplier in adjustable_suppliers else 0.0
            st.session_state[f"share_{country}_{supplier}"] = round(supplier_min + extra, 1)
    else:
        for supplier in other_suppliers:
            supplier_min = max(0.0, minimums.get(supplier, 0.0))
            proportional_extra = remaining_after_other_minimums * other_excess_values[supplier] / total_excess
            st.session_state[f"share_{country}_{supplier}"] = round(supplier_min + proportional_extra, 1)

    # Final numerical correction without violating minimums.
    total = sum(float(st.session_state.get(f"share_{country}_{supplier}", 0.0)) for supplier in SUPPLIERS)
    correction = round(100.0 - total, 10)
    if abs(correction) > 1e-8:
        candidates = [
            supplier for supplier in SUPPLIERS
            if float(st.session_state.get(f"share_{country}_{supplier}", 0.0)) + correction >= minimums.get(supplier, 0.0) - 1e-8
        ]
        if not candidates:
            candidates = SUPPLIERS
        target_supplier = max(candidates, key=lambda supplier: st.session_state.get(f"share_{country}_{supplier}", 0.0))
        target_key = f"share_{country}_{target_supplier}"
        st.session_state[target_key] = round(
            min(100.0, max(minimums.get(target_supplier, 0.0), float(st.session_state.get(target_key, 0.0)) + correction)),
            1,
        )


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
    Build the current baseline using the same economic logic used for proposals.

    Gross view:
        Current Total Spend = Current Base Spend + Current Gross Financial Cost

    Working-capital economic view:
        Current Economic Total Spend = Current Base Spend
                                     + Current Gross Financial Cost
                                     - Current Capital Gain Offset

    This makes payment-term comparisons apples-to-apples when longer payment terms
    allow the company to keep cash invested for longer.
    """
    current_payment_days = int(financial_assumptions[country].get("current_payment_days", 0))
    financing_rate_pct = financial_assumptions[country]["financing_rate_pct"]
    financing_days = int(financial_assumptions[country]["financing_days"])
    investment_return_rate_pct = financial_assumptions[country].get("investment_return_rate_pct", financing_rate_pct)
    investment_return_days = int(financial_assumptions[country].get("investment_return_days", financing_days))

    current_financing_rate = equivalent_rate(
        financing_rate_pct,
        financing_days,
        current_payment_days,
        method,
    )
    current_investment_return_rate = equivalent_rate(
        investment_return_rate_pct,
        investment_return_days,
        current_payment_days,
        method,
    )

    wc = working_capital_net_effect(
        base_amount=current_spend,
        financing_rate=current_financing_rate,
        investment_return_rate=current_investment_return_rate,
    )

    return {
        "current_payment_days": current_payment_days,
        "current_financing_rate": current_financing_rate,
        "current_effective_financial_rate": safe_divide(wc["gross_financial_cost"], current_spend),
        "current_weighted_payment_days": current_payment_days,
        "current_return_rate": current_investment_return_rate,
        "current_effective_return_rate": safe_divide(wc["capital_gain_offset"], current_spend),
        "current_gross_financial_cost": wc["gross_financial_cost"],
        "current_capital_gain_offset": wc["capital_gain_offset"],
        "current_net_financial_impact": wc["net_financial_impact"],
        "current_adjusted_baseline": wc["economic_total"],
        "current_total_spend": wc["gross_total"],
        "current_economic_total_spend": wc["economic_total"],
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
    Computes country-level TCO for the proposed sourcing scenario.

    This model separates three layers:

    1. Base spend economics
       New Spend = weighted supplier proposal spend before any financial logic.

    2. Gross payment-term cost
       Gross Financial Cost = New Spend x supplier financing rate for the proposed term.

    3. Working-capital carry
       Capital Gain Offset = New Spend x treasury/investment return for the same payment term.

    Final economic decision metric:
       Economic Total = New Spend + Gross Financial Cost - Capital Gain Offset

    Cost delta convention: New - Current. Negative = saving / green; positive = impact / red.
    """
    baseline = compute_country_baseline(country, current_spend, financial_assumptions, method)

    rows = []
    gross_total = 0.0
    economic_total = 0.0
    proposal_before_finance_total = 0.0
    gross_financial_cost_total = 0.0
    capital_gain_offset_total = 0.0
    net_financial_impact_total = 0.0
    risk_weighted_sum = 0.0
    weighted_payment_days_sum = 0.0
    weighted_return_rate_sum = 0.0

    for supplier in SUPPLIERS:
        supplier_data = supplier_inputs[country][supplier]
        spend = supplier_data["spend"]
        payment_days = int(supplier_data["payment_days"])
        risk_score = supplier_data["risk_score"]
        share_pct = effective_shares[country][supplier]
        share = share_pct / 100.0

        country_financing_rate = financial_assumptions[country]["financing_rate_pct"]
        country_financing_days = int(financial_assumptions[country]["financing_days"])
        investment_return_rate_pct = financial_assumptions[country].get("investment_return_rate_pct", country_financing_rate)
        investment_return_days = int(financial_assumptions[country].get("investment_return_days", country_financing_days))

        supplier_financing_rate = equivalent_rate(country_financing_rate, country_financing_days, payment_days, method)
        investment_return_rate = equivalent_rate(investment_return_rate_pct, investment_return_days, payment_days, method)

        allocated_before_finance = spend * share
        wc = working_capital_net_effect(
            base_amount=allocated_before_finance,
            financing_rate=supplier_financing_rate,
            investment_return_rate=investment_return_rate,
        )

        gross_financial_cost = wc["gross_financial_cost"]
        capital_gain_offset = wc["capital_gain_offset"]
        net_financial_impact = wc["net_financial_impact"]
        gross_adjusted_spend = wc["gross_total"]
        economic_adjusted_spend = wc["economic_total"]

        proposal_before_finance_total += allocated_before_finance
        weighted_payment_days_sum += payment_days * allocated_before_finance
        weighted_return_rate_sum += investment_return_rate * allocated_before_finance
        gross_financial_cost_total += gross_financial_cost
        capital_gain_offset_total += capital_gain_offset
        net_financial_impact_total += net_financial_impact
        gross_total += gross_adjusted_spend
        economic_total += economic_adjusted_spend
        risk_weighted_sum += risk_score * max(economic_adjusted_spend, 0.0)

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
                "Adjusted Proposal Spend": gross_adjusted_spend,
                "Economic Adjusted Proposal Spend": economic_adjusted_spend,
                "Risk Score": risk_score,
                "Kraljic Minimum Required": supplier_data["kraljic_required"],
                "Minimum Share %": supplier_data["minimum_share"],
            }
        )

    gross_cost_delta = gross_total - baseline["current_total_spend"]
    spend_delta = proposal_before_finance_total - current_spend
    gross_financial_delta = gross_financial_cost_total - baseline["current_gross_financial_cost"]
    net_financial_delta = net_financial_impact_total - baseline["current_net_financial_impact"]
    economic_cost_delta = economic_total - baseline["current_economic_total_spend"]

    return {
        "country": country,
        "current_base_spend": current_spend,
        "current_payment_days": baseline["current_payment_days"],
        "current_weighted_payment_days": baseline["current_weighted_payment_days"],
        "current_effective_financial_rate": baseline["current_effective_financial_rate"],
        "current_effective_return_rate": baseline["current_effective_return_rate"],
        "new_weighted_payment_days": safe_divide(weighted_payment_days_sum, proposal_before_finance_total),
        "new_effective_financial_rate": safe_divide(gross_financial_cost_total, proposal_before_finance_total),
        "new_effective_return_rate": safe_divide(capital_gain_offset_total, proposal_before_finance_total),
        "current_gross_financial_cost": baseline["current_gross_financial_cost"],
        "current_capital_gain_offset": baseline["current_capital_gain_offset"],
        "current_net_financial_impact": baseline["current_net_financial_impact"],
        "current_adjusted_baseline": baseline["current_adjusted_baseline"],
        "current_total_spend": baseline["current_total_spend"],
        "current_economic_total_spend": baseline["current_economic_total_spend"],
        "proposal_before_finance": proposal_before_finance_total,
        "gross_financial_cost": gross_financial_cost_total,
        "capital_gain_offset": capital_gain_offset_total,
        "net_financial_impact": net_financial_impact_total,
        "net_financial_delta": net_financial_delta,
        "gross_financial_delta": gross_financial_delta,
        "spend_delta": spend_delta,
        "financial_delta": gross_financial_delta,
        "adjusted_proposal": gross_total,
        "gross_cost_delta": gross_cost_delta,
        "economic_adjusted_proposal": economic_total,
        "economic_cost_delta": economic_cost_delta,
        "cost_delta": economic_cost_delta,
        "cost_delta_pct": safe_divide(economic_cost_delta, baseline["current_economic_total_spend"]),
        "gross_cost_delta_pct": safe_divide(gross_cost_delta, baseline["current_total_spend"]),
        "spend_delta_pct": safe_divide(spend_delta, current_spend),
        "financial_delta_pct": safe_divide(gross_financial_delta, baseline["current_gross_financial_cost"]),
        "net_financial_delta_pct": safe_divide(net_financial_delta, baseline["current_net_financial_impact"]),
        "risk_score": safe_divide(risk_weighted_sum, economic_total) if economic_total else 0.0,
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
                "Current Weighted Payment Days": result["current_weighted_payment_days"],
                "New Weighted Payment Days": result["new_weighted_payment_days"],
                "Current Effective Financial Rate": result["current_effective_financial_rate"],
                "New Effective Financial Rate": result["new_effective_financial_rate"],
                "Current Effective Return Rate": result["current_effective_return_rate"],
                "New Effective Return Rate": result["new_effective_return_rate"],
                "Current Gross Financial Cost": result["current_gross_financial_cost"],
                "Current Capital Gain Offset": result["current_capital_gain_offset"],
                "Current Net Financial Impact": result["current_net_financial_impact"],
                "Current Adjusted Baseline": result["current_adjusted_baseline"],
                "Current Total Spend": result["current_total_spend"],
                "Current Economic Total Spend": result["current_economic_total_spend"],
                "Current Spend": result["current_base_spend"],
                "Proposal Before Finance": result["proposal_before_finance"],
                "New Spend": result["proposal_before_finance"],
                "Gross Financial Cost": result["gross_financial_cost"],
                "Capital Gain Offset": result["capital_gain_offset"],
                "Net Financial Impact": result["net_financial_impact"],
                "Net Financial Delta": result["net_financial_delta"],
                "Spend Saving / Impact": result["spend_delta"],
                "Gross Financial Saving / Impact": result["gross_financial_delta"],
                "Financial Saving / Impact": result["gross_financial_delta"],
                "Net Financial Saving / Impact": result["net_financial_delta"],
                "Adjusted Proposal": result["adjusted_proposal"],
                "New Total Spend": result["adjusted_proposal"],
                "Gross All In Saving / Impact": result["gross_cost_delta"],
                "Economic Adjusted Proposal": result["economic_adjusted_proposal"],
                "New Economic Total Spend": result["economic_adjusted_proposal"],
                "Economic Saving / Impact": result["economic_cost_delta"],
                "All In Saving / Impact": result["economic_cost_delta"],
                "Saving / Impact": result["economic_cost_delta"],
                "Saving / Impact %": result["cost_delta_pct"],
                "Gross Saving / Impact %": result["gross_cost_delta_pct"],
                "Spend Saving / Impact %": result["spend_delta_pct"],
                "Financial Saving / Impact %": result["financial_delta_pct"],
                "Net Financial Saving / Impact %": result["net_financial_delta_pct"],
                "Risk Score": result["risk_score"],
            }
        )
        detail_rows.extend(result["rows"])

    def aggregate_rows(rows: List[Dict[str, float]], region_name: str) -> Dict[str, float]:
        current_base = sum(row["Current Base Spend"] for row in rows)
        current_gross = sum(row["Current Gross Financial Cost"] for row in rows)
        current_offset = sum(row["Current Capital Gain Offset"] for row in rows)
        current_net = sum(row["Current Net Financial Impact"] for row in rows)
        current_total_spend = sum(row["Current Total Spend"] for row in rows)
        current_economic_total = sum(row["Current Economic Total Spend"] for row in rows)
        current_weighted_days = safe_divide(
            sum(row["Current Weighted Payment Days"] * row["Current Base Spend"] for row in rows),
            current_base,
        )

        new_spend = sum(row["New Spend"] for row in rows)
        new_gross = sum(row["Gross Financial Cost"] for row in rows)
        new_offset = sum(row["Capital Gain Offset"] for row in rows)
        new_net = sum(row["Net Financial Impact"] for row in rows)
        new_total_spend = sum(row["New Total Spend"] for row in rows)
        new_economic_total = sum(row["New Economic Total Spend"] for row in rows)
        new_weighted_days = safe_divide(
            sum(row["New Weighted Payment Days"] * row["New Spend"] for row in rows),
            new_spend,
        )

        current_effective_rate = safe_divide(current_gross, current_base)
        new_effective_rate = safe_divide(new_gross, new_spend)
        current_effective_return = safe_divide(current_offset, current_base)
        new_effective_return = safe_divide(new_offset, new_spend)

        spend_delta = new_spend - current_base
        gross_financial_delta = new_gross - current_gross
        net_financial_delta = new_net - current_net
        gross_all_in_delta = new_total_spend - current_total_spend
        economic_delta = new_economic_total - current_economic_total
        risk_weight = sum(row["Risk Score"] * row["New Economic Total Spend"] for row in rows)

        return {
            "Region": region_name,
            "Current Base Spend": current_base,
            "Current Payment Term Days": None,
            "Current Weighted Payment Days": current_weighted_days,
            "New Weighted Payment Days": new_weighted_days,
            "Current Effective Financial Rate": current_effective_rate,
            "New Effective Financial Rate": new_effective_rate,
            "Current Effective Return Rate": current_effective_return,
            "New Effective Return Rate": new_effective_return,
            "Current Gross Financial Cost": current_gross,
            "Current Capital Gain Offset": current_offset,
            "Current Net Financial Impact": current_net,
            "Current Adjusted Baseline": current_economic_total,
            "Current Total Spend": current_total_spend,
            "Current Economic Total Spend": current_economic_total,
            "Current Spend": current_base,
            "Proposal Before Finance": new_spend,
            "New Spend": new_spend,
            "Gross Financial Cost": new_gross,
            "Capital Gain Offset": new_offset,
            "Net Financial Impact": new_net,
            "Net Financial Delta": net_financial_delta,
            "Spend Saving / Impact": spend_delta,
            "Gross Financial Saving / Impact": gross_financial_delta,
            "Financial Saving / Impact": gross_financial_delta,
            "Net Financial Saving / Impact": net_financial_delta,
            "Adjusted Proposal": new_total_spend,
            "New Total Spend": new_total_spend,
            "Gross All In Saving / Impact": gross_all_in_delta,
            "Economic Adjusted Proposal": new_economic_total,
            "New Economic Total Spend": new_economic_total,
            "Economic Saving / Impact": economic_delta,
            "All In Saving / Impact": economic_delta,
            "Saving / Impact": economic_delta,
            "Saving / Impact %": safe_divide(economic_delta, current_economic_total),
            "Gross Saving / Impact %": safe_divide(gross_all_in_delta, current_total_spend),
            "Spend Saving / Impact %": safe_divide(spend_delta, current_base),
            "Financial Saving / Impact %": safe_divide(gross_financial_delta, current_gross),
            "Net Financial Saving / Impact %": safe_divide(net_financial_delta, current_net),
            "Risk Score": safe_divide(risk_weight, new_economic_total) if new_economic_total else 0.0,
        }

    brazil_row = next(row for row in country_results if row["Region"] == "Brazil")
    latam_row = aggregate_rows([row for row in country_results if row["Region"] in LATAM_COUNTRIES], "LATAM")
    total_row = aggregate_rows(country_results, "Total")

    executive_rows = [brazil_row, latam_row, total_row]

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
        "adjusted_proposal": result["economic_adjusted_proposal"],
        # Economic cost delta convention: negative = saving, positive = impact.
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
                y=chart_df["Current Economic Total Spend"],
                name="Current Economic Total",
                marker_color="#94a3b8",
                hovertemplate="Current Economic Total<br>" + currency + " %{y:,.2f}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Bar(
                x=chart_df["Region"],
                y=chart_df["New Economic Total Spend"],
                name="New Economic Total",
                marker_color="#2563eb",
                hovertemplate="New Economic Total<br>" + currency + " %{y:,.2f}<extra></extra>",
            )
        )
        fig.update_layout(
            title="Brazil and LATAM: Economic Total Spend after Working-Capital Carry",
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
        st.bar_chart(chart_df.set_index("Region")[["Current Economic Total Spend", "New Economic Total Spend"]])


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
                hovertemplate="%{x}<br>Economic Saving/Impact: " + currency + " %{y:,.2f}<br>Negative = saving<extra></extra>",
            )
        )
        fig.add_hline(y=0, line_dash="dash", line_color="#64748b")
        fig.update_layout(
            title="Economic Saving / Impact by Executive Region",
            height=410,
            margin=dict(l=20, r=20, t=55, b=30),
            yaxis_title=f"Economic Saving / Impact ({currency}) - negative = saving",
            plot_bgcolor="white",
            paper_bgcolor="white",
            showlegend=False,
        )
        apply_graphite_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.bar_chart(chart_df.set_index("Region")[["Saving / Impact"]])


def plot_supplier_mix(details_df: pd.DataFrame) -> None:
    mix_df = details_df.groupby("Supplier", as_index=False)["Economic Adjusted Proposal Spend"].sum()
    if PLOTLY_AVAILABLE:
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=mix_df["Supplier"],
                    values=mix_df["Economic Adjusted Proposal Spend"],
                    hole=0.55,
                    textinfo="label+percent",
                    textfont=dict(color=GRAPHITE),
                    hovertemplate="%{label}<br>%{value:,.2f}<extra></extra>",
                )
            ]
        )
        fig.update_layout(
            title="Economic Proposal Spend Mix by Supplier",
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
        options=[10, 5, 2, 1],
        index=1,
        help="1% is the most precise but slower. 5% is a good online default.",
    )
    st.markdown("---")
    st.caption("The optimizer is an embedded heuristic engine. It does not call any external API. It optimizes economic all-in cost after working-capital carry.")


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
        current_spend["Mexico"] = st.number_input("Mexico current spend", min_value=0.0, value=3_000_000.0, step=100_000.0, format="%.2f")
    with c3:
        current_spend["Argentina"] = st.number_input("Argentina current spend", min_value=0.0, value=2_500_000.0, step=100_000.0, format="%.2f")
    with c4:
        current_spend["Colombia"] = st.number_input("Colombia current spend", min_value=0.0, value=1_500_000.0, step=100_000.0, format="%.2f")

with input_tab_2:
    render_section_header(
        "Financial Assumptions by Country",
        "Each country has its own supplier financing reference rate, treasury return assumption and current payment term. The final economic view offsets supplier financing with working-capital carry.",
    )
    for country in COUNTRIES:
        st.markdown(f"**{country}**")
        fc1, fc2, fc3, fc4, fc5 = st.columns(5)
        default_financing_rate = {"Brazil": 15.00, "Mexico": 7.00, "Argentina": 35.00, "Colombia": 10.00}[country]
        default_return_rate = {"Brazil": 15.00, "Mexico": 7.00, "Argentina": 35.00, "Colombia": 10.00}[country]
        default_reference_days = 360
        default_current_payment_days = 360
        with fc1:
            financing_rate = st.number_input(
                f"{country} supplier financing rate (%)",
                min_value=0.0,
                value=float(default_financing_rate),
                step=0.05,
                format="%.4f",
                key=f"financing_rate_{country}",
                help="Reference financial rate used to calculate supplier payment-term cost.",
            )
        with fc2:
            financing_days = st.number_input(
                f"{country} supplier financing period days",
                min_value=1,
                value=int(default_reference_days),
                step=1,
                key=f"financing_days_{country}",
            )
        with fc3:
            investment_return_rate = st.number_input(
                f"{country} investment return rate (%)",
                min_value=0.0,
                value=float(default_return_rate),
                step=0.05,
                format="%.4f",
                key=f"investment_return_rate_{country}",
                help="Treasury/cash return earned while payment is deferred. This offsets supplier financing cost.",
            )
        with fc4:
            investment_return_days = st.number_input(
                f"{country} investment return period days",
                min_value=1,
                value=int(default_reference_days),
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
                help="Used to calculate current financial cost and current capital gain offset.",
            )
        financial_assumptions[country] = {
            "financing_rate_pct": financing_rate,
            "financing_days": financing_days,
            "investment_return_rate_pct": investment_return_rate,
            "investment_return_days": investment_return_days,
            "current_payment_days": current_payment_days,
        }
        st.caption(
            f"{country}: Net financial impact = supplier financing cost minus capital gain offset from keeping cash invested during the payment term."
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
            help="When one supplier share is changed, the other supplier shares are automatically rebalanced proportionally to keep the country total at 100% while respecting Kraljic minimum locks.",
        ):
            st.session_state["share_projection_mode"] = "Automatic"
    with mode_col_2:
        if st.button(
            "Manual",
            type="primary" if st.session_state["share_projection_mode"] == "Manual" else "secondary",
            use_container_width=True,
            help="Each supplier share can be moved independently. Kraljic minimum suppliers remain locked at their minimum floor.",
        ):
            st.session_state["share_projection_mode"] = "Manual"
    with mode_col_3:
        if st.session_state["share_projection_mode"] == "Automatic":
            st.info(
                "Automatic mode is active: change one supplier slider and the other shares will rebalance proportionally. "
                "Kraljic minimum shares are locked as slider floors. Supplier proposal fields remain controlled in Supplier Proposals."
            )
        else:
            st.warning(
                "Manual mode is active: sliders do not modify each other. Kraljic minimum shares are still locked as slider floors. "
                "If the visible total is not 100%, the model uses the normalized Effective Share % shown below."
            )

    for country in COUNTRIES:
        with st.expander(f"{country} share projection and risk", expanded=(country == "Brazil")):
            st.caption(
                "Projected shares drive the scenario calculation in real time. Supplier expected spend and payment terms remain editable in the Supplier Proposals tab."
            )

            # Kraljic controls must be rendered before share sliders so the selected
            # minimum can be pushed into the slider floor in the same run.
            st.markdown("**Kraljic Minimum and Risk Controls**")
            for supplier in SUPPLIERS:
                ac1, ac2, ac3 = st.columns([1.25, 1, 1])
                with ac1:
                    kraljic_required = st.checkbox(
                        f"{supplier} | Kraljic minimum required",
                        value=False,
                        key=f"kraljic_{country}_{supplier}",
                        help="When selected, this supplier's Share Projection slider is automatically locked at or above the minimum share.",
                    )
                with ac2:
                    min_share = st.number_input(
                        f"{supplier} | Minimum share %",
                        min_value=0.0,
                        max_value=100.0,
                        value=20.0,
                        step=1.0,
                        key=f"min_{country}_{supplier}",
                        disabled=not kraljic_required,
                        help="This value becomes the minimum selectable value in the supplier share slider when Kraljic minimum is required.",
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
            else:
                # Lock the slider state at or above the selected Kraljic minimums
                # before Streamlit creates the slider widgets.
                enforce_kraljic_minimums_on_slider_state(country, minimums[country])

            st.markdown("**Share Projection**")
            st.caption("Kraljic-selected suppliers cannot be moved below their minimum share floor.")
            share_cols = st.columns(4)
            for idx_supplier, supplier in enumerate(SUPPLIERS):
                share_key = f"share_{country}_{supplier}"
                supplier_minimum = 0.0 if total_min > 100.0 else float(minimums[country].get(supplier, 0.0))
                with share_cols[idx_supplier]:
                    if st.session_state["share_projection_mode"] == "Automatic":
                        st.slider(
                            supplier,
                            min_value=supplier_minimum,
                            max_value=100.0,
                            step=0.1,
                            key=share_key,
                            on_change=auto_adjust_supplier_share,
                            args=(country, supplier),
                            help=(
                                f"Automatic mode: changing this supplier rebalances the others proportionally. "
                                f"Kraljic minimum floor: {supplier_minimum:.1f}%."
                            ),
                        )
                    else:
                        st.slider(
                            supplier,
                            min_value=supplier_minimum,
                            max_value=100.0,
                            step=0.1,
                            key=share_key,
                            help=(
                                f"Manual mode: this supplier can be moved independently, but not below its Kraljic floor. "
                                f"Kraljic minimum floor: {supplier_minimum:.1f}%."
                            ),
                        )

            raw_shares[country] = get_slider_share_values(country)
            visible_total = sum(raw_shares[country].values())

            if st.session_state["share_projection_mode"] == "Manual" and abs(visible_total - 100.0) > 0.01:
                st.caption(
                    f"Visible manual share total: {visible_total:.1f}%. The calculation will use normalized Effective Share % to keep the scenario at 100%."
                )
            else:
                st.caption(f"Visible share total: {visible_total:.1f}%")

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
    "Decision-ready view with spend, financial cost, all-in total, risk, and Brazil/LATAM breakdown.",
)

# Row 1 - same-line executive cost stack requested by Procurement.
st.markdown("**Total cost stack**")
t1, t2, t3, t4, t5, t6 = st.columns(6)
with t1:
    render_kpi_card(
        "Current Spend",
        format_money(total_row["Current Base Spend"], currency_symbol, True),
        "Without financial cost",
        "neutral",
        compact=True,
    )
with t2:
    render_kpi_card(
        "New Spend",
        format_money(total_row["New Spend"], currency_symbol, True),
        "Without financial cost",
        "neutral",
        compact=True,
    )
with t3:
    render_kpi_card(
        "Current Financial Cost",
        format_money(total_row["Current Gross Financial Cost"], currency_symbol, True),
        f"Effective rate {format_percent(total_row['Current Effective Financial Rate'])} | Avg {total_row['Current Weighted Payment Days']:.0f} days",
        "neutral",
        compact=True,
    )
with t4:
    render_kpi_card(
        "New Financial Cost",
        format_money(total_row["Gross Financial Cost"], currency_symbol, True),
        f"Effective rate {format_percent(total_row['New Effective Financial Rate'])} | Avg {total_row['New Weighted Payment Days']:.0f} days",
        "neutral",
        compact=True,
    )
with t5:
    render_kpi_card(
        "Current Total Spend",
        format_money(total_row["Current Total Spend"], currency_symbol, True),
        "Current spend + current financial cost",
        "neutral",
        compact=True,
    )
with t6:
    render_kpi_card(
        "New Total Spend",
        format_money(total_row["New Total Spend"], currency_symbol, True),
        "New spend + new financial cost",
        "neutral",
        compact=True,
    )

st.caption(
    "Gross financial-cost audit: Current Financial Cost uses current payment terms by country. "
    "New Financial Cost uses each supplier proposal payment term and country financing rate. "
    "The economic decision view below also subtracts the capital-gain offset earned while cash remains invested."
)

st.markdown('<div class="executive-row-spacer"></div>', unsafe_allow_html=True)

# Row 2 - working-capital economics.
st.markdown("**Working capital economic view**")
wc1, wc2, wc3, wc4, wc5, wc6 = st.columns(6)
with wc1:
    render_kpi_card(
        "Current Capital Gain",
        format_money(total_row["Current Capital Gain Offset"], currency_symbol, True),
        f"Return offset | {format_percent(total_row['Current Effective Return Rate'])}",
        "good",
        compact=True,
    )
with wc2:
    render_kpi_card(
        "New Capital Gain",
        format_money(total_row["Capital Gain Offset"], currency_symbol, True),
        f"Return offset | {format_percent(total_row['New Effective Return Rate'])}",
        "good",
        compact=True,
    )
with wc3:
    render_kpi_card(
        "Current Economic Total",
        format_money(total_row["Current Economic Total Spend"], currency_symbol, True),
        "Current spend + net financial impact",
        "neutral",
        compact=True,
    )
with wc4:
    render_kpi_card(
        "New Economic Total",
        format_money(total_row["New Economic Total Spend"], currency_symbol, True),
        "New spend + net financial impact",
        "neutral",
        compact=True,
    )
with wc5:
    render_kpi_card(
        "Net Financial Saving/Impact",
        format_delta(total_row["Net Financial Saving / Impact"], currency_symbol, True),
        "New net financial impact - current net financial impact",
        delta_tone(total_row["Net Financial Saving / Impact"]),
        compact=True,
    )
with wc6:
    render_kpi_card(
        "Economic All In",
        format_delta(total_row["Economic Saving / Impact"], currency_symbol, True),
        "New economic total - current economic total",
        delta_tone(total_row["Economic Saving / Impact"]),
        compact=True,
    )

st.markdown('<div class="executive-row-spacer"></div>', unsafe_allow_html=True)

# Row 3 - total savings/impact decomposition.
st.markdown("**Total saving / impact decomposition**")
d1, d2, d3, d4 = st.columns(4)
with d1:
    render_kpi_card(
        "Spend Saving/Impact",
        format_delta(total_row["Spend Saving / Impact"], currency_symbol, True),
        "New spend - current spend | negative = saving",
        delta_tone(total_row["Spend Saving / Impact"]),
        compact=True,
    )
with d2:
    render_kpi_card(
        "Gross Financial Saving/Impact",
        format_delta(total_row["Gross Financial Saving / Impact"], currency_symbol, True),
        "New gross financial cost - current gross financial cost",
        delta_tone(total_row["Gross Financial Saving / Impact"]),
        compact=True,
    )
with d3:
    render_kpi_card(
        "Economic All In Saving/Impact",
        format_delta(total_row["Economic Saving / Impact"], currency_symbol, True),
        "New economic total - current economic total",
        delta_tone(total_row["Economic Saving / Impact"]),
        compact=True,
    )
with d4:
    render_kpi_card(
        "Weighted Risk",
        f"{total_row['Risk Score']:.2f}/5",
        "Lower is better",
        "neutral",
        compact=True,
    )

st.markdown('<div class="executive-row-spacer"></div>', unsafe_allow_html=True)

# Row 3 - Brazil result.
st.markdown("**Brazil result**")
br1, br2, br3 = st.columns(3)
with br1:
    render_kpi_card(
        "Spend Saving/Impact",
        format_delta(brazil_row["Spend Saving / Impact"], currency_symbol, True),
        "New spend - current spend",
        delta_tone(brazil_row["Spend Saving / Impact"]),
        compact=True,
    )
with br2:
    render_kpi_card(
        "Gross Financial Saving/Impact",
        format_delta(brazil_row["Gross Financial Saving / Impact"], currency_symbol, True),
        "New gross financial cost - current gross financial cost",
        delta_tone(brazil_row["Gross Financial Saving / Impact"]),
        compact=True,
    )
with br3:
    render_kpi_card(
        "Economic All In Saving/Impact",
        format_delta(brazil_row["Economic Saving / Impact"], currency_symbol, True),
        "New economic total - current economic total",
        delta_tone(brazil_row["Economic Saving / Impact"]),
        compact=True,
    )

st.markdown('<div class="executive-row-spacer"></div>', unsafe_allow_html=True)

# Row 4 - LATAM result.
st.markdown("**LATAM result**")
la1, la2, la3 = st.columns(3)
with la1:
    render_kpi_card(
        "Spend Saving/Impact",
        format_delta(latam_row["Spend Saving / Impact"], currency_symbol, True),
        "New spend - current spend",
        delta_tone(latam_row["Spend Saving / Impact"]),
        compact=True,
    )
with la2:
    render_kpi_card(
        "Gross Financial Saving/Impact",
        format_delta(latam_row["Gross Financial Saving / Impact"], currency_symbol, True),
        "New gross financial cost - current gross financial cost",
        delta_tone(latam_row["Gross Financial Saving / Impact"]),
        compact=True,
    )
with la3:
    render_kpi_card(
        "Economic All In Saving/Impact",
        format_delta(latam_row["Economic Saving / Impact"], currency_symbol, True),
        "New economic total - current economic total",
        delta_tone(latam_row["Economic Saving / Impact"]),
        compact=True,
    )

if is_saving:
    st.markdown(
        f"""
        <div class="decision-card decision-good">
            <div class="decision-title">Recommended scenario is financially attractive under the current allocation</div>
            <div class="decision-body">
                The new economic total spend is below the current economic baseline by
                <b>{format_delta(total_row['Saving / Impact'], currency_symbol)}</b>, equivalent to
                <b>{format_percent(abs(total_row['Saving / Impact %']))}</b> economic all-in, with a weighted risk score of
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
                The new economic total spend is above the current economic baseline by
                <b>{format_delta(total_row['Saving / Impact'], currency_symbol)}</b>, equivalent to
                <b>{format_percent(abs(total_row['Saving / Impact %']))}</b> economic all-in. Use Cost Optimization to search for a better cost x risk allocation.
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
# Current Spend alias is only used for charts; keep the breakdown focused on current base spend.
if "Current Spend" in display_summary.columns:
    display_summary = display_summary.drop(columns=["Current Spend"])
ordered_summary_columns = [
    "Region",
    "Current Base Spend",
    "New Spend",
    "Current Gross Financial Cost",
    "Gross Financial Cost",
    "Current Capital Gain Offset",
    "Capital Gain Offset",
    "Current Net Financial Impact",
    "Net Financial Impact",
    "Current Total Spend",
    "New Total Spend",
    "Current Economic Total Spend",
    "New Economic Total Spend",
    "Spend Saving / Impact",
    "Gross Financial Saving / Impact",
    "Net Financial Saving / Impact",
    "Gross All In Saving / Impact",
    "Economic Saving / Impact",
    "Saving / Impact %",
    "Risk Score",
]
display_summary = display_summary[[col for col in ordered_summary_columns if col in display_summary.columns]]
display_summary = display_summary.rename(columns={
    "Current Base Spend": "Current Spend",
    "New Spend": "New Spend",
    "Current Gross Financial Cost": "Current Gross Financial Cost",
    "Gross Financial Cost": "New Gross Financial Cost",
    "Current Capital Gain Offset": "Current Capital Gain",
    "Capital Gain Offset": "New Capital Gain",
    "Current Net Financial Impact": "Current Net Financial Impact",
    "Net Financial Impact": "New Net Financial Impact",
    "Current Total Spend": "Current Gross Total Spend",
    "New Total Spend": "New Gross Total Spend",
    "Current Economic Total Spend": "Current Economic Total Spend",
    "New Economic Total Spend": "New Economic Total Spend",
})
for column in [
    "Current Spend",
    "New Spend",
    "Current Gross Financial Cost",
    "New Gross Financial Cost",
    "Current Capital Gain",
    "New Capital Gain",
    "Current Net Financial Impact",
    "New Net Financial Impact",
    "Current Gross Total Spend",
    "New Gross Total Spend",
    "Current Economic Total Spend",
    "New Economic Total Spend",
]:
    if column in display_summary.columns:
        display_summary[column] = display_summary[column].map(lambda x: format_money(x, currency_symbol))
for column in ["Spend Saving / Impact", "Gross Financial Saving / Impact", "Net Financial Saving / Impact", "Gross All In Saving / Impact", "Economic Saving / Impact"]:
    if column in display_summary.columns:
        display_summary[column] = display_summary[column].map(lambda x: format_delta(x, currency_symbol))
if "Saving / Impact %" in display_summary.columns:
    display_summary["Saving / Impact %"] = display_summary["Saving / Impact %"].map(format_percent)
if "Risk Score" in display_summary.columns:
    display_summary["Risk Score"] = display_summary["Risk Score"].map(lambda x: f"{x:.2f}/5")
st.dataframe(display_summary, use_container_width=True)

with st.expander("Supplier-level proposal details"):
    display_details = details_df.copy()
    for money_col in ["Proposal Spend", "Allocated Spend Before Finance", "Gross Financial Cost", "Capital Gain Offset", "Net Financial Impact", "Adjusted Proposal Spend", "Economic Adjusted Proposal Spend"]:
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
    "Searches the best allocation considering supplier proposal cost, payment-term financing, working-capital carry, Kraljic minimum shares and weighted risk score.",
)

opt_col1, opt_col2 = st.columns([1, 3])
with opt_col1:
    run_optimizer = st.button("Cost Optimization", type="primary", use_container_width=True)
with opt_col2:
    st.markdown(
        """
        <div class="small-note">
        Optimization objective: minimize economic all-in cost delta versus current economic baseline while respecting Kraljic minimum requirements. Negative cost delta = saving.
        The optimizer considers gross supplier financing, treasury capital-gain offset, payment terms and risk. This is an embedded heuristic optimizer, not an external API call.
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
        opt_display = opt_display.rename(columns={
            "Current Base Spend": "Current Spend",
            "New Spend": "New Spend",
            "Current Gross Financial Cost": "Current Gross Financial Cost",
            "Gross Financial Cost": "New Gross Financial Cost",
            "Current Capital Gain Offset": "Current Capital Gain",
            "Capital Gain Offset": "New Capital Gain",
            "Current Net Financial Impact": "Current Net Financial Impact",
            "Net Financial Impact": "New Net Financial Impact",
            "Current Total Spend": "Current Gross Total Spend",
            "New Total Spend": "New Gross Total Spend",
        })
        for column in [
            "Current Spend",
            "New Spend",
            "Current Gross Financial Cost",
            "New Gross Financial Cost",
            "Current Capital Gain",
            "New Capital Gain",
            "Current Net Financial Impact",
            "New Net Financial Impact",
            "Current Gross Total Spend",
            "New Gross Total Spend",
            "Current Economic Total Spend",
            "New Economic Total Spend",
        ]:
            if column in opt_display.columns:
                opt_display[column] = opt_display[column].map(lambda x: format_money(x, currency_symbol))
        for column in ["Spend Saving / Impact", "Gross Financial Saving / Impact", "Net Financial Saving / Impact", "Gross All In Saving / Impact", "Economic Saving / Impact"]:
            if column in opt_display.columns:
                opt_display[column] = opt_display[column].map(lambda x: format_delta(x, currency_symbol))
        if "Saving / Impact %" in opt_display.columns:
            opt_display["Saving / Impact %"] = opt_display["Saving / Impact %"].map(format_percent)
        if "Risk Score" in opt_display.columns:
            opt_display["Risk Score"] = opt_display["Risk Score"].map(lambda x: f"{x:.2f}/5")
        st.markdown("**Optimized executive summary**")
        st.dataframe(opt_display, use_container_width=True)
    with o2:
        allocation_view = optimized_details[["Country", "Supplier", "Effective Share %", "Economic Adjusted Proposal Spend", "Risk Score"]].copy()
        allocation_view["Effective Share %"] = allocation_view["Effective Share %"].map(lambda x: f"{x:.1f}%")
        allocation_view["Economic Adjusted Proposal Spend"] = allocation_view["Economic Adjusted Proposal Spend"].map(lambda x: format_money(x, currency_symbol))
        allocation_view["Risk Score"] = allocation_view["Risk Score"].map(lambda x: f"{x:.1f}/5")
        st.markdown("**Optimized supplier allocation now applied**")
        st.dataframe(allocation_view, use_container_width=True)

    st.markdown(
        f"""
        <div class="insight-box">
            <b>Automatic optimization reading</b><br><br>
            The optimizer searched allocation combinations in {optimization_step}% increments by country, respected all Kraljic minimum-share constraints,
            calculated gross financial cost and capital-gain offset for current and new terms,
            and selected the allocation with the lowest economic all-in cost delta versus the current economic baseline. Risk was used as the tie-breaker.
            <br><br>
            Best economic new total spend now active: <b>{format_money(optimized_total['New Economic Total Spend'], currency_symbol)}</b><br>
            Best all-in saving/impact now active: <b>{format_delta(optimized_total['Saving / Impact'], currency_symbol)}</b><br>
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
