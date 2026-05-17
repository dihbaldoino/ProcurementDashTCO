"""
Executive Procurement TCO & Should-Cost Dashboard
Version v15 - Senior Director Edition

Run:
    pip install -r requirements.txt
    streamlit run app.py

This dashboard compares current spend vs. supplier proposals using:
- commercial spend
- payment-term supplier financial cost
- treasury/working-capital carry benefit
- inventory carrying cost
- supplier risk and Kraljic minimum shares
- automatic cost x risk allocation optimization
"""

from __future__ import annotations

from itertools import product
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import streamlit as st

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except Exception:
    go = None
    PLOTLY_AVAILABLE = False

# =============================================================================
# Constants and defaults
# =============================================================================

COUNTRIES = ["Brazil", "Mexico", "Argentina", "Colombia"]
LATAM_COUNTRIES = ["Mexico", "Argentina", "Colombia"]
SUPPLIERS = [
    "ChemPrime",
    "OleoGlobal",
    "Oleo Overseas Trading Co.",
    "Comercio de Oleos Nacional Distribuicao",
]
SHORT_SUPPLIER = {
    "ChemPrime": "ChemPrime",
    "OleoGlobal": "OleoGlobal",
    "Oleo Overseas Trading Co.": "Overseas",
    "Comercio de Oleos Nacional Distribuicao": "Distribuicao",
}

DEFAULT_CURRENT_SPEND = {
    "Brazil": 13_000_000.0,
    "Mexico": 3_000_000.0,
    "Argentina": 2_500_000.0,
    "Colombia": 1_500_000.0,
}
DEFAULT_FINANCIAL_RATE = {
    "Brazil": 4.84,
    "Mexico": 2.32,
    "Argentina": 10.52,
    "Colombia": 3.07,
}
DEFAULT_REFERENCE_DAYS = {country: 120 for country in COUNTRIES}
DEFAULT_CURRENT_TERM = {
    "Brazil": 120,
    "Mexico": 60,
    "Argentina": 60,
    "Colombia": 60,
}
DEFAULT_TREASURY_RETURN = {
    "Brazil": 5.07,
    "Mexico": 2.50,
    "Argentina": 10.90,
    "Colombia": 3.40,
}
DEFAULT_TREASURY_REF_DAYS = {country: 120 for country in COUNTRIES}
DEFAULT_INVENTORY_CARRY_RATE = {
    "Brazil": 23.0,
    "Mexico": 15.0,
    "Argentina": 35.0,
    "Colombia": 22.0,
}
DEFAULT_CURRENT_INVENTORY_DAYS = {country: 30 for country in COUNTRIES}

# Validation example shared by the user.
DEFAULT_PROPOSAL_SPEND = {'Argentina': {'ChemPrime': 3125000.0,
               'Comercio de Oleos Nacional Distribuicao': 2316250.0,
               'Oleo Overseas Trading Co.': 2231250.0,
               'OleoGlobal': 2125000.0},
 'Brazil': {'ChemPrime': 16250000.0,
            'Comercio de Oleos Nacional Distribuicao': 12044500.0,
            'Oleo Overseas Trading Co.': 11602500.0,
            'OleoGlobal': 11050000.0},
 'Colombia': {'ChemPrime': 1875000.0,
              'Comercio de Oleos Nacional Distribuicao': 1389750.0,
              'Oleo Overseas Trading Co.': 1338750.0,
              'OleoGlobal': 1275000.0},
 'Mexico': {'ChemPrime': 3750000.0,
            'Comercio de Oleos Nacional Distribuicao': 2779500.0,
            'Oleo Overseas Trading Co.': 2677500.0,
            'OleoGlobal': 2550000.0}}
DEFAULT_PAYMENT_TERM = {
    country: {
        "ChemPrime": 90,
        "OleoGlobal": 70,
        "Oleo Overseas Trading Co.": 150,
        "Comercio de Oleos Nacional Distribuicao": 120,
    }
    for country in COUNTRIES
}
DEFAULT_LEAD_TIME_DAYS = {
    country: {
        "ChemPrime": 30,
        "OleoGlobal": 120,
        "Oleo Overseas Trading Co.": 120,
        "Comercio de Oleos Nacional Distribuicao": 30,
    }
    for country in COUNTRIES
}
DEFAULT_SAFETY_STOCK_DAYS = {
    country: {
        "ChemPrime": 0,
        "OleoGlobal": 0,
        "Oleo Overseas Trading Co.": 0,
        "Comercio de Oleos Nacional Distribuicao": 0,
    }
    for country in COUNTRIES
}
DEFAULT_SHARES = {
    country: {
        "ChemPrime": 40.0,
        "OleoGlobal": 0.0,
        "Oleo Overseas Trading Co.": 40.0,
        "Comercio de Oleos Nacional Distribuicao": 20.0,
    }
    for country in COUNTRIES
}
DEFAULT_KRALJIC_REQUIRED = {
    "ChemPrime": True,
    "OleoGlobal": False,
    "Oleo Overseas Trading Co.": False,
    "Comercio de Oleos Nacional Distribuicao": False,
}
DEFAULT_MIN_SHARE = {
    "ChemPrime": 40.0,
    "OleoGlobal": 0.0,
    "Oleo Overseas Trading Co.": 0.0,
    "Comercio de Oleos Nacional Distribuicao": 0.0,
}
DEFAULT_MAX_SHARE = {
    "ChemPrime": 100.0,
    "OleoGlobal": 100.0,
    "Oleo Overseas Trading Co.": 100.0,
    "Comercio de Oleos Nacional Distribuicao": 100.0,
}
DEFAULT_APPROVED = {supplier: True for supplier in SUPPLIERS}
DEFAULT_RISK = {
    "ChemPrime": {
        "Supply": 2.0,
        "Quality": 2.0,
        "Financial": 2.0,
        "Compliance": 1.5,
        "ESG": 2.0,
        "Logistics": 2.0,
    },
    "OleoGlobal": {
        "Supply": 3.0,
        "Quality": 2.5,
        "Financial": 2.5,
        "Compliance": 2.0,
        "ESG": 2.5,
        "Logistics": 2.5,
    },
    "Oleo Overseas Trading Co.": {
        "Supply": 4.0,
        "Quality": 3.0,
        "Financial": 3.5,
        "Compliance": 3.0,
        "ESG": 3.0,
        "Logistics": 4.5,
    },
    "Comercio de Oleos Nacional Distribuicao": {
        "Supply": 3.0,
        "Quality": 2.5,
        "Financial": 2.5,
        "Compliance": 2.0,
        "ESG": 2.5,
        "Logistics": 2.5,
    },
}
DEFAULT_RISK_WEIGHTS = {
    "Supply": 30.0,
    "Quality": 20.0,
    "Financial": 15.0,
    "Compliance": 15.0,
    "ESG": 10.0,
    "Logistics": 10.0,
}

GRAPHITE = "#1f2937"
GREEN = "#047857"
RED = "#b91c1c"
BLUE = "#1d4ed8"
AMBER = "#b45309"

# =============================================================================
# Page setup and CSS
# =============================================================================

