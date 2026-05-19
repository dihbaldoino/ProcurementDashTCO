"""
Executive Procurement TCO & Should-Cost Dashboard
Version v25 FINAL - Treasury Return Offset Logic

Run:
    pip install -r requirements.txt
    streamlit run app.py

This dashboard compares current spend vs. supplier proposals using:
- commercial spend
- payment-term supplier financial cost
- treasury/working-capital carry benefit
- inventory carrying cost with explicit ownership assumptions
- supplier risk and Kraljic minimum shares
- supplier capacity / max-share constraints with infeasibility warnings
- exact linear-programming cost optimization when SciPy is available, with grid fallback
- proposal financial and treasury return periods dynamically follow each supplier payment term; current financial period uses the current/reference period only
- gross financial impact is explicitly offset by incremental treasury return to produce net financial saving/impact

Key modeling guardrails
-----------------------
1. Supplier proposal spend is a 100% volume-equivalent spend, before financial cost.
2. Current baseline is never recalculated using proposal terms.
3. Proposal financial cost and treasury return use each supplier proposed payment term.
4. Negative deltas mean savings; positive deltas mean cost impact.
"""

from __future__ import annotations

import math
from itertools import product
from typing import Dict, Iterable, List, Tuple

import pandas as pd
import streamlit as st

try:
    from scipy.optimize import linprog
    SCIPY_AVAILABLE = True
except Exception:
    linprog = None
    SCIPY_AVAILABLE = False

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
# Default aligned with the executive test table: the current payment term defaults
# to the country financial-rate reference period. Users can still override it.
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
DEFAULT_PROPOSAL_SPEND = {
    "Brazil": {
        "ChemPrime": 16_250_000.0,
        "OleoGlobal": 9_750_000.0,
        "Oleo Overseas Trading Co.": 10_237_500.0,
        "Comercio de Oleos Nacional Distribuicao": 10_530_000.0,
    },
    "Mexico": {
        "ChemPrime": 3_750_000.0,
        "OleoGlobal": 2_250_000.0,
        "Oleo Overseas Trading Co.": 2_362_500.0,
        "Comercio de Oleos Nacional Distribuicao": 2_430_000.0,
    },
    "Argentina": {
        "ChemPrime": 3_125_000.0,
        "OleoGlobal": 1_875_000.0,
        "Oleo Overseas Trading Co.": 1_968_750.0,
        "Comercio de Oleos Nacional Distribuicao": 2_025_000.0,
    },
    "Colombia": {
        "ChemPrime": 1_875_000.0,
        "OleoGlobal": 1_125_000.0,
        "Oleo Overseas Trading Co.": 1_181_250.0,
        "Comercio de Oleos Nacional Distribuicao": 1_215_000.0,
    },
}
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