st.set_page_config(
    page_title="Executive Procurement TCO Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .block-container {padding-top: 1.2rem; padding-bottom: 2.2rem; max-width: 1600px;}
        .executive-hero {
            background: linear-gradient(135deg, #020617 0%, #0f172a 48%, #1d4ed8 100%);
            padding: 30px 34px; border-radius: 28px; color: white; margin-bottom: 22px;
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.25);
        }
        .executive-hero h1 {font-size: 2.25rem; line-height: 1.1; margin-bottom: 0.35rem; font-weight: 850; color: #ffffff;}
        .executive-hero p {font-size: 1rem; color: rgba(255,255,255,0.88); margin-bottom: 0; max-width: 1140px;}
        .section-header {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            border: 1px solid rgba(148, 163, 184, 0.25); border-radius: 18px;
            padding: 14px 18px; margin-top: 10px; margin-bottom: 14px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
        }
        .section-title {font-size: 1.12rem; font-weight: 850; color: #bfdbfe; margin-bottom: 3px;}
        .section-subtitle {font-size: 0.90rem; color: #e2e8f0; margin-bottom: 0;}
        .plain-title {font-size: 1.05rem; font-weight: 850; color: #f8fafc; margin-top: 10px; margin-bottom: 9px;}
        .kpi-card {
            background: #ffffff; border: 1px solid rgba(148, 163, 184, 0.26); border-radius: 22px;
            padding: 20px 22px; min-height: 165px; height: 165px; box-sizing: border-box;
            margin-bottom: 22px; box-shadow: 0 10px 28px rgba(15, 23, 42, 0.07);
            display: flex; flex-direction: column; justify-content: flex-start;
        }
        .kpi-card.short {min-height: 145px; height: 145px;}
        .kpi-label {color: #64748b; font-size: 0.76rem; font-weight: 850; text-transform: uppercase; letter-spacing: 0.055em; margin-bottom: 8px;}
        .kpi-value {color: #0f172a; font-size: 1.50rem; font-weight: 850; line-height: 1.1; margin-bottom: 9px;}
        .kpi-helper {color: #64748b; font-size: 0.80rem; line-height: 1.28;}
        .good {color: #047857 !important;} .bad {color: #b91c1c !important;} .neutral {color: #1d4ed8 !important;} .amber {color: #b45309 !important;}
        .decision-card {border-radius: 24px; padding: 22px 26px; margin: 14px 0 20px 0; box-shadow: 0 12px 35px rgba(15, 23, 42, 0.08);}
        .decision-good {background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%); border: 1px solid #a7f3d0;}
        .decision-bad {background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%); border: 1px solid #fecaca;}
        .decision-title {font-size: 1.25rem; font-weight: 850; color: #0f172a; margin-bottom: 5px;}
        .decision-body {font-size: 0.98rem; color: #334155; line-height: 1.45;}
        .insight-box {background: white; border: 1px solid rgba(148, 163, 184, 0.25); border-left: 5px solid #2563eb; border-radius: 18px; padding: 18px 20px; color: #334155; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06); min-height: 165px;}
        .small-note {font-size: 0.82rem; color: #64748b; margin-top: 8px;}
        .pill {display:inline-block; padding: 5px 10px; border-radius: 999px; background:#eff6ff; color:#1d4ed8; font-weight:700; font-size:0.78rem;}
        .supplier-box {border:1px solid rgba(148,163,184,.28); border-radius:18px; padding:14px; background:#ffffff; margin-bottom:12px;}
    </style>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# Utility functions
# =============================================================================

def safe_divide(numerator: float, denominator: float) -> float:
    return 0.0 if abs(denominator) < 1e-12 else numerator / denominator


def format_money(value: float, currency: str = "USD", compact: bool = False, signed: bool = False) -> str:
    value = float(value)
    sign = ""
    if signed:
        sign = "+" if value > 0 else "-" if value < 0 else ""
    elif value < 0:
        sign = "-"
    v = abs(value)
    if compact:
        if v >= 1_000_000_000:
            return f"{sign}{currency} {v / 1_000_000_000:,.2f}B"
        if v >= 1_000_000:
            return f"{sign}{currency} {v / 1_000_000:,.2f}M"
        if v >= 1_000:
            return f"{sign}{currency} {v / 1_000:,.2f}K"
    return f"{sign}{currency} {v:,.2f}"


def format_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def equivalent_rate(rate_pct: float, reference_days: int, target_days: int, method: str = "Compound") -> float:
    if reference_days <= 0 or target_days <= 0:
        return 0.0
    rate = rate_pct / 100.0
    if method == "Linear":
        return rate * (target_days / reference_days)
    return (1 + rate) ** (target_days / reference_days) - 1


def apply_chart_theme(fig):
    if fig is None:
        return fig
    fig.update_layout(
        font=dict(color=GRAPHITE),
        title_font=dict(color=GRAPHITE, size=18),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=20, r=20, t=55, b=35),
        xaxis=dict(title_font=dict(color=GRAPHITE), tickfont=dict(color=GRAPHITE), color=GRAPHITE, gridcolor="rgba(31,41,55,.12)"),
        yaxis=dict(title_font=dict(color=GRAPHITE), tickfont=dict(color=GRAPHITE), color=GRAPHITE, gridcolor="rgba(31,41,55,.12)"),
        legend=dict(font=dict(color=GRAPHITE)),
    )
    for tr in fig.data:
        if hasattr(tr, "textfont"):
            tr.textfont = dict(color=GRAPHITE)
        if hasattr(tr, "insidetextfont"):
            tr.insidetextfont = dict(color=GRAPHITE)
        if hasattr(tr, "outsidetextfont"):
            tr.outsidetextfont = dict(color=GRAPHITE)
    return fig


def render_section(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="section-header">
            <div class="section-title">{title}</div>
            <div class="section-subtitle">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi(label: str, value: str, helper: str = "", tone: str = "neutral", short: bool = False) -> None:
    cls = {"good": "good", "bad": "bad", "neutral": "neutral", "amber": "amber"}.get(tone, "neutral")
    card_cls = "kpi-card short" if short else "kpi-card"
    st.markdown(
        f"""
        <div class="{card_cls}">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value {cls}">{value}</div>
            <div class="kpi-helper">{helper}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def delta_tone(delta: float) -> str:
    # Procurement convention: negative delta = saving = green. Positive delta = impact = red.
    if delta < -1e-9:
        return "good"
    if delta > 1e-9:
        return "bad"
    return "neutral"


def risk_tone(risk: float) -> str:
    if risk <= 2.5:
        return "good"
    if risk <= 3.5:
        return "amber"
    return "bad"

# =============================================================================
# Share allocation helpers
# =============================================================================

def share_key(country: str, supplier: str) -> str:
    return f"share__{country}__{supplier}"


def min_key(supplier: str) -> str:
    return f"min_share__{supplier}"


def max_key(supplier: str) -> str:
    return f"max_share__{supplier}"


def kraljic_key(supplier: str) -> str:
    return f"kraljic_required__{supplier}"


def approved_key(supplier: str) -> str:
    return f"approved__{supplier}"


def get_min_shares() -> Dict[str, float]:
    mins = {}
    for supplier in SUPPLIERS:
        required = bool(st.session_state.get(kraljic_key(supplier), DEFAULT_KRALJIC_REQUIRED[supplier]))
        mins[supplier] = float(st.session_state.get(min_key(supplier), DEFAULT_MIN_SHARE[supplier])) if required else 0.0
    return mins


def get_max_shares() -> Dict[str, float]:
    maxs = {}
    for supplier in SUPPLIERS:
        approved = bool(st.session_state.get(approved_key(supplier), DEFAULT_APPROVED[supplier]))
        required = bool(st.session_state.get(kraljic_key(supplier), DEFAULT_KRALJIC_REQUIRED[supplier]))
        min_required = float(st.session_state.get(min_key(supplier), DEFAULT_MIN_SHARE[supplier])) if required else 0.0
        raw_max = float(st.session_state.get(max_key(supplier), DEFAULT_MAX_SHARE[supplier])) if approved else 0.0

        # Streamlit sliders cannot be rendered with max < min.
        # Business rule: if a Kraljic minimum is required, that strategic floor overrides
        # a conflicting max/capacity input for UI stability and model feasibility.
        maxs[supplier] = max(raw_max, min_required)
    return maxs


def clamp_shares_to_bounds(country: str) -> None:
    mins = get_min_shares()
    maxs = get_max_shares()
    for supplier in SUPPLIERS:
        k = share_key(country, supplier)
        if k not in st.session_state:
            st.session_state[k] = DEFAULT_SHARES[country][supplier]
        st.session_state[k] = max(mins[supplier], min(maxs[supplier], float(st.session_state[k])))


def allocate_with_bounds(preferences: Dict[str, float], mins: Dict[str, float], maxs: Dict[str, float], total: float = 100.0) -> Dict[str, float]:
    """Project preferences to shares that sum to total while respecting min/max bounds."""
    if sum(mins.values()) > total + 1e-9:
        return mins.copy()
    if sum(maxs.values()) < total - 1e-9:
        # Impossible to reach 100 under max constraints. Return capped and let UI show warning.
        return maxs.copy()

    shares = {s: mins[s] for s in SUPPLIERS}
    remaining = total - sum(shares.values())
    capacity = {s: max(0.0, maxs[s] - mins[s]) for s in SUPPLIERS}

    pref_excess = {s: max(0.0, preferences.get(s, 0.0) - mins[s]) for s in SUPPLIERS}
    if sum(pref_excess.values()) <= 1e-9:
        pref_excess = capacity.copy()

    active = {s for s in SUPPLIERS if capacity[s] > 1e-9}
    while remaining > 1e-8 and active:
        denom = sum(pref_excess[s] for s in active)
        if denom <= 1e-9:
            denom = sum(capacity[s] for s in active)
            weights = {s: capacity[s] / denom if denom else 0.0 for s in active}
        else:
            weights = {s: pref_excess[s] / denom for s in active}

        moved = 0.0
        saturated = []
        for s in list(active):
            add = remaining * weights[s]
            add = min(add, capacity[s])
            shares[s] += add
            capacity[s] -= add
            moved += add
            if capacity[s] <= 1e-8:
                saturated.append(s)
        for s in saturated:
            active.discard(s)
        if moved <= 1e-8:
            break
        remaining -= moved

    # Numeric cleanup.
    diff = total - sum(shares.values())
    for s in SUPPLIERS:
        room = maxs[s] - shares[s]
        if abs(diff) <= 1e-6:
            break
        if diff > 0 and room > 1e-9:
            add = min(room, diff)
            shares[s] += add
            diff -= add
        elif diff < 0 and shares[s] > mins[s] + 1e-9:
            remove = min(shares[s] - mins[s], -diff)
            shares[s] -= remove
            diff += remove

    return {s: round(shares[s], 6) for s in SUPPLIERS}


def rebalance_after_slider_change(country: str, changed_supplier: str) -> None:
    mins = get_min_shares()
    maxs = get_max_shares()
    changed_key = share_key(country, changed_supplier)
    changed_value = float(st.session_state.get(changed_key, DEFAULT_SHARES[country][changed_supplier]))
    changed_value = max(mins[changed_supplier], min(maxs[changed_supplier], changed_value))

    min_others = sum(mins[s] for s in SUPPLIERS if s != changed_supplier)
    max_others = sum(maxs[s] for s in SUPPLIERS if s != changed_supplier)
    changed_value = min(changed_value, 100.0 - min_others)
    changed_value = max(changed_value, 100.0 - max_others)
    changed_value = max(mins[changed_supplier], min(maxs[changed_supplier], changed_value))

    remaining = 100.0 - changed_value
    others = [s for s in SUPPLIERS if s != changed_supplier]
    preferences = {s: float(st.session_state.get(share_key(country, s), DEFAULT_SHARES[country][s])) for s in others}
    other_mins = {s: mins[s] for s in others}
    other_maxs = {s: maxs[s] for s in others}

    # Local allocation among other suppliers.
    shares = {s: other_mins[s] for s in others}
    rem = remaining - sum(shares.values())
    capacities = {s: max(0.0, other_maxs[s] - other_mins[s]) for s in others}
    pref_excess = {s: max(0.0, preferences[s] - other_mins[s]) for s in others}
    if sum(pref_excess.values()) <= 1e-9:
        pref_excess = capacities.copy()
    active = {s for s in others if capacities[s] > 1e-9}
    while rem > 1e-8 and active:
        denom = sum(pref_excess[s] for s in active)
        if denom <= 1e-9:
            denom = sum(capacities[s] for s in active)
            weights = {s: capacities[s] / denom if denom else 0.0 for s in active}
        else:
            weights = {s: pref_excess[s] / denom for s in active}
        moved = 0.0
        saturated = []
        for s in list(active):
            add = min(rem * weights[s], capacities[s])
            shares[s] += add
            capacities[s] -= add
            moved += add
            if capacities[s] <= 1e-8:
                saturated.append(s)
        for s in saturated:
            active.discard(s)
        if moved <= 1e-8:
            break
        rem -= moved

    st.session_state[changed_key] = changed_value
    for s in others:
        st.session_state[share_key(country, s)] = round(shares[s], 4)


def apply_pending_optimized_shares() -> None:
    pending = st.session_state.pop("pending_optimized_shares", None)
    if not pending:
        return
    for country, supplier_shares in pending.items():
        for supplier, value in supplier_shares.items():
            st.session_state[share_key(country, supplier)] = float(value)
    st.session_state["last_optimization_applied"] = True


apply_pending_optimized_shares()

# =============================================================================
# Input state initialization
# =============================================================================

def init_defaults() -> None:
    for supplier in SUPPLIERS:
        st.session_state.setdefault(kraljic_key(supplier), DEFAULT_KRALJIC_REQUIRED[supplier])
        st.session_state.setdefault(min_key(supplier), DEFAULT_MIN_SHARE[supplier])
        st.session_state.setdefault(max_key(supplier), DEFAULT_MAX_SHARE[supplier])
        st.session_state.setdefault(approved_key(supplier), DEFAULT_APPROVED[supplier])
    for country in COUNTRIES:
        for supplier in SUPPLIERS:
            st.session_state.setdefault(share_key(country, supplier), DEFAULT_SHARES[country][supplier])


init_defaults()

# =============================================================================
# Financial calculation engine
# =============================================================================

def supplier_risk_scores(risk_inputs: Dict[str, Dict[str, float]], risk_weights: Dict[str, float]) -> Dict[str, float]:
    weight_total = sum(risk_weights.values()) or 1.0
    scores = {}
    for supplier in SUPPLIERS:
        score = sum(risk_inputs[supplier][dim] * risk_weights[dim] for dim in risk_weights) / weight_total
        scores[supplier] = score
    return scores


def calc_current_by_country(country: str, country_inputs: Dict[str, Dict], method: str) -> Dict[str, float]:
    inp = country_inputs[country]
    spend = inp["current_spend"]
    fin_rate = equivalent_rate(inp["financial_rate_pct"], inp["financial_reference_days"], inp["current_payment_days"], method)
    treasury_rate = equivalent_rate(inp["treasury_return_pct"], inp["treasury_reference_days"], inp["current_payment_days"], method)
    inventory_rate = equivalent_rate(inp["inventory_carry_rate_pct"], 360, inp["current_inventory_days"], method)
    gross_financial_cost = spend * fin_rate
    capital_gain = spend * treasury_rate
    inventory_cost = spend * inventory_rate
    gross_total = spend + gross_financial_cost
    economic_total = spend + gross_financial_cost - capital_gain + inventory_cost
    return {
        "country": country,
        "base_spend": spend,
        "gross_financial_cost": gross_financial_cost,
        "capital_gain": capital_gain,
        "inventory_cost": inventory_cost,
        "gross_total": gross_total,
        "economic_total": economic_total,
        "effective_financial_rate": fin_rate,
        "effective_treasury_rate": treasury_rate,
        "payment_days": inp["current_payment_days"],
    }


def calc_proposal_by_country(
    country: str,
    shares: Dict[str, float],
    country_inputs: Dict[str, Dict],
    proposal_inputs: Dict[str, Dict[str, Dict]],
    supplier_risk: Dict[str, float],
    method: str,
) -> Dict[str, float]:
    country_total = {
        "country": country,
        "new_spend": 0.0,
        "new_gross_financial_cost": 0.0,
        "new_capital_gain": 0.0,
        "new_inventory_cost": 0.0,
        "new_gross_total": 0.0,
        "new_economic_total": 0.0,
        "weighted_risk_numerator": 0.0,
        "weighted_payment_days_numerator": 0.0,
        "weighted_financial_rate_numerator": 0.0,
        "supplier_rows": [],
    }
    inp = country_inputs[country]
    for supplier in SUPPLIERS:
        share = shares[supplier] / 100.0
        supplier_data = proposal_inputs[country][supplier]
        allocated_spend = supplier_data["spend"] * share
        fin_rate = equivalent_rate(inp["financial_rate_pct"], inp["financial_reference_days"], supplier_data["payment_days"], method)
        treasury_rate = equivalent_rate(inp["treasury_return_pct"], inp["treasury_reference_days"], supplier_data["payment_days"], method)
        inventory_days = supplier_data["lead_time_days"] + supplier_data["safety_stock_days"]
        inventory_rate = equivalent_rate(inp["inventory_carry_rate_pct"], 360, inventory_days, method)
        gross_financial = allocated_spend * fin_rate
        capital_gain = allocated_spend * treasury_rate
        inventory_cost = allocated_spend * inventory_rate
        gross_total = allocated_spend + gross_financial
        economic_total = allocated_spend + gross_financial - capital_gain + inventory_cost
        risk = supplier_risk[supplier]

        country_total["new_spend"] += allocated_spend
        country_total["new_gross_financial_cost"] += gross_financial
        country_total["new_capital_gain"] += capital_gain
        country_total["new_inventory_cost"] += inventory_cost
        country_total["new_gross_total"] += gross_total
        country_total["new_economic_total"] += economic_total
        country_total["weighted_risk_numerator"] += allocated_spend * risk
        country_total["weighted_payment_days_numerator"] += allocated_spend * supplier_data["payment_days"]
        country_total["weighted_financial_rate_numerator"] += allocated_spend * fin_rate
        country_total["supplier_rows"].append({
            "Country": country,
            "Supplier": supplier,
            "Share %": shares[supplier],
            "Allocated Spend": allocated_spend,
            "Payment Days": supplier_data["payment_days"],
            "Supplier Financial Cost": gross_financial,
            "Capital Gain Offset": capital_gain,
            "Inventory Carrying Cost": inventory_cost,
            "Economic Total": economic_total,
            "Risk Score": risk,
        })
    spend = country_total["new_spend"]
    country_total["weighted_risk"] = safe_divide(country_total["weighted_risk_numerator"], spend)
    country_total["avg_payment_days"] = safe_divide(country_total["weighted_payment_days_numerator"], spend)
    country_total["avg_financial_rate"] = safe_divide(country_total["weighted_financial_rate_numerator"], spend)
    return country_total


def calc_scenario(
    all_shares: Dict[str, Dict[str, float]],
    country_inputs: Dict[str, Dict],
    proposal_inputs: Dict[str, Dict[str, Dict]],
    supplier_risk: Dict[str, float],
    method: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, float]]:
    rows = []
    supplier_rows = []
    for country in COUNTRIES:
        cur = calc_current_by_country(country, country_inputs, method)
        prop = calc_proposal_by_country(country, all_shares[country], country_inputs, proposal_inputs, supplier_risk, method)
        row = {
            "Country": country,
            "Group": "Brazil" if country == "Brazil" else "LATAM",
            "Current Spend": cur["base_spend"],
            "New Spend": prop["new_spend"],
            "Current Financial Cost": cur["gross_financial_cost"],
            "New Financial Cost": prop["new_gross_financial_cost"],
            "Current Total Spend": cur["gross_total"],
            "New Total Spend": prop["new_gross_total"],
            "Current Capital Gain": cur["capital_gain"],
            "New Capital Gain": prop["new_capital_gain"],
            "Current Inventory Cost": cur["inventory_cost"],
            "New Inventory Cost": prop["new_inventory_cost"],
            "Current Economic Total": cur["economic_total"],
            "New Economic Total": prop["new_economic_total"],
            "Spend Delta": prop["new_spend"] - cur["base_spend"],
            "Financial Delta": prop["new_gross_financial_cost"] - cur["gross_financial_cost"],
            "Gross All-In Delta": prop["new_gross_total"] - cur["gross_total"],
            "Capital Gain Delta": prop["new_capital_gain"] - cur["capital_gain"],
            "Inventory Delta": prop["new_inventory_cost"] - cur["inventory_cost"],
            "Economic All-In Delta": prop["new_economic_total"] - cur["economic_total"],
            "Weighted Risk": prop["weighted_risk"],
            "Current Payment Days": cur["payment_days"],
            "New Avg Payment Days": prop["avg_payment_days"],
            "Current Effective Financial Rate": cur["effective_financial_rate"],
            "New Avg Financial Rate": prop["avg_financial_rate"],
        }
        rows.append(row)
        supplier_rows.extend(prop["supplier_rows"])
    country_df = pd.DataFrame(rows)
    supplier_df = pd.DataFrame(supplier_rows)
    group_df = country_df.groupby("Group", as_index=False).agg(
        {
            "Current Spend": "sum",
            "New Spend": "sum",
            "Current Financial Cost": "sum",
            "New Financial Cost": "sum",
            "Current Total Spend": "sum",
            "New Total Spend": "sum",
            "Current Capital Gain": "sum",
            "New Capital Gain": "sum",
            "Current Inventory Cost": "sum",
            "New Inventory Cost": "sum",
            "Current Economic Total": "sum",
            "New Economic Total": "sum",
            "Spend Delta": "sum",
            "Financial Delta": "sum",
            "Gross All-In Delta": "sum",
            "Capital Gain Delta": "sum",
            "Inventory Delta": "sum",
            "Economic All-In Delta": "sum",
        }
    )
    # Weighted metrics by new spend.
    weighted_rows = []
    for group in ["Brazil", "LATAM"]:
        subset = country_df[country_df["Group"] == group]
        total_new_spend = subset["New Spend"].sum()
        weighted_rows.append({
            "Group": group,
            "Weighted Risk": safe_divide((subset["Weighted Risk"] * subset["New Spend"]).sum(), total_new_spend),
            "New Avg Payment Days": safe_divide((subset["New Avg Payment Days"] * subset["New Spend"]).sum(), total_new_spend),
            "New Avg Financial Rate": safe_divide((subset["New Avg Financial Rate"] * subset["New Spend"]).sum(), total_new_spend),
        })
    group_df = group_df.merge(pd.DataFrame(weighted_rows), on="Group", how="left")

    total = {}
    for col in [
        "Current Spend", "New Spend", "Current Financial Cost", "New Financial Cost", "Current Total Spend",
        "New Total Spend", "Current Capital Gain", "New Capital Gain", "Current Inventory Cost", "New Inventory Cost",
        "Current Economic Total", "New Economic Total", "Spend Delta", "Financial Delta", "Gross All-In Delta",
        "Capital Gain Delta", "Inventory Delta", "Economic All-In Delta"
    ]:
        total[col] = country_df[col].sum()
    total["Weighted Risk"] = safe_divide((country_df["Weighted Risk"] * country_df["New Spend"]).sum(), country_df["New Spend"].sum())
    total["New Avg Payment Days"] = safe_divide((country_df["New Avg Payment Days"] * country_df["New Spend"]).sum(), country_df["New Spend"].sum())
    total["New Avg Financial Rate"] = safe_divide((country_df["New Avg Financial Rate"] * country_df["New Spend"]).sum(), country_df["New Spend"].sum())
    return country_df, group_df, supplier_df, total

# =============================================================================
# Optimization engine
# =============================================================================

def enumerate_share_combinations(mins: Dict[str, float], maxs: Dict[str, float], step: int = 5) -> List[Dict[str, float]]:
    min_units = {s: int(round(mins[s] / step)) for s in SUPPLIERS}
    max_units = {s: int(round(maxs[s] / step)) for s in SUPPLIERS}
    total_units = int(100 / step)
    combos = []
    for vals in product(*(range(min_units[s], max_units[s] + 1) for s in SUPPLIERS)):
        if sum(vals) == total_units:
            combos.append({s: vals[i] * step for i, s in enumerate(SUPPLIERS)})
    return combos


def optimize_allocations(
    country_inputs: Dict[str, Dict],
    proposal_inputs: Dict[str, Dict[str, Dict]],
    supplier_risk: Dict[str, float],
    method: str,
    risk_threshold: float,
    optimization_step: int,
) -> Tuple[Dict[str, Dict[str, float]], pd.DataFrame, str]:
    mins = get_min_shares()
    maxs = get_max_shares()
    if sum(mins.values()) > 100.0 + 1e-9:
        raise ValueError("Kraljic minimum shares exceed 100%. Reduce minimum shares before optimizing.")
    if sum(maxs.values()) < 100.0 - 1e-9:
        raise ValueError("Supplier maximum shares do not allow 100% allocation. Increase max shares or approve more suppliers.")
    candidates = enumerate_share_combinations(mins, maxs, step=optimization_step)
    if not candidates:
        raise ValueError("No feasible allocation found under current Kraljic / max-share constraints.")

    optimized = {}
    rationale_rows = []
    for country in COUNTRIES:
        current_row = calc_current_by_country(country, country_inputs, method)
        best_under_risk = None
        best_overall = None
        evaluated = []
        for shares in candidates:
            prop = calc_proposal_by_country(country, shares, country_inputs, proposal_inputs, supplier_risk, method)
            economic_delta = prop["new_economic_total"] - current_row["economic_total"]
            gross_delta = prop["new_gross_total"] - current_row["gross_total"]
            spend_delta = prop["new_spend"] - current_row["base_spend"]
            row = {
                "Country": country,
                "Shares": shares,
                "Economic Delta": economic_delta,
                "Gross All-In Delta": gross_delta,
                "Spend Delta": spend_delta,
                "Weighted Risk": prop["weighted_risk"],
                "New Economic Total": prop["new_economic_total"],
                "New Gross Total": prop["new_gross_total"],
                "New Spend": prop["new_spend"],
            }
            evaluated.append(row)
            key = (economic_delta, prop["weighted_risk"], gross_delta)
            if best_overall is None or key < (best_overall["Economic Delta"], best_overall["Weighted Risk"], best_overall["Gross All-In Delta"]):
                best_overall = row
            if prop["weighted_risk"] <= risk_threshold:
                if best_under_risk is None or key < (best_under_risk["Economic Delta"], best_under_risk["Weighted Risk"], best_under_risk["Gross All-In Delta"]):
                    best_under_risk = row
        chosen = best_under_risk if best_under_risk is not None else best_overall
        optimized[country] = chosen["Shares"]
        rationale_rows.append({
            "Country": country,
            "Chosen Risk": chosen["Weighted Risk"],
            "Economic Delta": chosen["Economic Delta"],
            "Gross All-In Delta": chosen["Gross All-In Delta"],
            "Spend Delta": chosen["Spend Delta"],
            **{SHORT_SUPPLIER[s]: chosen["Shares"][s] for s in SUPPLIERS},
            "Risk Gate Met": chosen["Weighted Risk"] <= risk_threshold,
        })
    rationale_df = pd.DataFrame(rationale_rows)
    message = "Optimization applied. Shares were updated using lowest economic all-in cost as priority and weighted risk as tie-breaker."
    return optimized, rationale_df, message

# =============================================================================
# Sidebar settings
# =============================================================================

with st.sidebar:
    st.markdown("## Executive Settings")
    currency_symbol = st.text_input("Currency", value="USD")
    rate_method = st.radio("Rate conversion method", options=["Compound", "Linear"], index=0)
    optimization_step = st.select_slider("Optimization share grid", options=[1, 2, 5, 10], value=5, help="Lower grid = deeper optimization, slower runtime.")
    risk_threshold = st.slider("Preferred weighted risk ceiling", min_value=1.0, max_value=5.0, value=3.25, step=0.05)
    show_advanced_economic = st.checkbox("Show working capital economic view", value=True)

# =============================================================================
# Header
# =============================================================================

st.markdown(
    """
    <div class="executive-hero">
        <h1>Executive Procurement TCO & Should-Cost Dashboard</h1>
        <p>
            Senior decision view for strategic raw-material sourcing: commercial spend, payment-term financial cost,
            working-capital carry, inventory carrying cost, supplier risk, Kraljic constraints and automatic cost x risk optimization.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# Inputs
# =============================================================================

input_tabs = st.tabs([
    "1. Current Spend & Finance",
    "2. Supplier Proposals",
    "3. Supplier Risk & Constraints",
    "4. Share Projection & Optimization",
])

with input_tabs[0]:
    render_section("Current Spend & Financial Assumptions", "Set the current baseline and country-specific financial assumptions. Treasury return is used only in the economic working-capital view.")
    country_inputs: Dict[str, Dict] = {}
    for country in COUNTRIES:
        with st.expander(country, expanded=(country == "Brazil")):
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                current_spend = st.number_input(f"{country} current spend", min_value=0.0, value=DEFAULT_CURRENT_SPEND[country], step=100_000.0, format="%.2f", key=f"current_spend__{country}")
                current_payment_days = st.number_input(f"{country} current payment term days", min_value=0, value=DEFAULT_CURRENT_TERM[country], step=1, key=f"current_term__{country}")
            with c2:
                financial_rate_pct = st.number_input(f"{country} payment-term financial rate (%)", min_value=0.0, value=DEFAULT_FINANCIAL_RATE[country], step=0.05, format="%.4f", key=f"financial_rate__{country}")
                financial_reference_days = st.number_input(f"{country} financial rate period days", min_value=1, value=DEFAULT_REFERENCE_DAYS[country], step=1, key=f"financial_ref_days__{country}")
            with c3:
                treasury_return_pct = st.number_input(f"{country} net treasury return (%)", min_value=0.0, value=DEFAULT_TREASURY_RETURN[country], step=0.05, format="%.4f", key=f"treasury_return__{country}")
                treasury_reference_days = st.number_input(f"{country} treasury return period days", min_value=1, value=DEFAULT_TREASURY_REF_DAYS[country], step=1, key=f"treasury_ref_days__{country}")
            with c4:
                inventory_carry_rate_pct = st.number_input(f"{country} inventory carrying rate (% p.a.)", min_value=0.0, value=DEFAULT_INVENTORY_CARRY_RATE[country], step=0.05, format="%.4f", key=f"inventory_rate__{country}")
                current_inventory_days = st.number_input(f"{country} current inventory days", min_value=0, value=DEFAULT_CURRENT_INVENTORY_DAYS[country], step=1, key=f"current_inventory_days__{country}")
            country_inputs[country] = {
                "current_spend": float(current_spend),
                "current_payment_days": int(current_payment_days),
                "financial_rate_pct": float(financial_rate_pct),
                "financial_reference_days": int(financial_reference_days),
                "treasury_return_pct": float(treasury_return_pct),
                "treasury_reference_days": int(treasury_reference_days),
                "inventory_carry_rate_pct": float(inventory_carry_rate_pct),
                "current_inventory_days": int(current_inventory_days),
            }

with input_tabs[1]:
    render_section("Supplier Proposals", "Input supplier proposal spend without financial cost, proposed payment terms, lead time and safety stock assumptions.")
    proposal_inputs: Dict[str, Dict[str, Dict]] = {country: {} for country in COUNTRIES}
    for country in COUNTRIES:
        with st.expander(country, expanded=(country == "Brazil")):
            for supplier in SUPPLIERS:
                st.markdown(f"<div class='supplier-box'><span class='pill'>{SHORT_SUPPLIER[supplier]}</span>", unsafe_allow_html=True)
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    spend = st.number_input(
                        f"{country} | {supplier} | Expected spend",
                        min_value=0.0,
                        value=DEFAULT_PROPOSAL_SPEND[country][supplier],
                        step=50_000.0,
                        format="%.2f",
                        key=f"proposal_spend__{country}__{supplier}",
                    )
                with c2:
                    payment_days = st.number_input(
                        f"{country} | {supplier} | Payment term days",
                        min_value=0,
                        value=DEFAULT_PAYMENT_TERM[country][supplier],
                        step=1,
                        key=f"proposal_term__{country}__{supplier}",
                    )
                with c3:
                    lead_time_days = st.number_input(
                        f"{country} | {supplier} | Lead time days",
                        min_value=0,
                        value=DEFAULT_LEAD_TIME_DAYS[country][supplier],
                        step=1,
                        key=f"lead_time__{country}__{supplier}",
                    )
                with c4:
                    safety_stock_days = st.number_input(
                        f"{country} | {supplier} | Safety stock days",
                        min_value=0,
                        value=DEFAULT_SAFETY_STOCK_DAYS[country][supplier],
                        step=1,
                        key=f"safety_stock__{country}__{supplier}",
                    )
                st.markdown("</div>", unsafe_allow_html=True)
                proposal_inputs[country][supplier] = {
                    "spend": float(spend),
                    "payment_days": int(payment_days),
                    "lead_time_days": int(lead_time_days),
                    "safety_stock_days": int(safety_stock_days),
                }

with input_tabs[2]:
    render_section("Supplier Risk & Strategic Constraints", "Add Kraljic minimum shares, max allocation/capacity and multi-dimensional risk scores. These constraints drive optimization.")
    cweights = st.columns(len(DEFAULT_RISK_WEIGHTS))
    risk_weights: Dict[str, float] = {}
    for idx, dim in enumerate(DEFAULT_RISK_WEIGHTS):
        with cweights[idx]:
            risk_weights[dim] = st.number_input(f"{dim} weight", min_value=0.0, value=DEFAULT_RISK_WEIGHTS[dim], step=1.0, key=f"risk_weight__{dim}")

    risk_inputs: Dict[str, Dict[str, float]] = {supplier: {} for supplier in SUPPLIERS}
    for supplier in SUPPLIERS:
        with st.expander(supplier, expanded=(supplier == "ChemPrime")):
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.checkbox("Approved supplier", value=DEFAULT_APPROVED[supplier], key=approved_key(supplier))
                st.checkbox("Kraljic minimum required", value=DEFAULT_KRALJIC_REQUIRED[supplier], key=kraljic_key(supplier))
            with c2:
                st.number_input("Minimum share %", min_value=0.0, max_value=100.0, value=DEFAULT_MIN_SHARE[supplier], step=1.0, key=min_key(supplier))
            with c3:
                st.number_input("Maximum share / capacity %", min_value=0.0, max_value=100.0, value=DEFAULT_MAX_SHARE[supplier], step=1.0, key=max_key(supplier))
            with c4:
                st.caption("Risk scores use 1 = low risk and 5 = high risk.")
            rcols = st.columns(len(DEFAULT_RISK_WEIGHTS))
            for idx, dim in enumerate(DEFAULT_RISK_WEIGHTS):
                with rcols[idx]:
                    risk_inputs[supplier][dim] = st.slider(
                        f"{dim}", min_value=1.0, max_value=5.0, value=DEFAULT_RISK[supplier][dim], step=0.1, key=f"risk__{supplier}__{dim}"
                    )

with input_tabs[3]:
    render_section("Share Projection & Cost Optimization", "Use sliders as a scenario gadget while supplier proposal inputs remain fully active. Automatic mode keeps allocation at 100% respecting Kraljic floors.")
    share_mode = st.radio("Share control mode", options=["Automatic", "Manual"], horizontal=True, key="share_mode")
    mins_now = get_min_shares()
    maxs_now = get_max_shares()
    min_sum = sum(mins_now.values())
    max_sum = sum(maxs_now.values())
    if min_sum > 100.0:
        st.error("Kraljic minimum shares exceed 100%. Reduce minimum requirements.")
    if max_sum < 100.0:
        st.error("Supplier maximum/capacity constraints cannot reach 100%. Increase max share or approve more suppliers.")

    all_shares: Dict[str, Dict[str, float]] = {}
    for country in COUNTRIES:
        clamp_shares_to_bounds(country)
        with st.expander(f"{country} share projection", expanded=(country == "Brazil")):
            if share_mode == "Automatic":
                st.caption("Automatic mode: changing one supplier will rebalance the others proportionally while respecting min/max shares.")
            else:
                st.caption("Manual mode: sliders are normalized for the calculation if the raw total is not exactly 100%.")

            cols = st.columns(4)
            raw_shares = {}
            for idx, supplier in enumerate(SUPPLIERS):
                with cols[idx]:
                    min_value = float(mins_now[supplier])
                    max_value = float(maxs_now[supplier])
                    key = share_key(country, supplier)
                    current_value = float(st.session_state.get(key, DEFAULT_SHARES[country][supplier]))
                    current_value = max(min_value, min(max_value, current_value))
                    st.session_state[key] = current_value

                    # If min and max are the same, render a disabled visual slider with a
                    # separate key. This avoids StreamlitAPIException while making it clear
                    # that the share is locked by Kraljic/capacity constraints.
                    if max_value <= min_value + 1e-9:
                        raw = float(min_value)
                        st.session_state[key] = raw
                        st.slider(
                            SHORT_SUPPLIER[supplier],
                            min_value=0.0,
                            max_value=100.0,
                            value=raw,
                            step=1.0,
                            key=f"{key}__display_locked",
                            disabled=True,
                        )
                        st.caption(f"Locked at {raw:.0f}% by Kraljic/capacity constraint")
                    else:
                        kwargs = {}
                        if share_mode == "Automatic":
                            kwargs = {"on_change": rebalance_after_slider_change, "args": (country, supplier)}
                        raw = st.slider(
                            SHORT_SUPPLIER[supplier],
                            min_value=min_value,
                            max_value=max_value,
                            value=current_value,
                            step=1.0,
                            key=key,
                            **kwargs,
                        )
                        if mins_now[supplier] > 0:
                            st.caption(f"Kraljic floor: {mins_now[supplier]:.0f}%")

                    raw_shares[supplier] = float(raw)

            if share_mode == "Manual":
                effective = allocate_with_bounds(raw_shares, mins_now, maxs_now, total=100.0)
            else:
                total_raw = sum(float(st.session_state[share_key(country, s)]) for s in SUPPLIERS)
                if abs(total_raw - 100.0) > 1e-6:
                    effective = allocate_with_bounds(raw_shares, mins_now, maxs_now, total=100.0)
                    for s, v in effective.items():
                        st.session_state[share_key(country, s)] = v
                effective = {s: float(st.session_state[share_key(country, s)]) for s in SUPPLIERS}

            all_shares[country] = effective
            share_df = pd.DataFrame([{"Supplier": SHORT_SUPPLIER[s], "Effective Model Share %": effective[s]} for s in SUPPLIERS])
            st.dataframe(share_df, use_container_width=True)

    supplier_risk_preview = supplier_risk_scores(risk_inputs, risk_weights)
    country_df_preview, group_df_preview, supplier_df_preview, total_preview = calc_scenario(
        all_shares, country_inputs, proposal_inputs, supplier_risk_preview, rate_method
    )

    b1, b2 = st.columns([0.26, 0.74])
    with b1:
        if st.button("Cost Optimization", type="primary", use_container_width=True):
            try:
                optimized_shares, rationale_df, opt_message = optimize_allocations(
                    country_inputs=country_inputs,
                    proposal_inputs=proposal_inputs,
                    supplier_risk=supplier_risk_preview,
                    method=rate_method,
                    risk_threshold=risk_threshold,
                    optimization_step=int(optimization_step),
                )
                st.session_state["pending_optimized_shares"] = optimized_shares
                st.session_state["optimization_rationale_df"] = rationale_df
                st.session_state["optimization_message"] = opt_message
                st.rerun()
            except Exception as exc:
                st.error(f"Optimization failed: {exc}")
    with b2:
        st.caption("Optimization objective: minimize economic all-in cost first, then risk. Kraljic minimums, max shares/capacity and approval status are respected.")

    if st.session_state.get("last_optimization_applied"):
        st.success(st.session_state.get("optimization_message", "Optimization applied."))
        st.session_state["last_optimization_applied"] = False

# =============================================================================
# Calculate scenario after inputs
# =============================================================================

supplier_risk = supplier_risk_scores(risk_inputs, risk_weights)
# Re-read shares from session after all widgets.
final_shares: Dict[str, Dict[str, float]] = {}
for country in COUNTRIES:
    raw = {s: float(st.session_state.get(share_key(country, s), DEFAULT_SHARES[country][s])) for s in SUPPLIERS}
    final_shares[country] = allocate_with_bounds(raw, get_min_shares(), get_max_shares(), total=100.0)

country_df, group_df, supplier_df, total = calc_scenario(final_shares, country_inputs, proposal_inputs, supplier_risk, rate_method)

# =============================================================================
# Executive output
# =============================================================================

render_section("Executive Result", "Decision-ready view with commercial spend, gross payment-term financial cost, working-capital economic value and cost x risk recommendation.")

st.markdown('<div class="plain-title">Total cost stack</div>', unsafe_allow_html=True)
row1 = st.columns(6)
with row1[0]:
    render_kpi("Current Spend", format_money(total["Current Spend"], currency_symbol, compact=True), "Without financial cost", "neutral")
with row1[1]:
    render_kpi("New Spend", format_money(total["New Spend"], currency_symbol, compact=True), "Supplier proposals x shares", "neutral")
with row1[2]:
    render_kpi("Current Financial Cost", format_money(total["Current Financial Cost"], currency_symbol, compact=True), "Current spend x current payment-term rate", "neutral")
with row1[3]:
    render_kpi("New Financial Cost", format_money(total["New Financial Cost"], currency_symbol, compact=True), "New spend x proposed payment-term rates", "neutral")
with row1[4]:
    render_kpi("Current Total Spend", format_money(total["Current Total Spend"], currency_symbol, compact=True), "Current spend + current financial cost", "neutral")
with row1[5]:
    render_kpi("New Total Spend", format_money(total["New Total Spend"], currency_symbol, compact=True), "New spend + new financial cost", "neutral")

st.markdown('<div class="plain-title">Total decomposition</div>', unsafe_allow_html=True)
row2 = st.columns(4)
with row2[0]:
    render_kpi("Spend Saving / Impact", format_money(total["Spend Delta"], currency_symbol, compact=True, signed=True), "New spend - current spend", delta_tone(total["Spend Delta"]), short=True)
with row2[1]:
    render_kpi("Financial Saving / Impact", format_money(total["Financial Delta"], currency_symbol, compact=True, signed=True), "New financial cost - current financial cost", delta_tone(total["Financial Delta"]), short=True)
with row2[2]:
    render_kpi("All-In Saving / Impact", format_money(total["Gross All-In Delta"], currency_symbol, compact=True, signed=True), "New total spend - current total spend", delta_tone(total["Gross All-In Delta"]), short=True)
with row2[3]:
    render_kpi("Weighted Risk", f"{total['Weighted Risk']:.2f}/5", "Lower is better", risk_tone(total["Weighted Risk"]), short=True)

brazil_row = group_df[group_df["Group"] == "Brazil"].iloc[0]
latam_row = group_df[group_df["Group"] == "LATAM"].iloc[0]

st.markdown('<div class="plain-title">Brazil result</div>', unsafe_allow_html=True)
row3 = st.columns(3)
with row3[0]:
    render_kpi("Spend Saving / Impact", format_money(brazil_row["Spend Delta"], currency_symbol, compact=True, signed=True), "Brazil new spend - current spend", delta_tone(brazil_row["Spend Delta"]), short=True)
with row3[1]:
    render_kpi("Financial Saving / Impact", format_money(brazil_row["Financial Delta"], currency_symbol, compact=True, signed=True), "Brazil new financial cost - current financial cost", delta_tone(brazil_row["Financial Delta"]), short=True)
with row3[2]:
    render_kpi("All-In Saving / Impact", format_money(brazil_row["Gross All-In Delta"], currency_symbol, compact=True, signed=True), "Brazil new total - current total", delta_tone(brazil_row["Gross All-In Delta"]), short=True)

st.markdown('<div class="plain-title">LATAM result</div>', unsafe_allow_html=True)
row4 = st.columns(3)
with row4[0]:
    render_kpi("Spend Saving / Impact", format_money(latam_row["Spend Delta"], currency_symbol, compact=True, signed=True), "LATAM new spend - current spend", delta_tone(latam_row["Spend Delta"]), short=True)
with row4[1]:
    render_kpi("Financial Saving / Impact", format_money(latam_row["Financial Delta"], currency_symbol, compact=True, signed=True), "LATAM new financial cost - current financial cost", delta_tone(latam_row["Financial Delta"]), short=True)
with row4[2]:
    render_kpi("All-In Saving / Impact", format_money(latam_row["Gross All-In Delta"], currency_symbol, compact=True, signed=True), "LATAM new total - current total", delta_tone(latam_row["Gross All-In Delta"]), short=True)

if total["Economic All-In Delta"] <= 0:
    st.markdown(
        f"""
        <div class="decision-card decision-good">
            <div class="decision-title">Recommended scenario is economically attractive</div>
            <div class="decision-body">
                Economic all-in delta is <b>{format_money(total['Economic All-In Delta'], currency_symbol, signed=True)}</b> after considering supplier financing,
                treasury carry, inventory carrying cost and weighted risk. Commercial spend delta is <b>{format_money(total['Spend Delta'], currency_symbol, signed=True)}</b>.
            </div>
        </div>
        """, unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"""
        <div class="decision-card decision-bad">
            <div class="decision-title">Scenario still creates economic cost impact</div>
            <div class="decision-body">
                Economic all-in delta is <b>{format_money(total['Economic All-In Delta'], currency_symbol, signed=True)}</b>. Use Cost Optimization or adjust supplier mix, payment terms, risk constraints or proposal spend.
            </div>
        </div>
        """, unsafe_allow_html=True,
    )

# =============================================================================
# Charts
# =============================================================================

chart_col1, chart_col2 = st.columns([1.2, 1.0])
with chart_col1:
    if PLOTLY_AVAILABLE:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=["Current Spend", "New Spend", "Current Fin. Cost", "New Fin. Cost", "Current Total", "New Total"],
            y=[total["Current Spend"], total["New Spend"], total["Current Financial Cost"], total["New Financial Cost"], total["Current Total Spend"], total["New Total Spend"]],
            marker_color=["#64748b", "#2563eb", "#f97316", "#f97316", "#0f766e", "#1d4ed8"],
            text=[format_money(v, currency_symbol, compact=True) for v in [total["Current Spend"], total["New Spend"], total["Current Financial Cost"], total["New Financial Cost"], total["Current Total Spend"], total["New Total Spend"]]],
            textposition="outside",
            hovertemplate="%{x}<br>" + currency_symbol + " %{y:,.2f}<extra></extra>",
        ))
        fig.update_layout(title="Total Cost Stack", height=430, yaxis_title=f"Value ({currency_symbol})")
        st.plotly_chart(apply_chart_theme(fig), use_container_width=True)
    else:
        st.bar_chart(pd.DataFrame({"Value": [total["Current Spend"], total["New Spend"], total["Current Financial Cost"], total["New Financial Cost"], total["Current Total Spend"], total["New Total Spend"]]}, index=["Current Spend", "New Spend", "Current Fin. Cost", "New Fin. Cost", "Current Total", "New Total"]))

with chart_col2:
    if PLOTLY_AVAILABLE:
        fig = go.Figure()
        decomp_names = ["Spend Delta", "Financial Delta", "Capital Gain Delta", "Inventory Delta", "Economic Delta"]
        decomp_vals = [total["Spend Delta"], total["Financial Delta"], -total["Capital Gain Delta"], total["Inventory Delta"], total["Economic All-In Delta"]]
        fig.add_trace(go.Bar(
            x=decomp_names,
            y=decomp_vals,
            marker_color=[GREEN if v < 0 else RED if v > 0 else BLUE for v in decomp_vals],
            text=[format_money(v, currency_symbol, compact=True, signed=True) for v in decomp_vals],
            textposition="outside",
            hovertemplate="%{x}<br>" + currency_symbol + " %{y:,.2f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
        fig.update_layout(title="Economic Value Decomposition", height=430, yaxis_title=f"Delta ({currency_symbol})")
        st.plotly_chart(apply_chart_theme(fig), use_container_width=True)
    else:
        st.bar_chart(pd.DataFrame({"Delta": [total["Spend Delta"], total["Financial Delta"], -total["Capital Gain Delta"], total["Inventory Delta"], total["Economic All-In Delta"]]}, index=["Spend", "Financial", "Capital gain", "Inventory", "Economic"]))

chart_col3, chart_col4 = st.columns([1.0, 1.0])
with chart_col3:
    allocation_rows = []
    for country in COUNTRIES:
        for supplier in SUPPLIERS:
            allocation_rows.append({"Country": country, "Supplier": SHORT_SUPPLIER[supplier], "Share %": final_shares[country][supplier]})
    allocation_df = pd.DataFrame(allocation_rows)
    if PLOTLY_AVAILABLE:
        fig = go.Figure()
        for supplier in [SHORT_SUPPLIER[s] for s in SUPPLIERS]:
            subset = allocation_df[allocation_df["Supplier"] == supplier]
            fig.add_trace(go.Bar(x=subset["Country"], y=subset["Share %"], name=supplier, text=[f"{v:.0f}%" for v in subset["Share %"]], textposition="inside"))
        fig.update_layout(title="Supplier Share Projection by Country", barmode="stack", height=430, yaxis_title="Share %")
        st.plotly_chart(apply_chart_theme(fig), use_container_width=True)
    else:
        st.bar_chart(allocation_df.pivot(index="Country", columns="Supplier", values="Share %"))

with chart_col4:
    # Efficient frontier approximation with named scenarios.
    frontier_rows = []
    frontier_rows.append({"Scenario": "Current projection", "Risk": total["Weighted Risk"], "Economic Delta": total["Economic All-In Delta"]})
    try:
        opt_shares, opt_rationale, _ = optimize_allocations(country_inputs, proposal_inputs, supplier_risk, rate_method, risk_threshold, int(optimization_step))
        _, _, _, opt_total = calc_scenario(opt_shares, country_inputs, proposal_inputs, supplier_risk, rate_method)
        frontier_rows.append({"Scenario": "Optimized", "Risk": opt_total["Weighted Risk"], "Economic Delta": opt_total["Economic All-In Delta"]})
    except Exception:
        pass
    # Lowest risk feasible: allocate as much as possible to lowest risk suppliers.
    low_risk_preferences = {s: max(0.0, 6.0 - supplier_risk[s]) for s in SUPPLIERS}
    low_risk_shares = {country: allocate_with_bounds(low_risk_preferences, get_min_shares(), get_max_shares(), 100.0) for country in COUNTRIES}
    _, _, _, low_risk_total = calc_scenario(low_risk_shares, country_inputs, proposal_inputs, supplier_risk, rate_method)
    frontier_rows.append({"Scenario": "Lowest risk", "Risk": low_risk_total["Weighted Risk"], "Economic Delta": low_risk_total["Economic All-In Delta"]})
    frontier_df = pd.DataFrame(frontier_rows)
    if PLOTLY_AVAILABLE:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=frontier_df["Risk"], y=frontier_df["Economic Delta"], mode="markers+text",
            text=frontier_df["Scenario"], textposition="top center", marker=dict(size=15, color=[BLUE, GREEN, AMBER][:len(frontier_df)]),
            hovertemplate="%{text}<br>Risk: %{x:.2f}/5<br>Economic delta: " + currency_symbol + " %{y:,.2f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
        fig.update_layout(title="Cost x Risk Decision Map", height=430, xaxis_title="Weighted risk score", yaxis_title=f"Economic delta ({currency_symbol})")
        st.plotly_chart(apply_chart_theme(fig), use_container_width=True)
    else:
        st.dataframe(frontier_df)

# =============================================================================
# Working capital economic view and rationale
# =============================================================================

if show_advanced_economic:
    render_section("Working Capital Economic View", "This view separates P&L spend, payment-term financing, capital carry benefit and inventory carrying cost.")
    econ_cols = st.columns(5)
    with econ_cols[0]:
        render_kpi("Current Capital Gain", format_money(total["Current Capital Gain"], currency_symbol, compact=True), "Current payment-term carry benefit", "good", short=True)
    with econ_cols[1]:
        render_kpi("New Capital Gain", format_money(total["New Capital Gain"], currency_symbol, compact=True), "Proposed payment-term carry benefit", "good", short=True)
    with econ_cols[2]:
        render_kpi("Inventory Delta", format_money(total["Inventory Delta"], currency_symbol, compact=True, signed=True), "New inventory cost - current inventory cost", delta_tone(total["Inventory Delta"]), short=True)
    with econ_cols[3]:
        render_kpi("Current Economic Total", format_money(total["Current Economic Total"], currency_symbol, compact=True), "Gross total - capital gain + inventory", "neutral", short=True)
    with econ_cols[4]:
        render_kpi("New Economic Total", format_money(total["New Economic Total"], currency_symbol, compact=True), "Gross total - capital gain + inventory", "neutral", short=True)

    st.markdown("<div class='plain-title'>Optimization rationale</div>", unsafe_allow_html=True)
    rationale_df = st.session_state.get("optimization_rationale_df")
    if isinstance(rationale_df, pd.DataFrame) and not rationale_df.empty:
        display_rat = rationale_df.copy()
        for col in ["Economic Delta", "Gross All-In Delta", "Spend Delta"]:
            display_rat[col] = display_rat[col].map(lambda x: format_money(x, currency_symbol, signed=True))
        st.dataframe(display_rat, use_container_width=True)
    else:
        st.info("Run Cost Optimization to generate a country-by-country allocation rationale.")

# =============================================================================
# Detailed tables
# =============================================================================

render_section("Detailed Data", "Audit trail for Finance, Procurement and category strategy discussions.")

detail_tabs = st.tabs(["Country summary", "Region summary", "Supplier allocation", "Risk scores"])
with detail_tabs[0]:
    display_country = country_df.copy()
    money_cols = [c for c in display_country.columns if any(k in c for k in ["Spend", "Cost", "Gain", "Total", "Delta"])]
    for col in money_cols:
        display_country[col] = display_country[col].map(lambda x: format_money(x, currency_symbol, signed=("Delta" in col)))
    for col in ["Weighted Risk", "Current Effective Financial Rate", "New Avg Financial Rate"]:
        if col in display_country:
            if "Rate" in col:
                display_country[col] = display_country[col].map(format_pct)
            else:
                display_country[col] = display_country[col].map(lambda x: f"{x:.2f}")
    st.dataframe(display_country, use_container_width=True)
with detail_tabs[1]:
    display_group = group_df.copy()
    money_cols = [c for c in display_group.columns if any(k in c for k in ["Spend", "Cost", "Gain", "Total", "Delta"])]
    for col in money_cols:
        display_group[col] = display_group[col].map(lambda x: format_money(x, currency_symbol, signed=("Delta" in col)))
    st.dataframe(display_group, use_container_width=True)
with detail_tabs[2]:
    display_supplier = supplier_df.copy()
    for col in ["Allocated Spend", "Supplier Financial Cost", "Capital Gain Offset", "Inventory Carrying Cost", "Economic Total"]:
        display_supplier[col] = display_supplier[col].map(lambda x: format_money(x, currency_symbol))
    display_supplier["Share %"] = display_supplier["Share %"].map(lambda x: f"{x:.1f}%")
    display_supplier["Risk Score"] = display_supplier["Risk Score"].map(lambda x: f"{x:.2f}")
    st.dataframe(display_supplier, use_container_width=True)
with detail_tabs[3]:
    risk_df = pd.DataFrame([{"Supplier": s, "Weighted Risk": supplier_risk[s], **risk_inputs[s]} for s in SUPPLIERS])
    st.dataframe(risk_df, use_container_width=True)

# =============================================================================
# Download
# =============================================================================

export_country = country_df.copy()
export_group = group_df.copy()
export_supplier = supplier_df.copy()
combined_csv = export_country.to_csv(index=False).encode("utf-8")
st.download_button(
    label="Download country summary CSV",
    data=combined_csv,
    file_name="executive_procurement_tco_country_summary.csv",
    mime="text/csv",
)

st.markdown(
    """
    <div class="small-note">
        Note: Commercial saving, financial cost, working-capital benefit and economic all-in value are intentionally separated.
        Finance/Treasury should validate financial and treasury-return assumptions before any official saving recognition.
    </div>
    """,
    unsafe_allow_html=True,
)