INVENTORY_OWNERSHIP_OPTIONS = [
    "Buyer owns transit + safety stock",
    "Buyer owns safety stock only",
    "Supplier/trader owns until delivery",
    "Distributor holds local stock",
]
DEFAULT_INVENTORY_OWNERSHIP = {
    country: {
        "ChemPrime": "Buyer owns safety stock only",
        "OleoGlobal": "Buyer owns transit + safety stock",
        "Oleo Overseas Trading Co.": "Supplier/trader owns until delivery",
        "Comercio de Oleos Nacional Distribuicao": "Distributor holds local stock",
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
        .visual-breaker {
            display: flex; align-items: center; gap: 14px;
            padding: 15px 18px; margin: 24px 0 14px 0;
            border-radius: 18px; border: 1px solid rgba(148, 163, 184, .26);
            box-shadow: 0 12px 26px rgba(2, 6, 23, .18);
            background: linear-gradient(135deg, rgba(15,23,42,.98) 0%, rgba(30,41,59,.96) 100%);
            position: relative; overflow: hidden;
        }
        .visual-breaker::before {
            content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 7px;
            background: var(--accent, #3b82f6);
        }
        .visual-breaker::after {
            content: ""; position: absolute; right: -72px; top: -72px; width: 165px; height: 165px;
            background: var(--accent-soft, rgba(59,130,246,.13)); border-radius: 999px;
        }
        .visual-icon {
            width: 42px; height: 42px; min-width: 42px; border-radius: 14px;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.25rem; background: var(--accent-soft, rgba(59,130,246,.16));
            border: 1px solid var(--accent-border, rgba(59,130,246,.28));
        }
        .visual-title {font-size: 1.08rem; font-weight: 900; color: #f8fafc; margin-bottom: 2px;}
        .visual-subtitle {font-size: .86rem; color: #cbd5e1; line-height: 1.32;}
        .visual-tag {
            margin-left: auto; padding: 6px 10px; border-radius: 999px;
            font-size: .72rem; font-weight: 850; letter-spacing: .05em; text-transform: uppercase;
            color: #e2e8f0; background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.12);
            white-space: nowrap; position: relative; z-index: 2;
        }
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


def render_visual_breaker(title: str, subtitle: str, icon: str, accent: str, tag: str) -> None:
    """Render a visual separator/header for executive dashboard sections."""
    st.markdown(
        f"""
        <div class="visual-breaker" style="--accent:{accent}; --accent-soft:{accent}22; --accent-border:{accent}55;">
            <div class="visual-icon">{icon}</div>
            <div>
                <div class="visual-title">{title}</div>
                <div class="visual-subtitle">{subtitle}</div>
            </div>
            <div class="visual-tag">{tag}</div>
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
    """Return supplier maximum/capacity shares.

    Important: this function does NOT silently override max share when a
    Kraljic minimum is higher than capacity. That situation is strategically
    infeasible and must be surfaced to the user instead of hidden.
    """
    maxs = {}
    for supplier in SUPPLIERS:
        approved = bool(st.session_state.get(approved_key(supplier), DEFAULT_APPROVED[supplier]))
        raw_max = float(st.session_state.get(max_key(supplier), DEFAULT_MAX_SHARE[supplier])) if approved else 0.0
        maxs[supplier] = raw_max
    return maxs


def constraint_issues(mins: Dict[str, float], maxs: Dict[str, float]) -> List[str]:
    issues: List[str] = []
    for supplier in SUPPLIERS:
        if mins[supplier] > maxs[supplier] + 1e-9:
            issues.append(
                f"{SHORT_SUPPLIER[supplier]} has Kraljic minimum {mins[supplier]:.0f}% "
                f"above max/capacity {maxs[supplier]:.0f}%."
            )
    if sum(mins.values()) > 100.0 + 1e-9:
        issues.append("Kraljic minimum shares exceed 100%.")
    if sum(maxs.values()) < 100.0 - 1e-9:
        issues.append("Supplier max/capacity constraints cannot reach 100%.")
    return issues


def clamp_shares_to_bounds(country: str) -> None:
    mins = get_min_shares()
    maxs = get_max_shares()
    for supplier in SUPPLIERS:
        k = share_key(country, supplier)
        if k not in st.session_state:
            st.session_state[k] = DEFAULT_SHARES[country][supplier]
        st.session_state[k] = max(mins[supplier], min(maxs[supplier], float(st.session_state[k])))


def allocate_with_bounds(preferences: Dict[str, float], mins: Dict[str, float], maxs: Dict[str, float], total: float = 100.0) -> Dict[str, float]:
    """Project preferences to shares that sum to total while respecting min/max bounds.

    If bounds are infeasible, this function remains stable for display purposes,
    but the UI and optimizer separately flag the infeasibility.
    """
    maxs = {s: max(float(maxs[s]), float(mins[s])) for s in SUPPLIERS}
    if sum(mins.values()) > total + 1e-9:
        return {s: safe_divide(mins[s], sum(mins.values())) * total for s in SUPPLIERS}
    if sum(maxs.values()) < total - 1e-9:
        return {s: safe_divide(maxs[s], sum(maxs.values())) * total for s in SUPPLIERS}

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


def inventory_days_from_ownership(ownership: str, lead_time_days: int, safety_stock_days: int) -> int:
    """Translate inventory ownership assumption into carrying-cost days.

    This avoids overstating inventory carrying cost when a trader/supplier or
    local distributor keeps ownership until delivery.
    """
    if ownership == "Buyer owns transit + safety stock":
        return int(lead_time_days) + int(safety_stock_days)
    if ownership == "Buyer owns safety stock only":
        return int(safety_stock_days)
    if ownership in {"Supplier/trader owns until delivery", "Distributor holds local stock"}:
        return 0
    return int(lead_time_days) + int(safety_stock_days)


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
        "weighted_share_sum": 0.0,
        "weighted_financial_rate_numerator": 0.0,
        "weighted_treasury_rate_numerator": 0.0,
        "weighted_return_days_numerator": 0.0,
        "supplier_rows": [],
    }
    inp = country_inputs[country]
    for supplier in SUPPLIERS:
        share = shares[supplier] / 100.0
        supplier_data = proposal_inputs[country][supplier]
        allocated_spend = supplier_data["spend"] * share
        fin_rate = equivalent_rate(inp["financial_rate_pct"], inp["financial_reference_days"], supplier_data["payment_days"], method)
        treasury_rate = equivalent_rate(inp["treasury_return_pct"], inp["treasury_reference_days"], supplier_data["payment_days"], method)
        inventory_days = inventory_days_from_ownership(
            supplier_data.get("inventory_ownership", "Buyer owns transit + safety stock"),
            supplier_data["lead_time_days"],
            supplier_data["safety_stock_days"],
        )
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
        # Payment/return days are share-weighted for operational readability.
        # Financial cost itself is still calculated supplier-by-supplier using allocated spend × equivalent rate.
        country_total["weighted_payment_days_numerator"] += share * supplier_data["payment_days"]
        country_total["weighted_share_sum"] += share
        country_total["weighted_financial_rate_numerator"] += allocated_spend * fin_rate
        country_total["weighted_treasury_rate_numerator"] += allocated_spend * treasury_rate
        country_total["weighted_return_days_numerator"] += share * supplier_data["payment_days"]
        country_total["supplier_rows"].append({
            "Country": country,
            "Supplier": supplier,
            "Share %": shares[supplier],
            "Allocated Spend": allocated_spend,
            "Payment Days": supplier_data["payment_days"],
            "Return Days Used": supplier_data["payment_days"],
            "Financial Rate Used": fin_rate,
            "Treasury Return Rate Used": treasury_rate,
            "Supplier Financial Cost": gross_financial,
            "Capital Gain Offset": capital_gain,
            "Inventory Ownership": supplier_data.get("inventory_ownership", "Buyer owns transit + safety stock"),
            "Inventory Days Charged": inventory_days,
            "Inventory Carrying Cost": inventory_cost,
            "Economic Total": economic_total,
            "Risk Score": risk,
        })
    spend = country_total["new_spend"]
    country_total["weighted_risk"] = safe_divide(country_total["weighted_risk_numerator"], spend)
    country_total["avg_payment_days"] = safe_divide(country_total["weighted_payment_days_numerator"], country_total["weighted_share_sum"])
    country_total["avg_return_days"] = safe_divide(country_total["weighted_return_days_numerator"], country_total["weighted_share_sum"])
    country_total["avg_financial_rate"] = safe_divide(country_total["weighted_financial_rate_numerator"], spend)
    country_total["avg_treasury_rate"] = safe_divide(country_total["weighted_treasury_rate_numerator"], spend)
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
            "Current Net Financial Effect": cur["gross_financial_cost"] - cur["capital_gain"],
            "New Net Financial Effect": prop["new_gross_financial_cost"] - prop["new_capital_gain"],
            "Net Financial Delta": (prop["new_gross_financial_cost"] - prop["new_capital_gain"]) - (cur["gross_financial_cost"] - cur["capital_gain"]),
            "Current Inventory Cost": cur["inventory_cost"],
            "New Inventory Cost": prop["new_inventory_cost"],
            "Current Economic Total": cur["economic_total"],
            "New Economic Total": prop["new_economic_total"],
            "Spend Delta": prop["new_spend"] - cur["base_spend"],
            "Financial Delta": prop["new_gross_financial_cost"] - cur["gross_financial_cost"],
            "Gross All-In Delta": prop["new_gross_total"] - cur["gross_total"],
            "Capital Gain Delta": prop["new_capital_gain"] - cur["capital_gain"],
            "Treasury Return Offset Delta": cur["capital_gain"] - prop["new_capital_gain"],
            "Inventory Delta": prop["new_inventory_cost"] - cur["inventory_cost"],
            "Economic All-In Delta": prop["new_economic_total"] - cur["economic_total"],
            "Weighted Risk": prop["weighted_risk"],
            "Current Payment Days": cur["payment_days"],
            "New Avg Payment Days": prop["avg_payment_days"],
            "Current Effective Financial Rate": cur["effective_financial_rate"],
            "New Avg Financial Rate": prop["avg_financial_rate"],
            "Current Capital Gain": cur["capital_gain"],
            "New Capital Gain": prop["new_capital_gain"],
            "Current Net Financial Effect": cur["gross_financial_cost"] - cur["capital_gain"],
            "New Net Financial Effect": prop["new_gross_financial_cost"] - prop["new_capital_gain"],
            "Net Financial Delta": (prop["new_gross_financial_cost"] - prop["new_capital_gain"]) - (cur["gross_financial_cost"] - cur["capital_gain"]),
            "Current Effective Treasury Rate": cur["effective_treasury_rate"],
            "New Avg Treasury Rate": prop["avg_treasury_rate"],
            "Current Return Days": cur["payment_days"],
            "New Avg Return Days": prop["avg_return_days"],
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
            "Current Net Financial Effect": "sum",
            "New Net Financial Effect": "sum",
            "Net Financial Delta": "sum",
            "Current Inventory Cost": "sum",
            "New Inventory Cost": "sum",
            "Current Economic Total": "sum",
            "New Economic Total": "sum",
            "Spend Delta": "sum",
            "Financial Delta": "sum",
            "Gross All-In Delta": "sum",
            "Capital Gain Delta": "sum",
            "Treasury Return Offset Delta": "sum",
            "Inventory Delta": "sum",
            "Economic All-In Delta": "sum",
        }
    )
    # Weighted metrics by new spend.
    weighted_rows = []
    for group in ["Brazil", "LATAM"]:
        subset = country_df[country_df["Group"] == group]
        total_new_spend = subset["New Spend"].sum()
        total_current_spend = subset["Current Spend"].sum()
        weighted_rows.append({
            "Group": group,
            "Weighted Risk": safe_divide((subset["Weighted Risk"] * subset["New Spend"]).sum(), total_new_spend),
            "Current Avg Payment Days": safe_divide((subset["Current Payment Days"] * subset["Current Spend"]).sum(), total_current_spend),
            "New Avg Payment Days": safe_divide((subset["New Avg Payment Days"] * subset["New Spend"]).sum(), total_new_spend),
            "New Avg Return Days": safe_divide((subset["New Avg Return Days"] * subset["New Spend"]).sum(), total_new_spend),
            "New Avg Financial Rate": safe_divide((subset["New Avg Financial Rate"] * subset["New Spend"]).sum(), total_new_spend),
            "New Avg Treasury Rate": safe_divide((subset["New Avg Treasury Rate"] * subset["New Spend"]).sum(), total_new_spend),
        })
    group_df = group_df.merge(pd.DataFrame(weighted_rows), on="Group", how="left")

    total = {}
    for col in [
        "Current Spend", "New Spend", "Current Financial Cost", "New Financial Cost", "Current Total Spend",
        "New Total Spend", "Current Capital Gain", "New Capital Gain", "Current Net Financial Effect", "New Net Financial Effect",
        "Current Inventory Cost", "New Inventory Cost", "Current Economic Total", "New Economic Total",
        "Spend Delta", "Financial Delta", "Net Financial Delta", "Gross All-In Delta",
        "Capital Gain Delta", "Treasury Return Offset Delta", "Inventory Delta", "Economic All-In Delta"
    ]:
        total[col] = country_df[col].sum()
    total["Weighted Risk"] = safe_divide((country_df["Weighted Risk"] * country_df["New Spend"]).sum(), country_df["New Spend"].sum())
    total["Current Avg Payment Days"] = safe_divide((country_df["Current Payment Days"] * country_df["Current Spend"]).sum(), country_df["Current Spend"].sum())
    total["New Avg Payment Days"] = safe_divide((country_df["New Avg Payment Days"] * country_df["New Spend"]).sum(), country_df["New Spend"].sum())
    total["New Avg Return Days"] = safe_divide((country_df["New Avg Return Days"] * country_df["New Spend"]).sum(), country_df["New Spend"].sum())
    total["New Avg Financial Rate"] = safe_divide((country_df["New Avg Financial Rate"] * country_df["New Spend"]).sum(), country_df["New Spend"].sum())
    total["New Avg Treasury Rate"] = safe_divide((country_df["New Avg Treasury Rate"] * country_df["New Spend"]).sum(), country_df["New Spend"].sum())
    return country_df, group_df, supplier_df, total


def calc_full_supplier_reference_stack(
    supplier: str,
    country_inputs: Dict[str, Dict],
    proposal_inputs: Dict[str, Dict[str, Dict]],
    method: str,
    payment_day_overrides: Dict[str, float] | None = None,
) -> Dict[str, float]:
    """Build a 100% allocation reference stack for a single supplier across all countries.

    This is useful for executive benchmarking, e.g. showing the scenario where
    100% of the total volume is awarded to ChemPrime under its proposed price
    and payment terms.
    """
    total_spend = 0.0
    total_financial_cost = 0.0
    total_total_spend = 0.0
    weighted_payment_days_num = 0.0
    for country in COUNTRIES:
        inp = country_inputs[country]
        supplier_data = proposal_inputs[country][supplier]
        spend = supplier_data["spend"]
        payment_days = payment_day_overrides.get(country, supplier_data["payment_days"]) if payment_day_overrides else supplier_data["payment_days"]
        fin_rate = equivalent_rate(inp["financial_rate_pct"], inp["financial_reference_days"], payment_days, method)
        financial_cost = spend * fin_rate
        total_spend += spend
        total_financial_cost += financial_cost
        total_total_spend += spend + financial_cost
        weighted_payment_days_num += spend * payment_days
    return {
        "Reference Spend": total_spend,
        "Reference Financial Cost": total_financial_cost,
        "Reference Total Spend": total_total_spend,
        "Reference Avg Payment Days": safe_divide(weighted_payment_days_num, total_spend),
    }

# =============================================================================
# Optimization engine
# =============================================================================

def enumerate_share_combinations(mins: Dict[str, float], maxs: Dict[str, float], step: int = 5) -> List[Dict[str, float]]:
    """Enumerate feasible share combinations using conservative rounding.

    Minimum constraints are rounded UP and max/capacity constraints are rounded
    DOWN so the optimizer never violates a strategic floor or capacity ceiling.
    """
    if any(mins[s] > maxs[s] + 1e-9 for s in SUPPLIERS):
        return []
    min_units = {s: int(math.ceil(mins[s] / step - 1e-12)) for s in SUPPLIERS}
    max_units = {s: int(math.floor(maxs[s] / step + 1e-12)) for s in SUPPLIERS}
    total_units = int(round(100 / step))
    combos = []
    for vals in product(*(range(min_units[s], max_units[s] + 1) for s in SUPPLIERS)):
        if sum(vals) == total_units:
            combos.append({s: vals[i] * step for i, s in enumerate(SUPPLIERS)})
    return combos


def _supplier_unit_economic_cost(
    country: str,
    supplier: str,
    country_inputs: Dict[str, Dict],
    proposal_inputs: Dict[str, Dict[str, Dict]],
    method: str,
) -> float:
    """Economic cost generated if supplier gets 100% country share."""
    inp = country_inputs[country]
    supplier_data = proposal_inputs[country][supplier]
    spend = supplier_data["spend"]
    fin_rate = equivalent_rate(inp["financial_rate_pct"], inp["financial_reference_days"], supplier_data["payment_days"], method)
    treasury_rate = equivalent_rate(inp["treasury_return_pct"], inp["treasury_reference_days"], supplier_data["payment_days"], method)
    inventory_days = inventory_days_from_ownership(
        supplier_data.get("inventory_ownership", "Buyer owns transit + safety stock"),
        supplier_data["lead_time_days"],
        supplier_data["safety_stock_days"],
    )
    inventory_rate = equivalent_rate(inp["inventory_carry_rate_pct"], 360, inventory_days, method)
    return spend * (1 + fin_rate - treasury_rate + inventory_rate)


def _optimize_allocations_lp(
    country_inputs: Dict[str, Dict],
    proposal_inputs: Dict[str, Dict[str, Dict]],
    supplier_risk: Dict[str, float],
    method: str,
    risk_threshold: float,
) -> Tuple[Dict[str, Dict[str, float]], str]:
    """Exact linear optimization using scipy.linprog.

    Decision variables are country-supplier shares in fractions. The objective
    minimizes proposal economic cost. Since current cost is constant, this is
    equivalent to minimizing economic all-in delta. Risk is constrained by the
    preferred risk threshold when feasible.
    """
    if not SCIPY_AVAILABLE:
        raise RuntimeError("SciPy is not available")

    mins = get_min_shares()
    maxs = get_max_shares()
    issues = constraint_issues(mins, maxs)
    if issues:
        raise ValueError("; ".join(issues))

    variables = [(country, supplier) for country in COUNTRIES for supplier in SUPPLIERS]
    n = len(variables)

    # Add a very small risk penalty to break true cost ties without allowing risk
    # to dominate cost. Cost remains priority #1.
    mean_cost = sum(_supplier_unit_economic_cost(c, s, country_inputs, proposal_inputs, method) for c, s in variables) / max(n, 1)
    risk_tiebreaker = mean_cost * 1e-7
    c = []
    for country, supplier in variables:
        c.append(_supplier_unit_economic_cost(country, supplier, country_inputs, proposal_inputs, method) + risk_tiebreaker * supplier_risk[supplier])

    # Each country must sum to 100%.
    A_eq = []
    b_eq = []
    for country in COUNTRIES:
        row = [0.0] * n
        for i, (c_country, _) in enumerate(variables):
            if c_country == country:
                row[i] = 1.0
        A_eq.append(row)
        b_eq.append(1.0)

    # Risk threshold by country: sum(spend*x*(risk-threshold)) <= 0.
    A_ub = []
    b_ub = []
    for country in COUNTRIES:
        row = [0.0] * n
        for i, (c_country, supplier) in enumerate(variables):
            if c_country == country:
                spend = proposal_inputs[country][supplier]["spend"]
                row[i] = spend * (supplier_risk[supplier] - risk_threshold)
        A_ub.append(row)
        b_ub.append(0.0)

    bounds = []
    for _, supplier in variables:
        bounds.append((mins[supplier] / 100.0, maxs[supplier] / 100.0))

    result = linprog(c=c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    risk_gate_used = True

    # If risk threshold makes the model infeasible, solve without the risk gate
    # but still use risk as a tiny tie-breaker. This is disclosed in the rationale.
    if not result.success:
        result = linprog(c=c, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
        risk_gate_used = False

    if not result.success:
        raise ValueError(f"No feasible allocation found: {result.message}")

    optimized: Dict[str, Dict[str, float]] = {country: {} for country in COUNTRIES}
    for value, (country, supplier) in zip(result.x, variables):
        optimized[country][supplier] = round(float(value) * 100.0, 4)

    method_message = "Exact LP optimizer used" if risk_gate_used else "Exact LP optimizer used; preferred risk gate was infeasible, so cost optimization ran without the risk ceiling"
    return optimized, method_message


def _optimize_allocations_grid(
    country_inputs: Dict[str, Dict],
    proposal_inputs: Dict[str, Dict[str, Dict]],
    supplier_risk: Dict[str, float],
    method: str,
    risk_threshold: float,
    optimization_step: int,
) -> Tuple[Dict[str, Dict[str, float]], str]:
    mins = get_min_shares()
    maxs = get_max_shares()
    issues = constraint_issues(mins, maxs)
    if issues:
        raise ValueError("; ".join(issues))
    candidates = enumerate_share_combinations(mins, maxs, step=optimization_step)
    if not candidates:
        raise ValueError("No feasible allocation found under current Kraljic / max-share constraints.")

    optimized = {}
    for country in COUNTRIES:
        current_row = calc_current_by_country(country, country_inputs, method)
        best_under_risk = None
        best_overall = None
        for shares in candidates:
            prop = calc_proposal_by_country(country, shares, country_inputs, proposal_inputs, supplier_risk, method)
            economic_delta = prop["new_economic_total"] - current_row["economic_total"]
            gross_delta = prop["new_gross_total"] - current_row["gross_total"]
            key = (economic_delta, prop["weighted_risk"], gross_delta)
            row = {"Shares": shares, "Economic Delta": economic_delta, "Weighted Risk": prop["weighted_risk"], "Gross All-In Delta": gross_delta}
            if best_overall is None or key < (best_overall["Economic Delta"], best_overall["Weighted Risk"], best_overall["Gross All-In Delta"]):
                best_overall = row
            if prop["weighted_risk"] <= risk_threshold:
                if best_under_risk is None or key < (best_under_risk["Economic Delta"], best_under_risk["Weighted Risk"], best_under_risk["Gross All-In Delta"]):
                    best_under_risk = row
        chosen = best_under_risk if best_under_risk is not None else best_overall
        optimized[country] = chosen["Shares"]
    return optimized, f"Grid optimizer used at {optimization_step}% step"


def optimize_allocations(
    country_inputs: Dict[str, Dict],
    proposal_inputs: Dict[str, Dict[str, Dict]],
    supplier_risk: Dict[str, float],
    method: str,
    risk_threshold: float,
    optimization_step: int,
) -> Tuple[Dict[str, Dict[str, float]], pd.DataFrame, str]:
    """Optimize allocation by economic all-in value, then risk.

    Uses exact linear programming when SciPy is available; otherwise falls back
    to grid search with conservative minimum/maximum rounding.
    """
    try:
        optimized, optimizer_message = _optimize_allocations_lp(
            country_inputs=country_inputs,
            proposal_inputs=proposal_inputs,
            supplier_risk=supplier_risk,
            method=method,
            risk_threshold=risk_threshold,
        )
    except Exception as lp_exc:
        optimized, optimizer_message = _optimize_allocations_grid(
            country_inputs=country_inputs,
            proposal_inputs=proposal_inputs,
            supplier_risk=supplier_risk,
            method=method,
            risk_threshold=risk_threshold,
            optimization_step=optimization_step,
        )
        optimizer_message += f" (LP unavailable/infeasible: {lp_exc})"

    # Build an explainable rationale table.
    rationale_rows = []
    country_df_opt, _, _, total_opt = calc_scenario(optimized, country_inputs, proposal_inputs, supplier_risk, method)
    for _, row in country_df_opt.iterrows():
        country = row["Country"]
        rationale_rows.append({
            "Country": country,
            "Chosen Risk": row["Weighted Risk"],
            "Economic Delta": row["Economic All-In Delta"],
            "Gross All-In Delta": row["Gross All-In Delta"],
            "Spend Delta": row["Spend Delta"],
            **{SHORT_SUPPLIER[s]: optimized[country][s] for s in SUPPLIERS},
            "Risk Gate Met": row["Weighted Risk"] <= risk_threshold,
        })
    rationale_df = pd.DataFrame(rationale_rows)
    message = (
        f"Optimization applied. {optimizer_message}. Objective: lowest economic all-in cost first, "
        "with payment-term financial cost, treasury return, inventory ownership/carrying cost and supplier risk considered. "
        f"Total optimized economic delta: {total_opt['Economic All-In Delta']:,.2f}."
    )
    return optimized, rationale_df, message

# =============================================================================
# Sidebar settings
# =============================================================================

with st.sidebar:
    st.markdown("## Executive Settings")
    currency_symbol = st.text_input("Currency", value="USD")
    rate_method = st.radio("Rate conversion method", options=["Compound", "Linear"], index=0)
    optimization_step = st.select_slider("Fallback optimization share grid", options=[1, 2, 5, 10], value=5, help="Used only if exact LP optimization is unavailable/infeasible. Lower grid = deeper but slower fallback.")
    st.caption("Optimizer: exact LP available" if SCIPY_AVAILABLE else "Optimizer: grid fallback only; SciPy not available")
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
    render_section("Current Spend & Financial Assumptions", "Set the current baseline and country-specific financial assumptions. Current financial and return rates use the current payment term only; proposal rates are recalculated later using each supplier proposed payment term.")
    st.info("Rate-period rule: the Financial Reference Period is the CURRENT baseline period. Current Financial Cost = Current Spend × the rate for that current period. Supplier proposals are recalculated supplier-by-supplier using each supplier proposed payment term as the NEW financial-rate and treasury-return period.")
    country_inputs: Dict[str, Dict] = {}
    for country in COUNTRIES:
        with st.expander(country, expanded=(country == "Brazil")):
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1:
                current_spend = st.number_input(
                    f"{country} current spend",
                    min_value=0.0,
                    value=DEFAULT_CURRENT_SPEND[country],
                    step=100_000.0,
                    format="%.2f",
                    key=f"v24_current_spend__{country}",
                )
                current_payment_days = st.number_input(
                    f"{country} current payment term days",
                    min_value=1,
                    value=DEFAULT_CURRENT_TERM[country],
                    step=1,
                    key=f"v24_current_payment_days__{country}",
                    help="This is the CURRENT baseline payment term. It does not change when supplier proposal terms change.",
                )
            with c2:
                financial_rate_pct = st.number_input(
                    f"{country} financial rate (%)",
                    min_value=0.0,
                    value=DEFAULT_FINANCIAL_RATE[country],
                    step=0.05,
                    format="%.4f",
                    key=f"v24_financial_rate__{country}",
                    help="Financial cost rate for the reference period below. Example: 4.84% for 120 days.",
                )
                financial_reference_days = st.number_input(
                    f"{country} financial rate reference days",
                    min_value=1,
                    value=DEFAULT_REFERENCE_DAYS[country],
                    step=1,
                    key=f"v24_financial_ref_days__{country}",
                    help="Period attached to the financial rate. Proposal terms will be converted from this base to each supplier payment term.",
                )
            with c3:
                treasury_return_pct = st.number_input(
                    f"{country} net treasury return (%)",
                    min_value=0.0,
                    value=DEFAULT_TREASURY_RETURN[country],
                    step=0.05,
                    format="%.4f",
                    key=f"v24_treasury_return__{country}",
                    help="Treasury/capital return rate for the reference period below. If your treasury return is better than supplier financing, longer payment terms create value.",
                )
                treasury_reference_days = st.number_input(
                    f"{country} treasury return reference days",
                    min_value=1,
                    value=DEFAULT_TREASURY_REF_DAYS[country],
                    step=1,
                    key=f"v24_treasury_ref_days__{country}",
                )
            with c4:
                inventory_carry_rate_pct = st.number_input(
                    f"{country} inventory carrying rate (% p.a.)",
                    min_value=0.0,
                    value=DEFAULT_INVENTORY_CARRY_RATE[country],
                    step=0.05,
                    format="%.4f",
                    key=f"v24_inventory_rate__{country}",
                )
                current_inventory_days = st.number_input(
                    f"{country} current inventory days",
                    min_value=0,
                    value=DEFAULT_CURRENT_INVENTORY_DAYS[country],
                    step=1,
                    key=f"v24_current_inventory_days__{country}",
                )
            with c5:
                st.markdown("<div class='small-note'><b>Baseline logic</b><br>Current financial/treasury effects use the current payment term. Supplier proposals use each supplier payment term as the new financial and treasury return period.</div>", unsafe_allow_html=True)
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
            st.caption(
                f"{country}: financial rate is referenced to {financial_reference_days} days; current baseline uses {current_payment_days} payment days; supplier proposals use each supplier payment term."
            )

with input_tabs[1]:
    render_section("Supplier Proposals", "Input supplier proposal spend without financial cost, proposed payment terms, lead time and safety stock assumptions. Each supplier payment term is used to calculate the NEW supplier financial cost and NEW treasury return period for that proposal only.")
    proposal_inputs: Dict[str, Dict[str, Dict]] = {country: {} for country in COUNTRIES}
    for country in COUNTRIES:
        with st.expander(country, expanded=(country == "Brazil")):
            for supplier in SUPPLIERS:
                st.markdown(f"<div class='supplier-box'><span class='pill'>{SHORT_SUPPLIER[supplier]}</span>", unsafe_allow_html=True)
                c1, c2, c3, c4, c5 = st.columns([1.35, 0.9, 0.9, 0.9, 1.25])
                with c1:
                    spend = st.number_input(
                        f"{country} | {supplier} | 100% volume-equivalent spend",
                        min_value=0.0,
                        value=DEFAULT_PROPOSAL_SPEND[country][supplier],
                        step=50_000.0,
                        format="%.2f",
                        key=f"proposal_spend__{country}__{supplier}",
                        help="Enter the spend this supplier would represent if it supplied 100% of the country volume. The Share Projection applies the allocation percentage later.",
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
                with c5:
                    inventory_ownership = st.selectbox(
                        f"{country} | {supplier} | Inventory ownership",
                        options=INVENTORY_OWNERSHIP_OPTIONS,
                        index=INVENTORY_OWNERSHIP_OPTIONS.index(DEFAULT_INVENTORY_OWNERSHIP[country][supplier]),
                        key=f"inventory_ownership__{country}__{supplier}",
                        help="Defines how many days are charged with inventory carrying cost.",
                    )
                st.markdown("</div>", unsafe_allow_html=True)
                proposal_inputs[country][supplier] = {
                    "spend": float(spend),
                    "payment_days": int(payment_days),
                    "lead_time_days": int(lead_time_days),
                    "safety_stock_days": int(safety_stock_days),
                    "inventory_ownership": inventory_ownership,
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
    render_section(
        "Share Projection & Cost Optimization",
        "Use sliders as a scenario gadget while supplier proposal inputs remain fully active. Cost Optimization automatically searches the best allocation and updates the sliders."
    )

    st.info(
        "Rate-period rule: Current baseline uses each country's current payment term only. "
        "Supplier proposals use each supplier's proposed payment term as the NEW financial-rate period and the NEW treasury-return period. "
        "Proposal payment terms never overwrite the current baseline."
    )

    share_mode = st.radio("Share control mode", options=["Automatic", "Manual"], horizontal=True, key="share_mode")
    mins_now = get_min_shares()
    maxs_now = get_max_shares()
    issues_now = constraint_issues(mins_now, maxs_now)
    invalid_constraints = bool(issues_now)

    if invalid_constraints:
        st.error("Constraint setup is infeasible. Please fix before using Cost Optimization.")
        for issue in issues_now:
            st.warning(issue)

    supplier_risk_preview = supplier_risk_scores(risk_inputs, risk_weights)

    # Keep the optimization control visible before the country sliders. In previous
    # versions it appeared after all expanders, which made it easy to miss.
    st.markdown("### Automatic Cost Optimization")
    opt_col1, opt_col2 = st.columns([0.28, 0.72])
    with opt_col1:
        if st.button("Cost Optimization", type="primary", use_container_width=True, key="cost_optimization_top"):
            if invalid_constraints:
                st.error("Optimization cannot run while Kraljic minimums or max/capacity constraints are infeasible.")
            else:
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
    with opt_col2:
        st.caption(
            "Objective: minimize economic all-in cost first, then weighted risk. "
            "The optimizer respects Kraljic minimum shares, supplier max/capacity and approved-supplier flags. "
            "After it runs, it automatically updates the Share Projection sliders."
        )

    if st.session_state.get("last_optimization_applied"):
        st.success(st.session_state.get("optimization_message", "Optimization applied."))
        st.session_state["last_optimization_applied"] = False

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

                    if max_value < min_value - 1e-9:
                        # Infeasible constraint: do not render a broken slider.
                        raw = min_value
                        st.warning(
                            f"{SHORT_SUPPLIER[supplier]} infeasible: floor {min_value:.0f}% > capacity {max_value:.0f}%."
                        )
                        st.slider(
                            SHORT_SUPPLIER[supplier],
                            min_value=0.0,
                            max_value=100.0,
                            value=min(raw, 100.0),
                            step=1.0,
                            key=f"{key}__display_infeasible",
                            disabled=True,
                        )
                    elif max_value <= min_value + 1e-9:
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
                        current_value = max(min_value, min(max_value, current_value))
                        st.session_state[key] = current_value
                        kwargs = {}
                        if share_mode == "Automatic" and not invalid_constraints:
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

    country_df_preview, group_df_preview, supplier_df_preview, total_preview = calc_scenario(
        all_shares, country_inputs, proposal_inputs, supplier_risk_preview, rate_method
    )

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
# Always-visible Cost Optimization panel
# =============================================================================

render_section(
    "Cost Optimization",
    "Run the optimizer from here at any time. It will respect Kraljic minimum shares, supplier capacity, approved-supplier flags, payment terms, financial rates, treasury return and inventory carrying cost."
)

current_mins_for_optimization = get_min_shares()
current_maxs_for_optimization = get_max_shares()
optimization_issues = constraint_issues(current_mins_for_optimization, current_maxs_for_optimization)
optimization_blocked = bool(optimization_issues)

for issue in optimization_issues:
    st.error(f"Optimization cannot run: {issue}")

opt_main_col, opt_note_col = st.columns([0.24, 0.76])
with opt_main_col:
    run_global_optimization = st.button(
        "Cost Optimization",
        type="primary",
        use_container_width=True,
        key="cost_optimization_always_visible",
        disabled=optimization_blocked,
    )

with opt_note_col:
    st.markdown(
        """
        <div class="insight-box" style="min-height: 92px; padding: 14px 16px;">
            <b>Optimization logic</b><br>
            Searches the best allocation by minimizing economic all-in cost first and weighted risk second.
            If a better allocation is found, the Share Projection sliders are updated automatically after the page refreshes.
        </div>
        """,
        unsafe_allow_html=True,
    )

if run_global_optimization:
    try:
        optimized_shares, rationale_df, opt_message = optimize_allocations(
            country_inputs=country_inputs,
            proposal_inputs=proposal_inputs,
            supplier_risk=supplier_risk,
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

if st.session_state.get("optimization_message"):
    st.success(st.session_state.get("optimization_message"))

# =============================================================================
# Financial calculation audit
# =============================================================================

st.markdown(
    """
    <div class="insight-box" style="min-height: 90px; padding: 14px 16px; margin-bottom: 14px;">
        <b>Financial calculation audit</b><br>
        Current Financial Cost is calculated only from <b>current spend × financial rate for the current/reference period</b>.
        New Financial Cost is calculated supplier-by-supplier from <b>allocated proposal spend × equivalent financial rate for each proposed payment term</b>.
        The audit's new payment days are <b>share-weighted</b>; supplier payment terms never overwrite the current baseline.
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("Show gross financial cost and treasury return audit by country"):
    st.markdown(
        """
        **Audit logic:** Gross Financial Delta is only the payment-term supplier financing cost impact.
        The correct finance decision view is **Net Financial Delta = Gross Financial Delta + Treasury Return Offset**,
        where Treasury Return Offset equals `Current Treasury Return - New Treasury Return`. A negative value is favorable because
        additional treasury return is offsetting financial cost.
        """
    )
    audit_cols = [
        "Country",
        "Current Spend",
        "Current Payment Days",
        "Current Effective Financial Rate",
        "Current Financial Cost",
        "Current Capital Gain",
        "New Spend",
        "New Avg Payment Days",
        "New Avg Financial Rate",
        "New Financial Cost",
        "New Capital Gain",
        "Financial Delta",
        "Treasury Return Offset Delta",
        "Net Financial Delta",
    ]
    audit_df = country_df[audit_cols].copy()
    money_cols = [
        "Current Spend",
        "Current Financial Cost",
        "Current Capital Gain",
        "New Spend",
        "New Financial Cost",
        "New Capital Gain",
        "Financial Delta",
        "Treasury Return Offset Delta",
        "Net Financial Delta",
    ]
    signed_cols = {"Financial Delta", "Treasury Return Offset Delta", "Net Financial Delta"}
    for col in money_cols:
        audit_df[col] = audit_df[col].map(lambda x, col=col: format_money(x, currency_symbol, signed=(col in signed_cols)))
    for col in ["Current Effective Financial Rate", "New Avg Financial Rate"]:
        audit_df[col] = audit_df[col].map(format_pct)
    audit_df["Current Payment Days"] = audit_df["Current Payment Days"].map(lambda x: f"{x:.0f} dd")
    audit_df["New Avg Payment Days"] = audit_df["New Avg Payment Days"].map(lambda x: f"{x:.0f} dd")
    st.dataframe(audit_df, use_container_width=True)

# =============================================================================
# Executive output
# =============================================================================

render_section("Executive Result", "Decision-ready view separating gross payment-term financial cost from treasury return offset. Net financial saving/impact is used for the finance decision view.")

gross_total_saving_impact = total["Gross All-In Delta"]
working_capital_gain_offset = total["Treasury Return Offset Delta"]
total_saving_plus_working_capital = gross_total_saving_impact + working_capital_gain_offset
final_economic_all_in = total["Economic All-In Delta"]

project_result_color = GREEN if final_economic_all_in <= 0 else RED
render_visual_breaker(
    'Total project saving',
    'Final Brazil + LATAM result, explicitly separating gross total saving, working-capital gain and inventory-adjusted economic all-in.',
    '🏁',
    project_result_color,
    'Final project result'
)
project_cols = st.columns([1.2, 1.2, 1.55, 1.35])
with project_cols[0]:
    render_kpi(
        "Gross Total Saving / Impact",
        format_money(gross_total_saving_impact, currency_symbol, compact=True, signed=True),
        "New total spend - current total spend | before treasury return",
        delta_tone(gross_total_saving_impact),
        short=True,
    )
with project_cols[1]:
    render_kpi(
        "Working Capital Gain",
        format_money(working_capital_gain_offset, currency_symbol, compact=True, signed=True),
        "Current treasury return - new treasury return | favorable when negative",
        delta_tone(working_capital_gain_offset),
        short=True,
    )
with project_cols[2]:
    render_kpi(
        "Total Saving + Working Capital",
        format_money(total_saving_plus_working_capital, currency_symbol, compact=True, signed=True),
        "Gross total saving/impact + incremental treasury return offset",
        delta_tone(total_saving_plus_working_capital),
    )
with project_cols[3]:
    render_kpi(
        "Final Economic All-In",
        format_money(final_economic_all_in, currency_symbol, compact=True, signed=True),
        "Total saving + working capital + inventory carrying delta",
        delta_tone(final_economic_all_in),
        short=True,
    )

contribution_cols = st.columns(2)
with contribution_cols[0]:
    render_kpi(
        "Brazil Contribution",
        format_money(group_df[group_df["Group"] == "Brazil"].iloc[0]["Economic All-In Delta"], currency_symbol, compact=True, signed=True),
        "Brazil economic all-in delta",
        delta_tone(group_df[group_df["Group"] == "Brazil"].iloc[0]["Economic All-In Delta"]),
        short=True,
    )
with contribution_cols[1]:
    render_kpi(
        "LATAM Contribution",
        format_money(group_df[group_df["Group"] == "LATAM"].iloc[0]["Economic All-In Delta"], currency_symbol, compact=True, signed=True),
        "Mexico + Argentina + Colombia economic all-in delta",
        delta_tone(group_df[group_df["Group"] == "LATAM"].iloc[0]["Economic All-In Delta"]),
        short=True,
    )

render_visual_breaker('Total cost stack', 'Commercial spend and gross payment-term cost comparison.', '🧾', '#3b82f6', 'Cost baseline')
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

chemprime_reference = calc_full_supplier_reference_stack(
    supplier="ChemPrime",
    country_inputs=country_inputs,
    proposal_inputs=proposal_inputs,
    method=rate_method,
    payment_day_overrides={"Brazil": 90, "Mexico": 60, "Argentina": 60, "Colombia": 60},
)

render_visual_breaker('New ChemPrime condition stack', 'Benchmark scenario assuming 100% volume under revised ChemPrime conditions.', '🏭', '#f59e0b', 'Reference case')
row1b = st.columns(6)
with row1b[0]:
    render_kpi(
        "100% ChemPrime Spend",
        format_money(chemprime_reference["Reference Spend"], currency_symbol, compact=True),
        "100% awarded to ChemPrime at proposed spend (+25%)",
        "neutral",
    )
with row1b[1]:
    render_kpi(
        "New Spend",
        format_money(total["New Spend"], currency_symbol, compact=True),
        "Supplier proposals x shares",
        "neutral",
    )
with row1b[2]:
    render_kpi(
        "100% ChemPrime Fin. Cost",
        format_money(chemprime_reference["Reference Financial Cost"], currency_symbol, compact=True),
        f"BR 90 dd | LATAM 60 dd financial terms",
        "neutral",
    )
with row1b[3]:
    render_kpi(
        "New Financial Cost",
        format_money(total["New Financial Cost"], currency_symbol, compact=True),
        "New spend x proposed payment-term rates",
        "neutral",
    )
with row1b[4]:
    render_kpi(
        "100% ChemPrime Total Spend",
        format_money(chemprime_reference["Reference Total Spend"], currency_symbol, compact=True),
        "100% ChemPrime spend + BR 90 dd / LATAM 60 dd financial cost",
        "neutral",
    )
with row1b[5]:
    render_kpi(
        "New Total Spend",
        format_money(total["New Total Spend"], currency_symbol, compact=True),
        "New spend + new financial cost",
        "neutral",
    )

render_visual_breaker('Working capital carry view', 'Treasury return and net financial effect from payment-term differences.', '🏦', '#10b981', 'Cash timing')
wc_row = st.columns(5)
with wc_row[0]:
    render_kpi("Current Treasury Return", format_money(total["Current Capital Gain"], currency_symbol, compact=True), "Capital return over current payment terms", "good", short=True)
with wc_row[1]:
    render_kpi("New Treasury Return", format_money(total["New Capital Gain"], currency_symbol, compact=True), "Capital return over proposed payment terms", "good", short=True)
with wc_row[2]:
    render_kpi("Current Net Financial Effect", format_money(total["Current Net Financial Effect"], currency_symbol, compact=True, signed=True), "Current financial cost - treasury return", delta_tone(total["Current Net Financial Effect"]), short=True)
with wc_row[3]:
    render_kpi("New Net Financial Effect", format_money(total["New Net Financial Effect"], currency_symbol, compact=True, signed=True), "New financial cost - treasury return", delta_tone(total["New Net Financial Effect"]), short=True)
with wc_row[4]:
    render_kpi("Net Financial Saving / Impact", format_money(total["Net Financial Delta"], currency_symbol, compact=True, signed=True), "New net effect - current net effect", delta_tone(total["Net Financial Delta"]), short=True)

render_visual_breaker('Total decomposition', 'Decision-ready breakdown of spend, financial effect, inventory and risk.', '🧩', '#8b5cf6', 'Decision view')
row2 = st.columns(6)
with row2[0]:
    render_kpi("Spend Saving / Impact", format_money(total["Spend Delta"], currency_symbol, compact=True, signed=True), "New spend - current spend", delta_tone(total["Spend Delta"]), short=True)
with row2[1]:
    render_kpi("Gross Financial Saving / Impact", format_money(total["Financial Delta"], currency_symbol, compact=True, signed=True), "New gross financial cost - current gross financial cost", delta_tone(total["Financial Delta"]), short=True)
with row2[2]:
    render_kpi("Treasury Return Offset", format_money(total["Treasury Return Offset Delta"], currency_symbol, compact=True, signed=True), "Current treasury return - new treasury return", delta_tone(total["Treasury Return Offset Delta"]), short=True)
with row2[3]:
    render_kpi("Net Financial Saving / Impact", format_money(total["Net Financial Delta"], currency_symbol, compact=True, signed=True), "Gross financial delta + treasury return offset", delta_tone(total["Net Financial Delta"]), short=True)
with row2[4]:
    render_kpi("Economic All-In Saving / Impact", format_money(total["Economic All-In Delta"], currency_symbol, compact=True, signed=True), "Spend + net financial effect + inventory carrying", delta_tone(total["Economic All-In Delta"]), short=True)
with row2[5]:
    render_kpi("Weighted Risk", f"{total['Weighted Risk']:.2f}/5", "Lower is better", risk_tone(total["Weighted Risk"]), short=True)

brazil_row = group_df[group_df["Group"] == "Brazil"].iloc[0]
latam_row = group_df[group_df["Group"] == "LATAM"].iloc[0]

render_visual_breaker('Brazil result', 'Country-level result and impact drivers for Brazil, including payment-term movement.', '🇧🇷', '#06b6d4', 'Country view')
row3 = st.columns(7)
with row3[0]:
    render_kpi("Current Avg Payment Term", f"{brazil_row['Current Avg Payment Days']:.0f} dd", "Current baseline payment term", "neutral", short=True)
with row3[1]:
    render_kpi("New Proposal Avg Payment Term", f"{brazil_row['New Avg Payment Days']:.0f} dd", "Share-weighted proposed payment term", "neutral", short=True)
with row3[2]:
    render_kpi("Spend Saving / Impact", format_money(brazil_row["Spend Delta"], currency_symbol, compact=True, signed=True), "Brazil new spend - current spend", delta_tone(brazil_row["Spend Delta"]), short=True)
with row3[3]:
    render_kpi("Gross Financial Saving / Impact", format_money(brazil_row["Financial Delta"], currency_symbol, compact=True, signed=True), "Brazil gross financial cost delta", delta_tone(brazil_row["Financial Delta"]), short=True)
with row3[4]:
    render_kpi("Treasury Return Offset", format_money(brazil_row["Treasury Return Offset Delta"], currency_symbol, compact=True, signed=True), "Brazil current return - new return", delta_tone(brazil_row["Treasury Return Offset Delta"]), short=True)
with row3[5]:
    render_kpi("Net Financial Saving / Impact", format_money(brazil_row["Net Financial Delta"], currency_symbol, compact=True, signed=True), "Brazil net financial effect after treasury return", delta_tone(brazil_row["Net Financial Delta"]), short=True)
with row3[6]:
    render_kpi("Economic All-In Saving / Impact", format_money(brazil_row["Economic All-In Delta"], currency_symbol, compact=True, signed=True), "Brazil spend + net financial effect + inventory", delta_tone(brazil_row["Economic All-In Delta"]), short=True)

render_visual_breaker('LATAM result', 'Consolidated Mexico, Argentina and Colombia impact view, including payment-term movement.', '🌎', '#ec4899', 'Regional view')
row4 = st.columns(7)
with row4[0]:
    render_kpi("Current Avg Payment Term", f"{latam_row['Current Avg Payment Days']:.0f} dd", "Current baseline payment term", "neutral", short=True)
with row4[1]:
    render_kpi("New Proposal Avg Payment Term", f"{latam_row['New Avg Payment Days']:.0f} dd", "Share-weighted proposed payment term", "neutral", short=True)
with row4[2]:
    render_kpi("Spend Saving / Impact", format_money(latam_row["Spend Delta"], currency_symbol, compact=True, signed=True), "LATAM new spend - current spend", delta_tone(latam_row["Spend Delta"]), short=True)
with row4[3]:
    render_kpi("Gross Financial Saving / Impact", format_money(latam_row["Financial Delta"], currency_symbol, compact=True, signed=True), "LATAM gross financial cost delta", delta_tone(latam_row["Financial Delta"]), short=True)
with row4[4]:
    render_kpi("Treasury Return Offset", format_money(latam_row["Treasury Return Offset Delta"], currency_symbol, compact=True, signed=True), "LATAM current return - new return", delta_tone(latam_row["Treasury Return Offset Delta"]), short=True)
with row4[5]:
    render_kpi("Net Financial Saving / Impact", format_money(latam_row["Net Financial Delta"], currency_symbol, compact=True, signed=True), "LATAM net financial effect after treasury return", delta_tone(latam_row["Net Financial Delta"]), short=True)
with row4[6]:
    render_kpi("Economic All-In Saving / Impact", format_money(latam_row["Economic All-In Delta"], currency_symbol, compact=True, signed=True), "LATAM spend + net financial effect + inventory", delta_tone(latam_row["Economic All-In Delta"]), short=True)

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
        decomp_names = ["Spend Delta", "Net Financial Delta", "Inventory Delta", "Economic Delta"]
        decomp_vals = [total["Spend Delta"], total["Net Financial Delta"], total["Inventory Delta"], total["Economic All-In Delta"]]
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
        st.bar_chart(pd.DataFrame({"Delta": [total["Spend Delta"], total["Net Financial Delta"], total["Inventory Delta"], total["Economic All-In Delta"]]}, index=["Spend", "Net Financial", "Inventory", "Economic"]))

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
        render_kpi("Current Capital Gain", format_money(total["Current Capital Gain"], currency_symbol, compact=True), "Uses current payment terms by country", "good", short=True)
    with econ_cols[1]:
        render_kpi("New Capital Gain", format_money(total["New Capital Gain"], currency_symbol, compact=True), f"Uses supplier payment terms | avg {total.get("New Avg Return Days", 0):.0f}dd", "good", short=True)
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
    for col in ["Weighted Risk", "Current Effective Financial Rate", "New Avg Financial Rate", "Current Effective Treasury Rate", "New Avg Treasury Rate"]:
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
        Note: Gross financial cost is intentionally separated from treasury return offset. Net Financial Saving / Impact is the correct finance view after working-capital carry is considered.
        Finance/Treasury should validate financial and treasury-return assumptions before any official saving recognition.
    </div>
    """,
    unsafe_allow_html=True,
)
