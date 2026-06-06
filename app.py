"""
Executive Procurement TCO & Should-Cost Dashboard
Version v39 - Dynamic Country Scope + Visual Market Selector

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
- Direct Materials mode calculates spend from landed unit price x volume before TCO analysis
- Indirect / Services mode calculates service TCO with scope, pricing model, headcount/hour economics, scorecards, overtime KPIs, should-cost, productivity gains and contract leakage

Key modeling guardrails
-----------------------
1. Supplier proposal spend is a 100% volume-equivalent spend, before financial cost.
2. Current baseline is never recalculated using proposal terms.
3. Proposal financial cost and treasury return use each supplier proposed payment term.
4. Negative deltas mean savings; positive deltas mean cost impact.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from html import escape
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

DEFAULT_ACTIVE_COUNTRIES = ["Brazil", "Mexico", "Argentina", "Colombia"]
COUNTRY_OPTIONS = [
    "Brazil", "Mexico", "Argentina", "Colombia", "Chile", "Peru", "Uruguay", "Paraguay",
    "Ecuador", "Bolivia", "Costa Rica", "Guatemala", "Panama", "Dominican Republic",
    "United States", "Canada", "China", "India", "Germany", "France", "Spain", "Italy",
    "Netherlands", "United Kingdom", "Japan", "South Korea", "Thailand", "Indonesia", "Malaysia",
]
COUNTRIES = DEFAULT_ACTIVE_COUNTRIES.copy()
PRIMARY_COUNTRY = "Brazil"
SECONDARY_GROUP = "LATAM"
LATAM_COUNTRIES = ["Mexico", "Argentina", "Colombia"]
SUPPLIERS = [
    "ChemPrime",
    "OleoGlobal",
    "Oleo Overseas Trading Co.",
    "Comercio de Oleos Nacional Distribuicao",
    "Supplier 05",
    "Supplier 06",
    "Supplier 07",
    "Supplier 08",
    "Supplier 09",
    "Supplier 10",
    "Supplier 11",
    "Supplier 12",
    "Supplier 13",
    "Supplier 14",
    "Supplier 15",
]
SUPPLIER_POOL = SUPPLIERS.copy()
SHORT_SUPPLIER = {
    "ChemPrime": "ChemPrime",
    "OleoGlobal": "OleoGlobal",
    "Oleo Overseas Trading Co.": "Overseas",
    "Comercio de Oleos Nacional Distribuicao": "Distribuicao",
    "Supplier 05": "Supplier 05",
    "Supplier 06": "Supplier 06",
    "Supplier 07": "Supplier 07",
    "Supplier 08": "Supplier 08",
    "Supplier 09": "Supplier 09",
    "Supplier 10": "Supplier 10",
    "Supplier 11": "Supplier 11",
    "Supplier 12": "Supplier 12",
    "Supplier 13": "Supplier 13",
    "Supplier 14": "Supplier 14",
    "Supplier 15": "Supplier 15",
}

# Supplier IDs remain fixed internally so calculations, widget keys and saved scenarios
# do not break. These editable display labels are what users see throughout the app.
DEFAULT_SUPPLIER_DISPLAY_NAME = {supplier: supplier for supplier in SUPPLIERS}
DEFAULT_SUPPLIER_SHORT_NAME = SHORT_SUPPLIER.copy()

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

# Direct materials landed-cost defaults. Spend is calculated as landed unit price x volume.
DEFAULT_ITEM_NAME = "Isopropyl Palmitate"
DEFAULT_NEGOTIATED_UNIT = "kg"
CURRENCY_OPTIONS = ["BRL", "USD", "EUR", "MXN", "ARS", "COP", "CNY"]
INCOTERM_OPTIONS = ["EXW", "FCA", "FOB", "CFR", "CIF", "DAP", "DDP"]
DEFAULT_DIRECT_VOLUME = {
    "Brazil": 1_000_000.0,
    "Mexico": 250_000.0,
    "Argentina": 200_000.0,
    "Colombia": 125_000.0,
}
DEFAULT_DIRECT_CURRENCY = {
    "Brazil": "BRL",
    "Mexico": "USD",
    "Argentina": "USD",
    "Colombia": "USD",
}
DEFAULT_FX_TO_REPORTING = {
    "BRL": 1.0,
    "USD": 5.30,
    "EUR": 5.75,
    "MXN": 0.30,
    "ARS": 0.0045,
    "COP": 0.00135,
    "CNY": 0.73,
}
LANDED_COST_COMPONENTS = [
    ("base_unit_price", "Base / quoted unit price"),
    ("conversion_cost", "Conversion cost"),
    ("fixed_margin", "Fixed margin"),
    ("international_freight", "International freight"),
    ("insurance", "Insurance"),
    ("customs_fees", "Customs / brokerage fees"),
    ("import_duties_taxes", "Import duties / taxes"),
    ("domestic_freight", "Domestic freight"),
    ("local_taxes", "Local taxes"),
]


# Indirect / Services executive cockpit defaults. Services are modeled by scope,
# pricing model, contract leakage, performance scorecard, risk and productivity gain.
SERVICE_SCOPES = [
    "IT Services / Digital & Outsourcing",
    "Facilities / Cleaning & Workplace",
    "Industrial MRO / VMI / Fastenal-style outsourcing",
    "Professional Services / Consulting",
    "Marketing / Agency Services",
    "Logistics / Transport Services",
    "BPO / Call Center",
    "Generic Indirect Service",
]
SERVICE_SCOPE_CONFIG = {
    "IT Services / Digital & Outsourcing": {
        "icon": "💻",
        "pricing_models": ["T&M rate card", "FTE-based outsourcing", "Fixed fee project", "Managed service SLA"],
        "driver_label": "tickets, sprints, users or FTE-months",
        "productivity_label": "automation, ticket deflection, cycle-time reduction or engineering velocity gain",
        "field_labels": ["FTEs / squad members", "Tickets or story points / month", "Critical systems covered"],
    },
    "Facilities / Cleaning & Workplace": {
        "icon": "🏢",
        "pricing_models": ["Rate per m²", "Fixed monthly fee", "FTE-based service", "Unit visit rate"],
        "driver_label": "m², sites, visits or headcount served",
        "productivity_label": "frequency optimization, route density, material consumption reduction or supervision productivity",
        "field_labels": ["Area serviced (m²)", "Sites / buildings", "Service frequency / month"],
    },
    "Industrial MRO / VMI / Fastenal-style outsourcing": {
        "icon": "🧰",
        "pricing_models": ["VMI managed service fee", "Cost plus fee", "Unit transaction fee", "FTE-based onsite service"],
        "driver_label": "SKUs, transactions, sites, vending machines or tool-crib workload",
        "productivity_label": "inventory reduction, stockout avoidance, technician productivity, tool-crib automation or consumption control",
        "field_labels": ["Managed SKUs", "Transactions / month", "Sites / vending points"],
    },
    "Professional Services / Consulting": {
        "icon": "🧠",
        "pricing_models": ["Fixed fee project", "T&M rate card", "Retainer", "Success fee"],
        "driver_label": "milestones, consultant days, workstreams or deliverables",
        "productivity_label": "faster implementation, capability transfer, reduced internal effort or measurable business impact",
        "field_labels": ["Senior consultant days", "Analyst / consultant days", "Milestones / deliverables"],
    },
    "Marketing / Agency Services": {
        "icon": "🎯",
        "pricing_models": ["Monthly retainer", "Project fee", "Pass-through + agency fee", "Rate card"],
        "driver_label": "campaigns, assets, production jobs, media pass-through or usage rights",
        "productivity_label": "asset reuse, lower rework, campaign cycle-time reduction or media efficiency",
        "field_labels": ["Campaigns / month", "Assets / deliverables", "Media pass-through budget"],
    },
    "Logistics / Transport Services": {
        "icon": "🚚",
        "pricing_models": ["Rate per shipment", "Dedicated route / vehicle", "Cost plus fee", "SLA-based logistics service"],
        "driver_label": "shipments, km, routes, pallets or dedicated vehicles",
        "productivity_label": "load factor improvement, route optimization, fewer expedites or warehouse throughput gain",
        "field_labels": ["Shipments / month", "Average km or routes", "Dedicated vehicles / lanes"],
    },
    "BPO / Call Center": {
        "icon": "🎧",
        "pricing_models": ["FTE-based", "Cost per contact", "SLA-based managed service", "Outcome-based"],
        "driver_label": "contacts, calls, cases, FTEs or resolved transactions",
        "productivity_label": "AHT reduction, containment, automation, first-contact resolution or lower escalation rate",
        "field_labels": ["Contacts / month", "FTEs", "Target AHT / productivity index"],
    },
    "Generic Indirect Service": {
        "icon": "🧾",
        "pricing_models": ["Fixed fee", "T&M rate card", "Unit rate", "Retainer", "Pass-through + fee"],
        "driver_label": "service units, hours, FTEs, projects or sites",
        "productivity_label": "supplier-led productivity, demand reduction, process improvement or service efficiency",
        "field_labels": ["Service units", "Hours / month", "Sites / users covered"],
    },
}
SERVICE_SCORECARD_WEIGHTS = {
    "Cost competitiveness": 18.0,
    "SLA / Delivery": 18.0,
    "Quality of service": 14.0,
    "Stakeholder satisfaction": 12.0,
    "Contract compliance": 10.0,
    "Productivity / Innovation": 10.0,
    "Overtime control": 8.0,
    "Risk & compliance": 5.0,
    "ESG / diversity": 5.0,
}


SUPPLIER_GOVERNANCE_WEIGHTS = {
    "OTIF / SLA delivery": 18.0,
    "Quality / NCR performance": 15.0,
    "Financial health": 12.0,
    "Compliance / due diligence": 15.0,
    "ESG / ethics": 10.0,
    "Cyber / data security": 8.0,
    "Labor / HSE": 10.0,
    "Stakeholder satisfaction": 12.0,
}
DUE_DILIGENCE_STATUS_OPTIONS = ["Clear", "Minor gaps", "Material gaps", "Not approved"]
CUSTOM_FACTOR_TYPES = [
    "Cost add-on",
    "Cost reduction / saving",
    "Productivity gain",
    "Risk increase",
    "Risk reduction",
    "Score bonus / penalty",
]
CUSTOM_FACTOR_COUNTRIES = ["All countries"] + COUNTRIES
SERVICE_OPEN_COST_COMPONENTS = [
    ("labor", "Labor / delivery team"),
    ("supervision", "Supervision / management"),
    ("tools", "Tools / licenses / equipment"),
    ("training", "Training / onboarding"),
    ("materials", "Consumables / materials"),
    ("subcontractors", "Subcontractors / partners"),
    ("travel_expenses", "Travel / expenses"),
    ("transition", "Transition / implementation"),
    ("risk_buffer", "Risk / contingency buffer"),
    ("overhead", "Supplier overhead"),
    ("margin", "Supplier margin"),
]
DEFAULT_SERVICE_SCOPE = "IT Services / Digital & Outsourcing"
DEFAULT_SERVICE_PRICING_MODEL = "FTE-based outsourcing"
DEFAULT_SERVICE_CONTRACT_VALUE = {
    "Brazil": 13_000_000.0,
    "Mexico": 3_000_000.0,
    "Argentina": 2_500_000.0,
    "Colombia": 1_500_000.0,
}

# Light country templates keep the experience simple: users select countries visually,
# while the app auto-seeds practical defaults that can be refined in the country cards.
COUNTRY_DEFAULT_TEMPLATE = {
    "current_spend": 1_000_000.0,
    "financial_rate": 3.0,
    "reference_days": 60,
    "current_term": 60,
    "treasury_return": 2.0,
    "treasury_ref_days": 60,
    "inventory_carry_rate": 20.0,
    "current_inventory_days": 30,
    "direct_volume": 100_000.0,
    "direct_currency": "USD",
    "service_contract_value": 1_000_000.0,
}
COUNTRY_PRESET_OVERRIDES = {
    "Brazil": {"current_spend": 13_000_000.0, "financial_rate": 4.84, "reference_days": 120, "current_term": 120, "treasury_return": 5.07, "treasury_ref_days": 120, "inventory_carry_rate": 23.0, "direct_volume": 1_000_000.0, "direct_currency": "BRL", "service_contract_value": 13_000_000.0},
    "Mexico": {"current_spend": 3_000_000.0, "financial_rate": 2.32, "current_term": 60, "treasury_return": 2.50, "inventory_carry_rate": 15.0, "direct_volume": 250_000.0, "service_contract_value": 3_000_000.0},
    "Argentina": {"current_spend": 2_500_000.0, "financial_rate": 10.52, "current_term": 60, "treasury_return": 10.90, "inventory_carry_rate": 35.0, "direct_volume": 200_000.0, "service_contract_value": 2_500_000.0},
    "Colombia": {"current_spend": 1_500_000.0, "financial_rate": 3.07, "current_term": 60, "treasury_return": 3.40, "inventory_carry_rate": 22.0, "direct_volume": 125_000.0, "service_contract_value": 1_500_000.0},
    "Chile": {"current_spend": 1_250_000.0, "financial_rate": 2.20, "treasury_return": 1.60, "inventory_carry_rate": 18.0, "direct_volume": 100_000.0, "service_contract_value": 1_250_000.0},
    "Peru": {"current_spend": 1_000_000.0, "financial_rate": 2.40, "treasury_return": 1.70, "inventory_carry_rate": 20.0, "direct_volume": 90_000.0, "service_contract_value": 1_000_000.0},
    "United States": {"current_spend": 2_500_000.0, "financial_rate": 1.70, "treasury_return": 1.20, "inventory_carry_rate": 17.0, "direct_volume": 200_000.0, "direct_currency": "USD", "service_contract_value": 2_500_000.0},
    "China": {"current_spend": 2_000_000.0, "financial_rate": 1.40, "treasury_return": 0.90, "inventory_carry_rate": 16.0, "direct_volume": 200_000.0, "direct_currency": "USD", "service_contract_value": 2_000_000.0},
    "Germany": {"current_spend": 1_800_000.0, "financial_rate": 1.30, "treasury_return": 0.80, "inventory_carry_rate": 16.0, "direct_volume": 150_000.0, "direct_currency": "EUR", "service_contract_value": 1_800_000.0},
    "United Kingdom": {"current_spend": 1_600_000.0, "financial_rate": 1.50, "treasury_return": 0.90, "inventory_carry_rate": 17.0, "direct_volume": 140_000.0, "direct_currency": "EUR", "service_contract_value": 1_600_000.0},
}


def seed_country_defaults(country: str) -> None:
    base = COUNTRY_DEFAULT_TEMPLATE.copy()
    base.update(COUNTRY_PRESET_OVERRIDES.get(country, {}))
    DEFAULT_CURRENT_SPEND.setdefault(country, float(base["current_spend"]))
    DEFAULT_FINANCIAL_RATE.setdefault(country, float(base["financial_rate"]))
    DEFAULT_REFERENCE_DAYS.setdefault(country, int(base["reference_days"]))
    DEFAULT_CURRENT_TERM.setdefault(country, int(base["current_term"]))
    DEFAULT_TREASURY_RETURN.setdefault(country, float(base["treasury_return"]))
    DEFAULT_TREASURY_REF_DAYS.setdefault(country, int(base["treasury_ref_days"]))
    DEFAULT_INVENTORY_CARRY_RATE.setdefault(country, float(base["inventory_carry_rate"]))
    DEFAULT_CURRENT_INVENTORY_DAYS.setdefault(country, int(base["current_inventory_days"]))
    DEFAULT_DIRECT_VOLUME.setdefault(country, float(base["direct_volume"]))
    DEFAULT_DIRECT_CURRENCY.setdefault(country, str(base["direct_currency"]))
    DEFAULT_SERVICE_CONTRACT_VALUE.setdefault(country, float(base["service_contract_value"]))


for _country_option in COUNTRY_OPTIONS:
    seed_country_defaults(_country_option)

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

# Extend all default dictionaries to support a dynamic supplier universe up to 15 suppliers.
# First four suppliers keep the original business-case defaults; the additional suppliers
# start as approved, zero-share alternatives with conservative generic assumptions.
for _supplier in SUPPLIER_POOL:
    DEFAULT_SUPPLIER_DISPLAY_NAME.setdefault(_supplier, _supplier)
    DEFAULT_SUPPLIER_SHORT_NAME.setdefault(_supplier, SHORT_SUPPLIER.get(_supplier, _supplier))
    DEFAULT_KRALJIC_REQUIRED.setdefault(_supplier, False)
    DEFAULT_MIN_SHARE.setdefault(_supplier, 0.0)
    DEFAULT_MAX_SHARE.setdefault(_supplier, 100.0)
    DEFAULT_APPROVED.setdefault(_supplier, True)
    DEFAULT_RISK.setdefault(_supplier, {dim: 3.0 for dim in DEFAULT_RISK_WEIGHTS})

for _country in COUNTRY_OPTIONS:
    seed_country_defaults(_country)
    _base_spend = DEFAULT_CURRENT_SPEND[_country]
    DEFAULT_PROPOSAL_SPEND.setdefault(_country, {})
    DEFAULT_PAYMENT_TERM.setdefault(_country, {})
    DEFAULT_LEAD_TIME_DAYS.setdefault(_country, {})
    DEFAULT_SAFETY_STOCK_DAYS.setdefault(_country, {})
    DEFAULT_INVENTORY_OWNERSHIP.setdefault(_country, {})
    DEFAULT_SHARES.setdefault(_country, {})
    for _idx, _supplier in enumerate(SUPPLIER_POOL, start=1):
        DEFAULT_PROPOSAL_SPEND[_country].setdefault(_supplier, _base_spend)
        DEFAULT_PAYMENT_TERM[_country].setdefault(_supplier, DEFAULT_CURRENT_TERM[_country])
        DEFAULT_LEAD_TIME_DAYS[_country].setdefault(_supplier, 30)
        DEFAULT_SAFETY_STOCK_DAYS[_country].setdefault(_supplier, 0)
        DEFAULT_INVENTORY_OWNERSHIP[_country].setdefault(_supplier, "Supplier/trader owns until delivery")
        DEFAULT_SHARES[_country].setdefault(_supplier, 0.0)

GRAPHITE = "#1f2937"
GREEN = "#047857"
RED = "#b91c1c"
BLUE = "#1d4ed8"
AMBER = "#b45309"

RESULT_STACK_OPTIONS = [
    "Top supplier focus lens",
    "Total project saving",
    "AI Executive Copilot",
    "Total cost stack",
    "Reference supplier condition stack",
    "Working capital carry view",
    "Total decomposition",
    "Brazil result",
    "LATAM result",
    "Decision recommendation",
    "Charts",
    "Working capital economic view",
    "Detailed data",
    "Download export",
]
DEFAULT_RESULT_STACKS = [
    "Top supplier focus lens",
    "Total project saving",
    "AI Executive Copilot",
    "Total decomposition",
    "Brazil result",
    "LATAM result",
    "Charts",
    "Download export",
]

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
        @keyframes fadeUp { from {opacity:0; transform: translateY(10px);} to {opacity:1; transform: translateY(0);} }
        @keyframes subtlePulse { 0% {box-shadow:0 12px 28px rgba(15,23,42,.08);} 50% {box-shadow:0 16px 34px rgba(15,23,42,.13);} 100% {box-shadow:0 12px 28px rgba(15,23,42,.08);} }
        .block-container {padding-top: 1.0rem; padding-bottom: 2.4rem; max-width: 1680px;}
        .executive-hero {
            background: linear-gradient(135deg, #020617 0%, #0f172a 48%, #1d4ed8 100%);
            padding: 32px 36px; border-radius: 30px; color: white; margin-bottom: 24px;
            box-shadow: 0 20px 55px rgba(15, 23, 42, 0.28); animation: fadeUp .45s ease-out both;
        }
        .hero-direct {background: radial-gradient(circle at top right, rgba(96,165,250,.42), transparent 30%), linear-gradient(135deg, #020617 0%, #0f172a 48%, #1d4ed8 100%);}
        .hero-service {background: radial-gradient(circle at top right, rgba(168,85,247,.40), transparent 30%), linear-gradient(135deg, #111827 0%, #312e81 48%, #7c3aed 100%);}
        .mode-chip {display:inline-block; padding:7px 12px; border-radius:999px; background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.18); color:#fff; font-size:.76rem; font-weight:900; letter-spacing:.06em; text-transform:uppercase; margin-bottom:10px;}
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
            background: #ffffff; border: 1px solid rgba(148, 163, 184, 0.26); border-radius: 24px;
            padding: 22px 23px; min-height: 168px; height: 168px; box-sizing: border-box;
            margin-bottom: 24px; box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
            display: flex; flex-direction: column; justify-content: flex-start; animation: fadeUp .35s ease-out both;
            transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
        }
        .kpi-card:hover {transform: translateY(-3px); box-shadow: 0 18px 40px rgba(15,23,42,.14); border-color: rgba(59,130,246,.32);}
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
        .mode-card {background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%); border: 1px solid rgba(96,165,250,.35); border-radius: 18px; padding: 14px 15px; margin: 8px 0 14px 0; color: white; box-shadow: 0 10px 28px rgba(15,23,42,.20);}
        .mode-card-title {font-weight: 900; font-size: .95rem; color: #ffffff; margin-bottom: 2px;}
        .mode-card-subtitle {font-size: .78rem; color: #dbeafe; line-height: 1.25;}
        .market-scope-card {background: linear-gradient(135deg, rgba(14,165,233,.18), rgba(124,58,237,.18)); border:1px solid rgba(125,211,252,.28); border-radius:20px; padding:14px 15px; margin: 10px 0 16px 0; color:#e0f2fe; box-shadow: 0 12px 30px rgba(2,6,23,.18);}
        .market-scope-title {font-weight:900; color:#ffffff; font-size:.95rem; margin-bottom:4px;}
        .market-scope-meta {font-size:.78rem; color:#bae6fd; line-height:1.28;}
        .market-chip {display:inline-block; padding:4px 8px; margin: 4px 4px 0 0; border-radius:999px; background:rgba(255,255,255,.10); border:1px solid rgba(255,255,255,.15); color:#f8fafc; font-size:.72rem; font-weight:800;}
        .landed-result {background:#f8fafc; border:1px dashed rgba(37,99,235,.35); border-radius:14px; padding:10px 12px; margin-top:8px;}
        .landed-result b {color:#0f172a;}
        .service-result {background:#f8fafc; border:1px dashed rgba(124,58,237,.35); border-radius:14px; padding:10px 12px; margin-top:8px;}
        .service-result b {color:#0f172a;}
        .score-badge {display:inline-block; padding:4px 9px; border-radius:999px; font-weight:850; font-size:.76rem; background:#eef2ff; color:#3730a3;}
        .executive-panel {background:rgba(255,255,255,.78); border:1px solid rgba(148,163,184,.28); border-radius:24px; padding:18px 20px; margin:16px 0 22px 0; box-shadow:0 10px 30px rgba(15,23,42,.07); animation:fadeUp .38s ease-out both;}
        .direct-accent {border-left:6px solid #2563eb;}
        .service-accent {border-left:6px solid #7c3aed;}
        .chart-shell {background:#ffffff; border:1px solid rgba(148,163,184,.24); border-radius:24px; padding:12px 14px; box-shadow:0 12px 30px rgba(15,23,42,.07); animation: fadeUp .42s ease-out both;}
        div[data-testid="stMetricValue"] {font-weight:900;}
        div[data-testid="stExpander"] {border-radius:18px !important;}

        /* v36 visual lock: keep executive components aligned and consistently framed */
        .kpi-card { overflow: hidden; }
        .kpi-value { min-height: 36px; display: flex; align-items: center; }
        .kpi-helper { min-height: 40px; overflow: hidden; }
        .executive-panel { min-height: 128px; overflow: hidden; }
        .visual-breaker { min-height: 76px; box-sizing: border-box; }
        .chart-shell { min-height: 480px; overflow: hidden; }
        .chart-shell h4 { margin: 0 0 8px 0; color: #0f172a; }
        div[data-testid="stHorizontalBlock"] { align-items: stretch; }
        div[data-testid="column"] > div { height: 100%; }
        div[data-testid="stDataFrame"] { border-radius: 18px; overflow: hidden; border: 1px solid rgba(148,163,184,.25); }
        .ai-copilot-card {
            background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid rgba(99,102,241,.28); border-left: 7px solid #6366f1; border-radius: 24px;
            padding: 20px 22px; margin: 12px 0 20px 0; box-shadow: 0 14px 34px rgba(15,23,42,.09);
        }
        .ai-copilot-card h4 {margin: 0 0 8px 0; color:#0f172a;}
        .ai-copilot-card ul {margin-top: 8px; margin-bottom: 0;}
        .ai-copilot-card li {margin-bottom: 6px; color:#334155; line-height:1.34;}
        .stack-control-note {font-size:.78rem; color:#94a3b8; line-height:1.25;}
        .stack-caption {
            margin: 2px 0 12px 0; padding: 10px 13px; border-radius: 14px;
            border-left: 5px solid var(--accent); background: rgba(248,250,252,.88);
            color:#475569; font-size:.84rem; line-height:1.35;
        }
        div[data-testid="stExpander"] {
            border: 1px solid rgba(148,163,184,.28) !important; border-radius: 22px !important;
            margin: 18px 0 22px 0 !important; overflow: hidden !important;
            box-shadow: 0 14px 34px rgba(15,23,42,.08); background: rgba(255,255,255,.045);
        }
        div[data-testid="stExpander"] details summary {
            min-height: 48px; padding: 12px 18px !important; font-weight: 900 !important;
            color: #e2e8f0 !important; background: linear-gradient(135deg, rgba(15,23,42,.96), rgba(30,41,59,.88));
            letter-spacing: .01em;
        }
        div[data-testid="stExpander"] details[open] summary {border-bottom: 1px solid rgba(148,163,184,.20);}


        /* v38 enterprise visual lock: tighter spacing, equalized inputs and cleaner empty whitespace */
        .plain-title {margin-top: 24px !important; margin-bottom: 12px !important; line-height: 1.25;}
        .section-header {margin-top: 16px !important; margin-bottom: 24px !important;}
        div[data-testid="stAlert"] {margin: 16px 0 20px 0 !important; border-radius: 16px !important;}
        div[data-testid="stForm"] {border-radius: 18px !important;}
        .stNumberInput label, .stTextInput label, .stSelectbox label, .stSlider label, .stTextArea label, .stCheckbox label {
            min-height: 42px !important; display: flex !important; align-items: flex-end !important;
            line-height: 1.18 !important; font-weight: 750 !important;
        }
        div[data-testid="stNumberInput"] input, div[data-testid="stTextInput"] input {min-height: 40px !important;}
        div[data-testid="stVerticalBlock"] {gap: 0.72rem !important;}
        div[data-testid="stHorizontalBlock"] {gap: 1.02rem !important; align-items: stretch !important;}
        div[data-testid="column"] {min-width: 0 !important;}
        div[data-testid="column"] > div {height: auto !important;}
        .kpi-card {min-height: 146px !important; height: auto !important; padding: 20px 22px !important;}
        .kpi-card.short {min-height: 128px !important; height: auto !important;}
        .kpi-value {min-height: 30px !important;}
        .kpi-helper {min-height: 26px !important; overflow: visible !important;}
        .supplier-box {padding: 18px 18px 20px 18px !important; margin: 14px 0 18px 0 !important; background: rgba(255,255,255,.03) !important;}
        .service-result, .landed-result {margin: 14px 0 18px 0 !important; line-height: 1.45 !important;}
        .chart-shell {min-height: 450px !important; padding: 18px 18px 12px 18px !important; margin-bottom: 22px !important; animation: chartReveal .72s ease-out both;}
        @keyframes chartReveal { from {opacity:0; transform: translateY(18px) scale(.985);} to {opacity:1; transform: translateY(0) scale(1);} }
        .governance-card, .custom-factor-card, .open-cost-card {
            background: rgba(255,255,255,.06); border: 1px solid rgba(148,163,184,.24); border-radius: 22px;
            padding: 18px 18px 20px 18px; margin: 16px 0 20px 0; box-shadow: 0 10px 28px rgba(2,6,23,.12);
        }
        .matrix-header {font-size:.88rem; color:#cbd5e1; font-weight:850; margin: 10px 0 6px 0;}
        .supplier-expander-note {font-size:.78rem; color:#94a3b8; margin-top:-5px; margin-bottom:8px;}
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


def format_quantity(value: float, unit: str = "") -> str:
    unit_suffix = f" {unit}" if unit else ""
    return f"{float(value):,.0f}{unit_suffix}"


def landed_unit_price(components: Dict[str, float], fx_rate: float = 1.0) -> float:
    """Convert a direct-material unit cost build-up to reporting currency.

    All component inputs are assumed to be per negotiated unit in the quote currency.
    The FX rate converts 1 quote-currency unit into the dashboard reporting currency.
    """
    return sum(float(components.get(key, 0.0)) for key, _ in LANDED_COST_COMPONENTS) * float(fx_rate)


def default_unit_price_from_spend(spend: float, volume: float) -> float:
    return safe_divide(float(spend), max(float(volume), 1e-9))


def collect_component_values(prefix: str, defaults: Dict[str, float] | None = None) -> Dict[str, float]:
    defaults = defaults or {}
    return {key: float(defaults.get(key, 0.0)) for key, _ in LANDED_COST_COMPONENTS}


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
        margin=dict(l=30, r=24, t=62, b=44),
        bargap=0.28,
        modebar=dict(remove=["lasso2d", "select2d"]),
        xaxis=dict(title_font=dict(color=GRAPHITE), tickfont=dict(color=GRAPHITE), color=GRAPHITE, gridcolor="rgba(31,41,55,.12)"),
        yaxis=dict(title_font=dict(color=GRAPHITE), tickfont=dict(color=GRAPHITE), color=GRAPHITE, gridcolor="rgba(31,41,55,.12)"),
        legend=dict(font=dict(color=GRAPHITE)),
        transition=dict(duration=850, easing="cubic-in-out"),
        hovermode="x unified",
    )
    for tr in fig.data:
        if hasattr(tr, "textfont"):
            tr.textfont = dict(color=GRAPHITE)
        if hasattr(tr, "insidetextfont"):
            tr.insidetextfont = dict(color=GRAPHITE)
        if hasattr(tr, "outsidetextfont"):
            tr.outsidetextfont = dict(color=GRAPHITE)
    try:
        fig.update_traces(opacity=0.94, marker_line_width=0)
    except Exception:
        pass
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


def _safe_group_row(group_df: pd.DataFrame, group: str) -> Dict[str, float]:
    if group_df is None or group_df.empty or "Group" not in group_df.columns:
        return {}
    rows = group_df[group_df["Group"] == group]
    if rows.empty:
        return {}
    return rows.iloc[0].to_dict()


def build_ai_prompt_payload(
    *,
    analysis_mode: str,
    total: Dict[str, float],
    group_df: pd.DataFrame,
    supplier_focus_df: pd.DataFrame,
    focused_supplier_count: int,
    currency: str,
) -> str:
    """Create a compact copy/paste prompt for an external AI tool.

    The app does not call an external AI API. This payload is the controlled
    context that would be pasted into an AI assistant or used by a future API integration.
    """
    primary = _safe_group_row(group_df, PRIMARY_COUNTRY)
    secondary = _safe_group_row(group_df, SECONDARY_GROUP)
    focus = supplier_focus_df.head(focused_supplier_count) if isinstance(supplier_focus_df, pd.DataFrame) else pd.DataFrame()
    focus_lines = []
    if not focus.empty:
        for _, row in focus.iterrows():
            extra = ""
            if analysis_mode == "Indirect / Services" and pd.notna(row.get("Performance Score", None)):
                extra = f" | Performance score: {row.get('Performance Score', 0):.1f}/100 | Productivity gain: {currency} {row.get('Productivity Gain', 0):,.2f} | Overtime h/mo: {row.get('Overtime Hours / Month', 0):,.1f}"
            focus_lines.append(
                f"#{int(row.get('Rank', 0))} {row.get('Supplier','')} | Economic total: {currency} {row.get('Economic Total',0):,.2f} | Risk: {row.get('Risk Score',0):.2f}/5{extra}"
            )
    return "\n".join([
        "Act as a senior executive procurement advisor. Provide a concise, decision-oriented recommendation.",
        f"Analysis mode: {analysis_mode}",
        f"Gross total saving/impact: {currency} {total.get('Gross All-In Delta', 0):,.2f}",
        f"Working capital gain/impact: {currency} {total.get('Treasury Return Offset Delta', 0):,.2f}",
        f"Inventory carrying delta: {currency} {total.get('Inventory Delta', 0):,.2f}",
        f"Final economic all-in saving/impact: {currency} {total.get('Economic All-In Delta', 0):,.2f}",
        f"Weighted risk: {total.get('Weighted Risk', 0):.2f}/5",
        f"{PRIMARY_COUNTRY} economic delta: {currency} {primary.get('Economic All-In Delta', 0):,.2f}; current term {primary.get('Current Avg Payment Days', 0):.0f} dd; new term {primary.get('New Avg Payment Days', 0):.0f} dd",
        f"{SECONDARY_GROUP} economic delta: {currency} {secondary.get('Economic All-In Delta', 0):,.2f}; current term {secondary.get('Current Avg Payment Days', 0):.0f} dd; new term {secondary.get('New Avg Payment Days', 0):.0f} dd",
        "Top supplier focus:",
        *focus_lines,
        "Return: recommendation, best option, risk watchouts, negotiation levers and next actions. Keep it short.",
    ])


def generate_ai_executive_brief(
    *,
    analysis_mode: str,
    total: Dict[str, float],
    group_df: pd.DataFrame,
    supplier_focus_df: pd.DataFrame,
    focused_supplier_count: int,
    currency: str,
) -> str:
    """Local AI-style executive brief.

    This is intentionally concise and deterministic until a real AI API key/integration
    is connected. It reads the same data that would be sent to an AI assistant.
    """
    final_delta = float(total.get("Economic All-In Delta", 0.0))
    gross_delta = float(total.get("Gross All-In Delta", 0.0))
    wc_delta = float(total.get("Treasury Return Offset Delta", 0.0))
    inv_delta = float(total.get("Inventory Delta", 0.0))
    risk = float(total.get("Weighted Risk", 0.0))
    primary = _safe_group_row(group_df, PRIMARY_COUNTRY)
    secondary = _safe_group_row(group_df, SECONDARY_GROUP)
    focus = supplier_focus_df.head(max(1, focused_supplier_count)) if isinstance(supplier_focus_df, pd.DataFrame) else pd.DataFrame()
    best_supplier = "No supplier ranked"
    best_rationale = "Complete supplier inputs to generate the ranked recommendation."
    if not focus.empty:
        top = focus.iloc[0]
        best_supplier = str(top.get("Supplier", "Top supplier"))
        if analysis_mode == "Indirect / Services":
            perf = top.get("Performance Score", None)
            should_gap = top.get("Should-Cost Gap", None)
            prod = top.get("Productivity Gain", None)
            best_rationale = (
                f"best current executive focus by performance-adjusted cost. "
                f"Score {perf:.1f}/100, productivity gain {format_money(prod, currency, compact=True) if pd.notna(prod) else 'n/a'}, "
                f"should-cost gap {format_money(should_gap, currency, compact=True, signed=True) if pd.notna(should_gap) else 'n/a'}."
            )
        else:
            best_rationale = f"best current executive focus by economic all-in cost and risk score {top.get('Risk Score', 0):.2f}/5."

    decision = "Approve / advance to negotiation" if final_delta <= 0 and risk <= 3.5 else "Negotiate before approval"
    if final_delta > 0:
        decision = "Do not approve as-is"
    wc_msg = "helps the case" if wc_delta < 0 else "does not offset the case enough"
    inv_msg = "inventory is favorable" if inv_delta < 0 else "inventory adds cost" if inv_delta > 0 else "inventory is neutral"
    service_extra = ""
    if analysis_mode == "Indirect / Services":
        service_extra = (
            "<li><b>Services lens:</b> challenge overtime, headcount productivity, SLA credits, rate-card compliance and supplier productivity commitments before contracting.</li>"
        )
    else:
        service_extra = (
            "<li><b>Direct materials lens:</b> challenge landed unit price, FX, incoterm cost ownership, MOQ, lead time and inventory ownership before contracting.</li>"
        )

    return f"""
    <div class="ai-copilot-card">
        <h4>🤖 AI Executive Copilot — concise recommendation</h4>
        <ul>
            <li><b>Decision:</b> {decision}. Final economic all-in = <b>{format_money(final_delta, currency, compact=True, signed=True)}</b>; weighted risk = <b>{risk:.2f}/5</b>.</li>
            <li><b>Best current option:</b> {escape(best_supplier)} — {escape(best_rationale)}</li>
            <li><b>Value bridge:</b> gross saving/impact = <b>{format_money(gross_delta, currency, compact=True, signed=True)}</b>; working capital {wc_msg} = <b>{format_money(wc_delta, currency, compact=True, signed=True)}</b>; {inv_msg} = <b>{format_money(inv_delta, currency, compact=True, signed=True)}</b>.</li>
            <li><b>Market check:</b> {escape(PRIMARY_COUNTRY)} = <b>{format_money(primary.get('Economic All-In Delta', 0), currency, compact=True, signed=True)}</b>; {escape(SECONDARY_GROUP)} = <b>{format_money(secondary.get('Economic All-In Delta', 0), currency, compact=True, signed=True)}</b>.</li>
            {service_extra}
            <li><b>Next action:</b> use the top supplier focus list to run a final negotiation round on price, payment term, risk mitigation and implementation commitments.</li>
        </ul>
    </div>
    """



def service_scope_config(scope: str) -> Dict[str, object]:
    return SERVICE_SCOPE_CONFIG.get(scope, SERVICE_SCOPE_CONFIG["Generic Indirect Service"])


def service_tier(score: float) -> str:
    if score >= 90:
        return "Strategic / preferred"
    if score >= 75:
        return "Approved / good"
    if score >= 60:
        return "Watchlist"
    return "Corrective action / exit plan"


def service_score_tone(score: float) -> str:
    if score >= 75:
        return "#047857"
    if score >= 60:
        return "#b45309"
    return "#b91c1c"


def weighted_service_score(scores: Dict[str, float], weights: Dict[str, float] | None = None) -> float:
    weights = weights or SERVICE_SCORECARD_WEIGHTS
    total_w = sum(float(v) for v in weights.values()) or 1.0
    return sum(float(scores.get(dim, 0.0)) * float(weight) for dim, weight in weights.items()) / total_w


def weighted_governance_score(scores: Dict[str, float]) -> float:
    total_w = sum(float(v) for v in SUPPLIER_GOVERNANCE_WEIGHTS.values()) or 1.0
    return sum(float(scores.get(dim, 0.0)) * float(weight) for dim, weight in SUPPLIER_GOVERNANCE_WEIGHTS.items()) / total_w


def score_to_risk(score: float) -> float:
    """Convert a 0-100 performance/due-diligence score into a 1-5 risk score.

    100 = best performance = 1.0 risk. 0 = critical performance = 5.0 risk.
    """
    return max(1.0, min(5.0, 1.0 + 4.0 * (100.0 - float(score)) / 100.0))


def governance_tier(score: float) -> str:
    if score >= 90:
        return "Strategic / preferred"
    if score >= 75:
        return "Approved / good"
    if score >= 60:
        return "Watchlist"
    return "Corrective action / exit"


def due_diligence_penalty(status: str) -> float:
    return {"Clear": 0.0, "Minor gaps": 0.25, "Material gaps": 0.75, "Not approved": 1.50}.get(status, 0.0)


def governance_risk_defaults(governance_inputs: Dict[str, Dict[str, float | str]], supplier: str) -> Dict[str, float]:
    """Map supplier governance/scorecard data into the same risk dimensions used by sourcing optimization."""
    data = governance_inputs.get(supplier, {}) or {}
    status_penalty = due_diligence_penalty(str(data.get("Due diligence status", "Clear")))
    return {
        "Supply": max(1.0, min(5.0, score_to_risk(float(data.get("OTIF / SLA delivery", 75.0))) + 0.15 * status_penalty)),
        "Quality": max(1.0, min(5.0, score_to_risk(float(data.get("Quality / NCR performance", 75.0))))),
        "Financial": max(1.0, min(5.0, score_to_risk(float(data.get("Financial health", 75.0))) + 0.25 * status_penalty)),
        "Compliance": max(1.0, min(5.0, score_to_risk(float(data.get("Compliance / due diligence", 75.0))) + status_penalty)),
        "ESG": max(1.0, min(5.0, score_to_risk(float(data.get("ESG / ethics", 75.0))) + 0.35 * status_penalty)),
        "Logistics": max(1.0, min(5.0, (score_to_risk(float(data.get("OTIF / SLA delivery", 75.0))) + score_to_risk(float(data.get("Labor / HSE", 75.0)))) / 2.0)),
    }


def blend_risk_default(base: float, governance_based: float, custom_adjustment: float = 0.0) -> float:
    """Blend manually curated risk baseline with supplier governance signals."""
    blended = 0.45 * float(base) + 0.55 * float(governance_based) + float(custom_adjustment)
    return round(max(1.0, min(5.0, blended)), 1)


def render_service_scope_fields(*, key_prefix: str, scope: str) -> Dict[str, float]:
    """Render scope-specific commercial/service drivers.

    These fields are intentionally descriptive and category-specific. They help the
    buyer validate scope and demand before comparing suppliers. Not every service
    should be analyzed with the same units.
    """
    cfg = service_scope_config(scope)
    labels = list(cfg.get("field_labels", ["Service units", "Hours / month", "Sites / users covered"]))
    c = st.columns(3)
    values = {}
    defaults = [0.0, 0.0, 0.0]
    for idx, label in enumerate(labels[:3]):
        with c[idx]:
            values[f"driver_{idx+1}"] = st.number_input(
                label,
                min_value=0.0,
                value=defaults[idx],
                step=1.0,
                format="%.2f",
                key=f"{key_prefix}__scope_driver_{idx+1}",
            )
    st.caption(f"Recommended demand driver for this scope: {cfg.get('driver_label', 'service units')}.")
    return values


def render_service_scorecard(*, key_prefix: str, supplier_label: str, default_score: float = 82.0) -> Dict[str, float | str]:
    st.markdown("<div class='plain-title'>Supplier performance scorecard</div>", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    scores: Dict[str, float] = {}
    dims = list(SERVICE_SCORECARD_WEIGHTS.keys())
    cols = [c1, c2, c3, c4]
    for idx, dim in enumerate(dims):
        with cols[idx % 4]:
            scores[dim] = st.slider(
                f"{supplier_label} | {dim}",
                min_value=0.0,
                max_value=100.0,
                value=float(default_score),
                step=1.0,
                key=f"{key_prefix}__score__{dim}",
            )
    score = weighted_service_score(scores)
    tier = service_tier(score)
    color = service_score_tone(score)
    st.markdown(
        f"""
        <div class="service-result">
            <b>Weighted service score:</b> <span class="score-badge" style="color:{color};">{score:,.1f}/100</span>
            &nbsp; | &nbsp; <b>Supplier tier:</b> {escape(tier)}
        </div>
        """,
        unsafe_allow_html=True,
    )
    return {"score": float(score), "tier": tier, **scores}


def render_service_baseline_builder(
    *,
    key_prefix: str,
    country: str,
    scope: str,
    reporting_currency: str,
) -> Dict[str, float | str]:
    """Render the current baseline for Indirect / Services mode.

    Current service spend is built as a service lifecycle cost, not a unit x volume material spend.
    """
    cfg = service_scope_config(scope)
    pricing_models = list(cfg.get("pricing_models", ["Fixed fee"]))
    default_model = pricing_models[0]
    st.markdown(f"**{cfg.get('icon', '🧾')} {scope} — current baseline ({country})**")
    r1 = st.columns([1.15, 0.85, 0.85, 0.85])
    with r1[0]:
        pricing_model = st.selectbox(
            "Pricing model",
            options=pricing_models,
            index=pricing_models.index(default_model),
            key=f"{key_prefix}__pricing_model",
        )
    with r1[1]:
        contracted_value = st.number_input(
            "Current contracted / baseline value",
            min_value=0.0,
            value=float(DEFAULT_SERVICE_CONTRACT_VALUE[country]),
            step=100_000.0,
            format="%.2f",
            key=f"{key_prefix}__contracted_value",
        )
    with r1[2]:
        budget_value = st.number_input(
            "Current budget",
            min_value=0.0,
            value=float(DEFAULT_SERVICE_CONTRACT_VALUE[country]),
            step=100_000.0,
            format="%.2f",
            key=f"{key_prefix}__budget_value",
        )
    with r1[3]:
        actual_demand_index = st.number_input(
            "Actual demand index",
            min_value=0.0,
            value=100.0,
            step=5.0,
            format="%.2f",
            key=f"{key_prefix}__actual_demand_index",
            help="100 = baseline demand. Above 100 indicates demand growth/scope consumption beyond baseline.",
        )

    render_service_scope_fields(key_prefix=key_prefix, scope=scope)

    st.markdown("<div class='plain-title'>Current workforce, rate card and overtime KPIs</div>", unsafe_allow_html=True)
    wh = st.columns(6)
    with wh[0]:
        headcount = st.number_input("Current headcount / FTEs", min_value=0.0, value=0.0, step=1.0, format="%.2f", key=f"{key_prefix}__headcount")
    with wh[1]:
        price_per_person_month = st.number_input("Current price per person / month", min_value=0.0, value=0.0, step=1_000.0, format="%.2f", key=f"{key_prefix}__price_per_person_month")
    with wh[2]:
        regular_hours_per_person_month = st.number_input("Regular hours / person / month", min_value=0.0, value=168.0, step=1.0, format="%.2f", key=f"{key_prefix}__regular_hours_per_person_month")
    with wh[3]:
        hourly_rate = st.number_input("Current hourly rate", min_value=0.0, value=0.0, step=10.0, format="%.2f", key=f"{key_prefix}__hourly_rate", help="If left as zero, the tool estimates hourly rate from price per person divided by regular hours.")
    with wh[4]:
        overtime_hours_month = st.number_input("Overtime hours / month", min_value=0.0, value=0.0, step=1.0, format="%.2f", key=f"{key_prefix}__overtime_hours_month")
    with wh[5]:
        overtime_multiplier = st.number_input("OT multiplier", min_value=1.0, value=1.5, step=0.05, format="%.2f", key=f"{key_prefix}__overtime_multiplier")
    effective_hourly_rate = float(hourly_rate) if float(hourly_rate) > 0 else safe_divide(float(price_per_person_month), float(regular_hours_per_person_month))
    overtime_cost = float(overtime_hours_month) * effective_hourly_rate * float(overtime_multiplier) * 12.0
    people_cost_model = float(headcount) * float(price_per_person_month) * 12.0

    st.markdown("<div class='plain-title'>Current service lifecycle costs and leakage</div>", unsafe_allow_html=True)
    r2 = st.columns(6)
    with r2[0]:
        change_orders = st.number_input("Change orders / add-ons", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__change_orders")
    with r2[1]:
        internal_management = st.number_input("Internal management cost", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__internal_management")
    with r2[2]:
        rework_cost = st.number_input("Rework / quality cost", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__rework_cost")
    with r2[3]:
        downtime_compliance_cost = st.number_input("Downtime / compliance cost", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__downtime_compliance_cost")
    with r2[4]:
        sla_credits_rebates = st.number_input("SLA credits / rebates", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__sla_credits_rebates")
    with r2[5]:
        overtime_cost_input = st.number_input("Annual overtime cost", min_value=0.0, value=float(overtime_cost), step=10_000.0, format="%.2f", key=f"{key_prefix}__overtime_cost_input")

    service_tco = contracted_value + change_orders + internal_management + rework_cost + downtime_compliance_cost + overtime_cost_input - sla_credits_rebates
    scope_creep_pct = safe_divide(change_orders, contracted_value)
    budget_variance = service_tco - budget_value
    st.markdown(
        f"""
        <div class="service-result">
            <b>Current Service TCO:</b> {reporting_currency} {service_tco:,.2f} &nbsp; | &nbsp;
            <b>Scope creep:</b> {scope_creep_pct*100:,.1f}% &nbsp; | &nbsp;
            <b>Budget variance:</b> {reporting_currency} {budget_variance:,.2f} &nbsp; | &nbsp;
            <b>Overtime hours/month:</b> {overtime_hours_month:,.1f}
        </div>
        """,
        unsafe_allow_html=True,
    )
    return {
        "scope": scope,
        "pricing_model": pricing_model,
        "contracted_value": float(contracted_value),
        "budget_value": float(budget_value),
        "actual_demand_index": float(actual_demand_index),
        "change_orders": float(change_orders),
        "internal_management": float(internal_management),
        "rework_cost": float(rework_cost),
        "downtime_compliance_cost": float(downtime_compliance_cost),
        "sla_credits_rebates": float(sla_credits_rebates),
        "headcount": float(headcount),
        "price_per_person_month": float(price_per_person_month),
        "regular_hours_per_person_month": float(regular_hours_per_person_month),
        "hourly_rate": float(effective_hourly_rate),
        "overtime_hours_month": float(overtime_hours_month),
        "overtime_cost": float(overtime_cost_input),
        "people_cost_model": float(people_cost_model),
        "productivity_gain": 0.0,
        "expected_risk_cost": 0.0,
        "service_tco": float(service_tco),
        "scope_creep_pct": float(scope_creep_pct),
        "budget_variance": float(budget_variance),
    }


def render_service_supplier_builder(
    *,
    key_prefix: str,
    country: str,
    scope: str,
    supplier_label: str,
    default_spend: float,
    reporting_currency: str,
) -> Dict[str, float | str]:
    """Render supplier proposal build-up for Indirect / Services mode.

    The returned service_tco is used as the proposal spend in the TCO engine.
    It already includes supplier-led productivity gains, leakage assumptions and risk-adjusted cost.
    """
    cfg = service_scope_config(scope)
    pricing_models = list(cfg.get("pricing_models", ["Fixed fee"]))
    st.markdown(f"<div class='plain-title'>{cfg.get('icon','🧾')} Service pricing, scope and productivity</div>", unsafe_allow_html=True)
    r1 = st.columns([1.05, .85, .85, .85])
    with r1[0]:
        pricing_model = st.selectbox(
            f"{supplier_label} | Pricing model",
            options=pricing_models,
            index=0,
            key=f"{key_prefix}__pricing_model",
        )
    with r1[1]:
        proposed_contract_value = st.number_input(
            f"{supplier_label} | Proposed contract / service value",
            min_value=0.0,
            value=float(default_spend),
            step=50_000.0,
            format="%.2f",
            key=f"{key_prefix}__proposed_contract_value",
        )
    with r1[2]:
        baseline_demand_index = st.number_input(
            f"{supplier_label} | Demand / scope index",
            min_value=0.0,
            value=100.0,
            step=5.0,
            format="%.2f",
            key=f"{key_prefix}__baseline_demand_index",
            help="100 = same demand/scope. Use this to normalize proposals with different scope coverage.",
        )
    with r1[3]:
        transition_days = st.number_input(
            f"{supplier_label} | Transition / implementation days",
            min_value=0,
            value=30,
            step=1,
            key=f"{key_prefix}__transition_days",
        )

    render_service_scope_fields(key_prefix=key_prefix, scope=scope)

    st.markdown("<div class='plain-title'>Workforce, rate card and overtime KPIs</div>", unsafe_allow_html=True)
    wh = st.columns(6)
    with wh[0]:
        headcount = st.number_input(f"{supplier_label} | Headcount / FTEs", min_value=0.0, value=0.0, step=1.0, format="%.2f", key=f"{key_prefix}__headcount")
    with wh[1]:
        price_per_person_month = st.number_input(f"{supplier_label} | Price per person / month", min_value=0.0, value=0.0, step=1_000.0, format="%.2f", key=f"{key_prefix}__price_per_person_month")
    with wh[2]:
        regular_hours_per_person_month = st.number_input(f"{supplier_label} | Regular hours / person / month", min_value=0.0, value=168.0, step=1.0, format="%.2f", key=f"{key_prefix}__regular_hours_per_person_month")
    with wh[3]:
        hourly_rate = st.number_input(f"{supplier_label} | Hourly rate", min_value=0.0, value=0.0, step=10.0, format="%.2f", key=f"{key_prefix}__hourly_rate", help="If left as zero, the tool estimates hourly rate from price per person divided by regular hours.")
    with wh[4]:
        overtime_hours_month = st.number_input(f"{supplier_label} | Overtime hours / month", min_value=0.0, value=0.0, step=1.0, format="%.2f", key=f"{key_prefix}__overtime_hours_month")
    with wh[5]:
        overtime_multiplier = st.number_input(f"{supplier_label} | OT multiplier", min_value=1.0, value=1.5, step=0.05, format="%.2f", key=f"{key_prefix}__overtime_multiplier")
    effective_hourly_rate = float(hourly_rate) if float(hourly_rate) > 0 else safe_divide(float(price_per_person_month), float(regular_hours_per_person_month))
    people_cost_model = float(headcount) * float(price_per_person_month) * 12.0
    overtime_cost = float(overtime_hours_month) * effective_hourly_rate * float(overtime_multiplier) * 12.0

    st.markdown("<div class='plain-title'>Service should-cost engine</div>", unsafe_allow_html=True)
    sc = st.columns(6)
    with sc[0]:
        should_cost_headcount = st.number_input(f"{supplier_label} | Should-cost HC", min_value=0.0, value=float(headcount), step=1.0, format="%.2f", key=f"{key_prefix}__should_cost_headcount")
    with sc[1]:
        benchmark_hourly_rate = st.number_input(f"{supplier_label} | Benchmark hourly rate", min_value=0.0, value=max(float(effective_hourly_rate), 0.0), step=10.0, format="%.2f", key=f"{key_prefix}__benchmark_hourly_rate")
    with sc[2]:
        target_hours_month = st.number_input(f"{supplier_label} | Target hours/FTE/month", min_value=0.0, value=float(regular_hours_per_person_month), step=1.0, format="%.2f", key=f"{key_prefix}__target_hours_month")
    with sc[3]:
        overhead_tools_pct = st.number_input(f"{supplier_label} | Overhead/tools %", min_value=0.0, max_value=200.0, value=15.0, step=1.0, format="%.2f", key=f"{key_prefix}__overhead_tools_pct")
    with sc[4]:
        fair_margin_pct = st.number_input(f"{supplier_label} | Fair margin %", min_value=0.0, max_value=100.0, value=12.0, step=1.0, format="%.2f", key=f"{key_prefix}__fair_margin_pct")
    with sc[5]:
        should_cost_productivity_pct = st.number_input(f"{supplier_label} | Productivity target %", min_value=0.0, max_value=100.0, value=0.0, step=1.0, format="%.2f", key=f"{key_prefix}__should_cost_productivity_pct")
    st.markdown("<div class='plain-title'>Open-cost / should-cost breakdown</div>", unsafe_allow_html=True)
    st.caption("Use these fields to request an open-cost quotation: labor build-up, supervision, tools, subcontractors, transition, risk buffer, overhead and margin. These values enrich the should-cost target and reveal unexplained quote value.")
    open_cost_values: Dict[str, float] = {}
    oc_rows = [SERVICE_OPEN_COST_COMPONENTS[i:i+4] for i in range(0, len(SERVICE_OPEN_COST_COMPONENTS), 4)]
    for row_idx, component_row in enumerate(oc_rows):
        oc_cols = st.columns(4)
        for col_idx, (component_key, component_label) in enumerate(component_row):
            with oc_cols[col_idx]:
                open_cost_values[component_key] = st.number_input(
                    f"{supplier_label} | {component_label}",
                    min_value=0.0,
                    value=0.0,
                    step=10_000.0,
                    format="%.2f",
                    key=f"{key_prefix}__open_cost__{component_key}",
                )
    should_cost_labor = float(should_cost_headcount) * float(target_hours_month) * 12.0 * float(benchmark_hourly_rate)
    open_cost_total = sum(float(v) for v in open_cost_values.values())
    # Open-cost components complement the clean-sheet labor model. Keep labor separated to avoid double-counting if the user leaves open-cost fields blank.
    should_cost_raw = should_cost_labor + open_cost_total
    should_cost_target = should_cost_raw * (1.0 + overhead_tools_pct / 100.0) * (1.0 + fair_margin_pct / 100.0) * (1.0 - should_cost_productivity_pct / 100.0)
    should_cost_gap = float(proposed_contract_value) - float(should_cost_target)
    open_cost_coverage_pct = safe_divide(open_cost_total, float(proposed_contract_value))
    unexplained_quote_value = max(float(proposed_contract_value) - open_cost_total, 0.0)
    st.markdown(
        f"""
        <div class="open-cost-card">
            <b>Open-cost coverage:</b> {open_cost_coverage_pct*100:,.1f}% &nbsp; | &nbsp;
            <b>Open-cost total:</b> {reporting_currency} {open_cost_total:,.2f} &nbsp; | &nbsp;
            <b>Unexplained quote value:</b> {reporting_currency} {unexplained_quote_value:,.2f} &nbsp; | &nbsp;
            <b>Clean-sheet should-cost:</b> {reporting_currency} {should_cost_target:,.2f}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<div class='plain-title'>Service TCO adjustments</div>", unsafe_allow_html=True)
    r2 = st.columns(6)
    with r2[0]:
        transition_cost = st.number_input(f"{supplier_label} | Transition / implementation cost", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__transition_cost")
    with r2[1]:
        change_order_reserve = st.number_input(f"{supplier_label} | Change order reserve", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__change_order_reserve")
    with r2[2]:
        internal_management = st.number_input(f"{supplier_label} | Internal management cost", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__internal_management")
    with r2[3]:
        rework_cost = st.number_input(f"{supplier_label} | Rework / quality cost", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__rework_cost")
    with r2[4]:
        sla_credits_rebates = st.number_input(f"{supplier_label} | SLA credits / rebates", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__sla_credits_rebates")
    with r2[5]:
        overtime_cost_input = st.number_input(f"{supplier_label} | Annual overtime cost", min_value=0.0, value=float(overtime_cost), step=10_000.0, format="%.2f", key=f"{key_prefix}__overtime_cost_input")

    st.markdown("<div class='plain-title'>Supplier-led productivity and risk-adjusted service cost</div>", unsafe_allow_html=True)
    st.caption(f"Productivity expectation for this scope: {cfg.get('productivity_label', 'supplier-led productivity')}.")
    r3 = st.columns([1.0, .78, .78, .78])
    with r3[0]:
        productivity_description = st.text_input(
            f"{supplier_label} | Productivity lever",
            value=str(cfg.get("productivity_label", "supplier-led productivity")),
            key=f"{key_prefix}__productivity_description",
        )
    with r3[1]:
        productivity_gain = st.number_input(
            f"{supplier_label} | Productivity gain value",
            min_value=0.0,
            value=0.0,
            step=10_000.0,
            format="%.2f",
            key=f"{key_prefix}__productivity_gain",
            help="Hard-value productivity that the supplier commits to deliver in the chain. This reduces service TCO.",
        )
    with r3[2]:
        risk_probability = st.number_input(f"{supplier_label} | Risk probability %", min_value=0.0, max_value=100.0, value=0.0, step=1.0, format="%.2f", key=f"{key_prefix}__risk_probability")
    with r3[3]:
        risk_impact = st.number_input(f"{supplier_label} | Risk financial impact", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__risk_impact")

    scorecard = render_service_scorecard(key_prefix=key_prefix, supplier_label=supplier_label)
    expected_risk_cost = float(risk_probability) / 100.0 * float(risk_impact)
    service_tco_before_productivity = proposed_contract_value + transition_cost + change_order_reserve + internal_management + rework_cost + float(overtime_cost_input) + expected_risk_cost - sla_credits_rebates
    service_tco = max(service_tco_before_productivity - productivity_gain, 0.0)
    performance_score = float(scorecard["score"])
    performance_adjusted_cost = safe_divide(service_tco, max(performance_score / 100.0, 1e-9))
    scope_creep_pct = safe_divide(change_order_reserve, proposed_contract_value)
    st.markdown(
        f"""
        <div class="service-result">
            <b>Service TCO used as proposal spend:</b> {reporting_currency} {service_tco:,.2f} &nbsp; | &nbsp;
            <b>Productivity gain:</b> {reporting_currency} {productivity_gain:,.2f} &nbsp; | &nbsp;
            <b>Expected risk cost:</b> {reporting_currency} {expected_risk_cost:,.2f} &nbsp; | &nbsp;
            <b>Performance-adjusted cost:</b> {reporting_currency} {performance_adjusted_cost:,.2f} &nbsp; | &nbsp;
            <b>Should-cost gap:</b> {reporting_currency} {should_cost_gap:,.2f} &nbsp; | &nbsp;
            <b>OT hours/month:</b> {overtime_hours_month:,.1f}
        </div>
        """,
        unsafe_allow_html=True,
    )
    return {
        "scope": scope,
        "pricing_model": pricing_model,
        "proposed_contract_value": float(proposed_contract_value),
        "baseline_demand_index": float(baseline_demand_index),
        "transition_days": int(transition_days),
        "transition_cost": float(transition_cost),
        "change_order_reserve": float(change_order_reserve),
        "internal_management": float(internal_management),
        "rework_cost": float(rework_cost),
        "sla_credits_rebates": float(sla_credits_rebates),
        "headcount": float(headcount),
        "price_per_person_month": float(price_per_person_month),
        "regular_hours_per_person_month": float(regular_hours_per_person_month),
        "hourly_rate": float(effective_hourly_rate),
        "people_cost_model": float(people_cost_model),
        "overtime_hours_month": float(overtime_hours_month),
        "overtime_cost": float(overtime_cost_input),
        "should_cost_headcount": float(should_cost_headcount),
        "benchmark_hourly_rate": float(benchmark_hourly_rate),
        "should_cost_target": float(should_cost_target),
        "should_cost_gap": float(should_cost_gap),
        "open_cost_total": float(open_cost_total),
        "open_cost_coverage_pct": float(open_cost_coverage_pct),
        "unexplained_quote_value": float(unexplained_quote_value),
        **{f"open_cost_{k}": float(v) for k, v in open_cost_values.items()},
        "productivity_description": productivity_description,
        "productivity_gain": float(productivity_gain),
        "risk_probability": float(risk_probability),
        "risk_impact": float(risk_impact),
        "expected_risk_cost": float(expected_risk_cost),
        "service_tco_before_productivity": float(service_tco_before_productivity),
        "service_tco": float(service_tco),
        "performance_score": float(performance_score),
        "performance_tier": str(scorecard["tier"]),
        "performance_adjusted_cost": float(performance_adjusted_cost),
        "scope_creep_pct": float(scope_creep_pct),
        **{f"score_{dim}": float(scorecard[dim]) for dim in SERVICE_SCORECARD_WEIGHTS},
    }


def render_landed_cost_builder(
    *,
    key_prefix: str,
    default_spend: float,
    default_volume: float,
    unit: str,
    reporting_currency: str,
    currency_default: str = "BRL",
    supplier_label: str = "Supplier",
) -> Dict[str, float | str]:
    """Render Direct Materials landed-cost inputs and return calculated spend.

    The build-up is intentionally unit-based because direct materials are normally
    negotiated as price x volume. The rest of the dashboard still consumes spend,
    so this function converts landed unit economics back into 100% equivalent spend.
    """
    if currency_default not in CURRENCY_OPTIONS:
        currency_default = "BRL"
    default_fx = float(DEFAULT_FX_TO_REPORTING.get(currency_default, 1.0))
    # Defaults are stored as reporting-currency spend. Convert them back to quote-currency
    # unit price so the initial landed spend remains aligned with the previous dashboard.
    base_default = default_unit_price_from_spend(default_spend, max(default_volume * default_fx, 1e-9))

    r1 = st.columns([1.0, 0.82, 0.78, 0.78, 0.72])
    with r1[0]:
        base_unit_price = st.number_input(
            f"{supplier_label} | Base / quoted unit price",
            min_value=0.0,
            value=float(base_default),
            step=0.01,
            format="%.6f",
            key=f"{key_prefix}__base_unit_price",
            help="Quoted price per negotiated unit before additional landed-cost components.",
        )
    with r1[1]:
        currency = st.selectbox(
            f"{supplier_label} | Quote currency",
            options=CURRENCY_OPTIONS,
            index=CURRENCY_OPTIONS.index(currency_default),
            key=f"{key_prefix}__currency",
        )
    with r1[2]:
        fx_rate = st.number_input(
            f"{supplier_label} | FX to {reporting_currency}",
            min_value=0.000001,
            value=default_fx,
            step=0.01,
            format="%.6f",
            key=f"{key_prefix}__fx_rate",
            help=f"How many {reporting_currency} one unit of quote currency represents.",
        )
    with r1[3]:
        volume = st.number_input(
            f"{supplier_label} | 100% equivalent volume ({unit})",
            min_value=0.0,
            value=float(default_volume),
            step=max(float(default_volume) * 0.05, 1.0),
            format="%.4f",
            key=f"{key_prefix}__volume",
            help="Country demand volume used to calculate 100% equivalent spend. Share allocation is applied later.",
        )
    with r1[4]:
        moq = st.number_input(
            f"{supplier_label} | MOQ ({unit})",
            min_value=0.0,
            value=0.0,
            step=max(float(default_volume) * 0.05, 1.0),
            format="%.4f",
            key=f"{key_prefix}__moq",
        )

    r2 = st.columns(5)
    with r2[0]:
        conversion_cost = st.number_input(f"{supplier_label} | Conversion cost / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__conversion_cost")
    with r2[1]:
        fixed_margin = st.number_input(f"{supplier_label} | Fixed margin / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__fixed_margin")
    with r2[2]:
        international_freight = st.number_input(f"{supplier_label} | International freight / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__international_freight")
    with r2[3]:
        insurance = st.number_input(f"{supplier_label} | Insurance / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__insurance")
    with r2[4]:
        incoterm = st.selectbox(f"{supplier_label} | Incoterm", options=INCOTERM_OPTIONS, index=INCOTERM_OPTIONS.index("FOB"), key=f"{key_prefix}__incoterm")

    r3 = st.columns(4)
    with r3[0]:
        customs_fees = st.number_input(f"{supplier_label} | Customs / brokerage fees / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__customs_fees")
    with r3[1]:
        import_duties_taxes = st.number_input(f"{supplier_label} | Import duties / taxes / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__import_duties_taxes")
    with r3[2]:
        domestic_freight = st.number_input(f"{supplier_label} | Domestic freight / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__domestic_freight")
    with r3[3]:
        local_taxes = st.number_input(f"{supplier_label} | Local taxes / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__local_taxes")

    components = {
        "base_unit_price": float(base_unit_price),
        "conversion_cost": float(conversion_cost),
        "fixed_margin": float(fixed_margin),
        "international_freight": float(international_freight),
        "insurance": float(insurance),
        "customs_fees": float(customs_fees),
        "import_duties_taxes": float(import_duties_taxes),
        "domestic_freight": float(domestic_freight),
        "local_taxes": float(local_taxes),
    }
    unit_price_quote = sum(components.values())
    unit_price_reporting = landed_unit_price(components, float(fx_rate))
    spend = unit_price_reporting * float(volume)
    moq_note = "OK" if float(moq) <= 0 or float(volume) >= float(moq) else "Volume below MOQ"
    moq_tone = "#047857" if moq_note == "OK" else "#b91c1c"
    st.markdown(
        f"""
        <div class="landed-result">
            <b>Landed unit price:</b> {reporting_currency} {unit_price_reporting:,.6f} / {escape(unit)} &nbsp; | &nbsp;
            <b>100% equivalent spend:</b> {reporting_currency} {spend:,.2f} &nbsp; | &nbsp;
            <b>MOQ status:</b> <span style="color:{moq_tone}; font-weight:800;">{moq_note}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    return {
        "spend": float(spend),
        "unit_price_quote": float(unit_price_quote),
        "unit_price_reporting": float(unit_price_reporting),
        "volume": float(volume),
        "moq": float(moq),
        "currency": currency,
        "fx_rate": float(fx_rate),
        "incoterm": incoterm,
        **components,
    }

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


def supplier_name_key(supplier: str) -> str:
    return f"supplier_display_name__{supplier}"


def supplier_short_name_key(supplier: str) -> str:
    return f"supplier_short_name__{supplier}"


def supplier_display_name(supplier: str) -> str:
    value = str(st.session_state.get(supplier_name_key(supplier), DEFAULT_SUPPLIER_DISPLAY_NAME.get(supplier, supplier))).strip()
    return value or DEFAULT_SUPPLIER_DISPLAY_NAME.get(supplier, supplier)


def supplier_short_name(supplier: str) -> str:
    value = str(st.session_state.get(supplier_short_name_key(supplier), DEFAULT_SUPPLIER_SHORT_NAME.get(supplier, supplier))).strip()
    return value or DEFAULT_SUPPLIER_SHORT_NAME.get(supplier, supplier)


def supplier_display_html(supplier: str) -> str:
    return escape(supplier_display_name(supplier), quote=True)


def supplier_short_html(supplier: str) -> str:
    return escape(supplier_short_name(supplier), quote=True)


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
                f"{supplier_short_name(supplier)} has Kraljic minimum {mins[supplier]:.0f}% "
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
        st.session_state.setdefault(supplier_name_key(supplier), DEFAULT_SUPPLIER_DISPLAY_NAME[supplier])
        st.session_state.setdefault(supplier_short_name_key(supplier), DEFAULT_SUPPLIER_SHORT_NAME[supplier])
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
        direct_profile = supplier_data.get("direct_profile", {}) or {}
        service_profile = supplier_data.get("service_profile", {}) or {}
        country_total["supplier_rows"].append({
            "Country": country,
            "Supplier ID": supplier,
            "Supplier": supplier_display_name(supplier),
            "Item / Scope": supplier_data.get("item_name", ""),
            "Unit / Demand Driver": supplier_data.get("negotiated_unit", ""),
            "Quote Currency": direct_profile.get("currency", ""),
            "FX Rate": direct_profile.get("fx_rate", None),
            "Incoterm": direct_profile.get("incoterm", ""),
            "Landed Unit Price": direct_profile.get("unit_price_reporting", None),
            "100% Equivalent Volume": direct_profile.get("volume", None),
            "MOQ": direct_profile.get("moq", None),
            "Service Scope": service_profile.get("scope", ""),
            "Pricing Model": service_profile.get("pricing_model", ""),
            "Proposed Contract Value": service_profile.get("proposed_contract_value", None),
            "Service TCO Before Productivity": service_profile.get("service_tco_before_productivity", None),
            "Productivity Gain": service_profile.get("productivity_gain", None),
            "Expected Risk Cost": service_profile.get("expected_risk_cost", None),
            "Performance Score": service_profile.get("performance_score", None),
            "Performance Tier": service_profile.get("performance_tier", ""),
            "Performance-Adjusted Cost": service_profile.get("performance_adjusted_cost", None),
            "Headcount / FTEs": service_profile.get("headcount", None),
            "Price per Person / Month": service_profile.get("price_per_person_month", None),
            "Hourly Rate": service_profile.get("hourly_rate", None),
            "Overtime Hours / Month": service_profile.get("overtime_hours_month", None),
            "Overtime Cost": service_profile.get("overtime_cost", None),
            "Should-Cost Target": service_profile.get("should_cost_target", None),
            "Should-Cost Gap": service_profile.get("should_cost_gap", None),
            "Open-Cost Total": service_profile.get("open_cost_total", None),
            "Open-Cost Coverage %": service_profile.get("open_cost_coverage_pct", None),
            "Unexplained Quote Value": service_profile.get("unexplained_quote_value", None),
            "Custom Cost Adjustment": supplier_data.get("custom_cost_adjustment", 0.0),
            "Scope Creep %": service_profile.get("scope_creep_pct", None),
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
            "Group": PRIMARY_COUNTRY if country == PRIMARY_COUNTRY else SECONDARY_GROUP,
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
    required_groups = [PRIMARY_COUNTRY, SECONDARY_GROUP]
    group_df = group_df.set_index("Group").reindex(required_groups).reset_index().fillna(0.0)
    # Weighted metrics by new spend.
    weighted_rows = []
    for group in required_groups:
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
            **{supplier_short_name(s): optimized[country][s] for s in SUPPLIERS},
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
    currency_symbol = st.text_input("Reporting currency", value="BRL", help="Currency used in executive cards and total spend calculations.")

    st.markdown("### Sourcing analysis mode")
    analysis_mode = st.radio(
        "Tool mode",
        options=["Direct Materials", "Indirect / Services"],
        index=0,
        horizontal=False,
        help="Direct Materials calculates spend from landed unit price × volume. Indirect / Services keeps the legacy manual spend input.",
    )
    if analysis_mode == "Direct Materials":
        st.markdown(
            """
            <div class="mode-card">
                <div class="mode-card-title">🧪 Direct Materials Landed Cost Engine</div>
                <div class="mode-card-subtitle">Price build-up → landed unit price → spend → TCO, working capital, inventory and risk.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        analysed_item_name = st.text_input("Analysed item", value=DEFAULT_ITEM_NAME, key="direct_item_name")
        negotiated_unit = st.text_input("Negotiated unit", value=DEFAULT_NEGOTIATED_UNIT, key="direct_negotiated_unit")
        service_scope = None
    else:
        st.markdown(
            """
            <div class="mode-card">
                <div class="mode-card-title">🧾 Indirect / Services Executive Cockpit</div>
                <div class="mode-card-subtitle">Scope → pricing model → service TCO → scorecard → productivity gain → contract leakage → executive decision.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        service_scope = st.selectbox(
            "Service / buying scope",
            options=SERVICE_SCOPES,
            index=SERVICE_SCOPES.index(DEFAULT_SERVICE_SCOPE),
            key="service_scope",
            help="The tool changes its required fields and analysis logic according to the service scope selected.",
        )
        cfg = service_scope_config(service_scope)
        analysed_item_name = st.text_input("Negotiated service / scope name", value=service_scope, key="service_item_name")
        negotiated_unit = st.text_input("Main service unit / demand driver", value=str(cfg.get("driver_label", "service unit")), key="service_negotiated_unit")
        st.caption(f"Suggested productivity lens: {cfg.get('productivity_label', 'supplier-led productivity')}.")

    st.markdown("### Market scope")
    default_country_selection = st.session_state.get("selected_country_scope", DEFAULT_ACTIVE_COUNTRIES)
    default_country_selection = [c for c in default_country_selection if c in COUNTRY_OPTIONS] or DEFAULT_ACTIVE_COUNTRIES
    selected_countries = st.multiselect(
        "Countries included in this analysis",
        options=COUNTRY_OPTIONS,
        default=default_country_selection,
        key="selected_country_scope",
        help="Select only the countries that matter for the sourcing case. The app automatically creates the country cards, proposal inputs, risk tables, share sliders and executive views.",
    )
    if not selected_countries:
        selected_countries = ["Brazil"]
        st.warning("At least one country is required. Brazil was temporarily selected as the anchor market.")

    primary_default = st.session_state.get("primary_country_scope", selected_countries[0])
    primary_index = selected_countries.index(primary_default) if primary_default in selected_countries else 0
    primary_country_choice = st.selectbox(
        "Primary / anchor country",
        options=selected_countries,
        index=primary_index,
        key="primary_country_scope",
        help="This country receives its own executive result stack. The remaining selected countries are consolidated as Other selected markets.",
    )
    COUNTRIES = list(selected_countries)
    PRIMARY_COUNTRY = primary_country_choice
    SECONDARY_GROUP = "Other selected markets"
    LATAM_COUNTRIES = [c for c in COUNTRIES if c != PRIMARY_COUNTRY]
    CUSTOM_FACTOR_COUNTRIES = ["All countries"] + COUNTRIES
    for _selected_country in COUNTRIES:
        seed_country_defaults(_selected_country)
    market_chips = "".join([f"<span class='market-chip'>{escape(c)}</span>" for c in COUNTRIES])
    st.markdown(
        f"""
        <div class="market-scope-card">
            <div class="market-scope-title">🌎 Dynamic market scope</div>
            <div class="market-scope-meta"><b>{len(COUNTRIES)}</b> country/countries selected · anchor: <b>{escape(PRIMARY_COUNTRY)}</b></div>
            <div>{market_chips}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    rate_method = st.radio("Rate conversion method", options=["Compound", "Linear"], index=0)
    optimization_step = st.select_slider("Fallback optimization share grid", options=[1, 2, 5, 10], value=5, help="Used only if exact LP optimization is unavailable/infeasible. Lower grid = deeper but slower fallback.")
    st.caption("Optimizer: exact LP available" if SCIPY_AVAILABLE else "Optimizer: grid fallback only; SciPy not available")
    risk_threshold = st.slider("Preferred weighted risk ceiling", min_value=1.0, max_value=5.0, value=3.25, step=0.05)

    st.markdown("### Supplier universe")
    supplier_count_default = int(st.session_state.get("supplier_count_control", min(4, len(SUPPLIER_POOL))))
    supplier_count_default = max(1, min(len(SUPPLIER_POOL), supplier_count_default))
    supplier_count = st.slider(
        "Number of suppliers in the analysis",
        min_value=1,
        max_value=len(SUPPLIER_POOL),
        value=supplier_count_default,
        step=1,
        key="supplier_count_control",
        help="Controls how many supplier cards are displayed and included in inputs, constraints, shares and optimization.",
    )
    focused_default = int(st.session_state.get("focused_supplier_count_control", min(4, int(supplier_count))))
    focused_default = max(1, min(int(supplier_count), focused_default))
    focused_supplier_count = st.slider(
        "Top suppliers to focus executive view",
        min_value=1,
        max_value=int(supplier_count),
        value=focused_default,
        step=1,
        key="focused_supplier_count_control",
        help="After proposals are entered, the cockpit ranks suppliers and highlights only the top N best offers for executive focus.",
    )
    SUPPLIERS = SUPPLIER_POOL[:int(supplier_count)]
    st.session_state["focused_supplier_count"] = int(focused_supplier_count)

    show_advanced_economic = st.checkbox("Show working capital economic view", value=True)

    st.markdown("### Executive result stacks")
    st.markdown(
        "<div class='stack-control-note'>Result stacks are now controlled directly on the Executive Result screen. Use each stack chevron to expand only the views needed for the meeting.</div>",
        unsafe_allow_html=True,
    )

    with st.expander("Supplier names", expanded=False):
        st.caption("Edit the supplier names once here. The labels are saved in the current app session and reflected across proposal inputs, risk, share sliders, charts and tables.")
        for idx, supplier in enumerate(SUPPLIERS, start=1):
            st.text_input(
                f"Supplier {idx} full name",
                key=supplier_name_key(supplier),
                help=f"Display name for internal supplier ID: {supplier}",
            )
            st.text_input(
                f"Supplier {idx} short label",
                key=supplier_short_name_key(supplier),
                help="Compact label used in sliders, charts and executive cards.",
            )

def show_stack(stack_name: str) -> bool:
    # Backward-compatible helper. Visual control moved from sidebar to inline stack expanders.
    return True


@contextmanager
def result_stack(title: str, subtitle: str, icon: str, accent: str, tag: str, expanded: bool = False):
    """Native Streamlit expandable result stack with a compact executive label."""
    label = f"{icon}  {title}  ·  {tag}"
    with st.expander(label, expanded=expanded):
        st.markdown(
            f"<div class='stack-caption' style='--accent:{accent};'>Use the chevron to collapse or expand this decision stack. {escape(subtitle)}</div>",
            unsafe_allow_html=True,
        )
        yield


# =============================================================================
# Header
# =============================================================================

mode_chip = "Direct Materials Cockpit" if analysis_mode == "Direct Materials" else "Indirect / Services Command Center"
hero_class = "hero-direct" if analysis_mode == "Direct Materials" else "hero-service"
hero_copy = (
    "Landed cost, FX, incoterm, MOQ, volume, inventory carrying, payment terms, treasury return and supplier-risk optimization."
    if analysis_mode == "Direct Materials"
    else "Service TCO, headcount/hour economics, overtime KPIs, scorecards, should-cost, contract leakage, productivity gains and supplier-risk optimization."
)
st.markdown(
    f"""
    <div class="executive-hero {hero_class}">
        <div class="mode-chip">{mode_chip}</div>
        <h1>Executive Procurement TCO & Should-Cost Dashboard</h1>
        <p>{hero_copy}</p>
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
    "3. Supplier Management & Performance",
    "4. Custom Analysis Items",
    "5. Supplier Risk & Constraints",
    "6. Share Projection & Optimization",
])

with input_tabs[0]:
    if analysis_mode == "Direct Materials":
        render_section(
            "Current Direct Material Baseline & Financial Assumptions",
            "Build the current baseline from landed unit price × volume, then apply country-specific payment-term, treasury return and inventory assumptions.",
        )
        st.info(
            "Direct Materials rule: Current Spend = landed unit price × 100% equivalent volume. "
            "All unit-cost components are entered per negotiated unit in the quote currency and converted to the reporting currency using FX."
        )
    else:
        render_section(
            "Current Indirect / Services Baseline & Financial Assumptions",
            "Build the current service baseline from contract value, demand/scope drivers, leakage, service lifecycle costs and payment-term economics.",
        )
        st.info(
            "Indirect / Services rule: Current Spend = Service TCO baseline. Service TCO includes contracted value, change orders, internal management, rework, downtime/compliance costs and SLA credits/rebates. "
            "Inventory carrying is set to zero for services unless you later model a service with owned stock."
        )

    country_inputs: Dict[str, Dict] = {}
    for country in COUNTRIES:
        with st.expander(country, expanded=(country == PRIMARY_COUNTRY)):
            direct_profile: Dict[str, float | str] = {}
            service_profile: Dict[str, float | str] = {}
            if analysis_mode == "Direct Materials":
                st.markdown(f"**{analysed_item_name} — Current baseline build-up ({country})**")
                current_default_volume = DEFAULT_DIRECT_VOLUME[country]
                direct_profile = render_landed_cost_builder(
                    key_prefix=f"current_direct__{country}",
                    default_spend=DEFAULT_CURRENT_SPEND[country],
                    default_volume=current_default_volume,
                    unit=negotiated_unit,
                    reporting_currency=currency_symbol,
                    currency_default=DEFAULT_DIRECT_CURRENCY[country],
                    supplier_label=f"{country} current",
                )
                current_spend = float(direct_profile["spend"])
                st.caption(
                    f"{country} current baseline spend is calculated from {format_quantity(direct_profile['volume'], negotiated_unit)} × "
                    f"{currency_symbol} {direct_profile['unit_price_reporting']:,.6f}/{negotiated_unit}."
                )
            else:
                service_profile = render_service_baseline_builder(
                    key_prefix=f"current_service__{country}",
                    country=country,
                    scope=service_scope or DEFAULT_SERVICE_SCOPE,
                    reporting_currency=currency_symbol,
                )
                current_spend = float(service_profile["service_tco"])
                st.caption(
                    f"{country} current baseline spend is calculated as Service TCO for {service_profile['pricing_model']} under the selected service scope."
                )

            st.markdown("<div class='plain-title'>Financial, treasury and inventory assumptions</div>", unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                current_payment_days = st.number_input(
                    f"{country} current payment term days",
                    min_value=1,
                    value=DEFAULT_CURRENT_TERM[country],
                    step=1,
                    key=f"v24_current_payment_days__{country}",
                    help="This is the CURRENT baseline payment term. It does not change when supplier proposal terms change.",
                )
                current_inventory_days = st.number_input(
                    f"{country} current stock-on-hand days",
                    min_value=0,
                    value=DEFAULT_CURRENT_INVENTORY_DAYS[country] if analysis_mode == "Direct Materials" else 0,
                    step=1,
                    key=f"v24_current_inventory_days__{country}",
                    help="Inventory carrying cost uses this number as stock-on-hand / inventory ownership days for the current baseline. Services default to zero.",
                    disabled=(analysis_mode != "Direct Materials"),
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
                    value=DEFAULT_INVENTORY_CARRY_RATE[country] if analysis_mode == "Direct Materials" else 0.0,
                    step=0.05,
                    format="%.4f",
                    key=f"v24_inventory_rate__{country}",
                    disabled=(analysis_mode != "Direct Materials"),
                )
                st.markdown("<div class='small-note'><b>Baseline logic</b><br>Financial/treasury effects use the current payment term. Direct-material spend is calculated from landed unit price × volume.</div>", unsafe_allow_html=True)

            country_inputs[country] = {
                "current_spend": float(current_spend),
                "current_payment_days": int(current_payment_days),
                "financial_rate_pct": float(financial_rate_pct),
                "financial_reference_days": int(financial_reference_days),
                "treasury_return_pct": float(treasury_return_pct),
                "treasury_reference_days": int(treasury_reference_days),
                "inventory_carry_rate_pct": float(inventory_carry_rate_pct),
                "current_inventory_days": int(current_inventory_days),
                "analysis_mode": analysis_mode,
                "item_name": analysed_item_name,
                "negotiated_unit": negotiated_unit,
                "direct_profile": direct_profile,
                "service_profile": service_profile,
                "service_scope": service_scope,
            }
            st.caption(
                f"{country}: financial rate is referenced to {financial_reference_days} days; current baseline uses {current_payment_days} payment days; supplier proposals use each supplier payment term."
            )

with input_tabs[1]:
    if analysis_mode == "Direct Materials":
        render_section(
            "Supplier Direct Material Proposals",
            "Build each supplier proposal from landed unit economics. The calculated 100% equivalent spend is then used by the share allocation and TCO engine.",
        )
        st.info(
            "Each supplier proposal is entered as price build-up per negotiated unit. The app calculates: landed unit price × 100% equivalent volume = proposal spend. "
            "MOQ is flagged as a commercial constraint for now; in the next module it can drive order quantity and average inventory."
        )
    else:
        render_section(
            "Supplier Service Proposals, Scorecards & Productivity Commitments",
            "Build each service proposal from pricing model, scope, contract leakage, service scorecard, expected risk cost and supplier-led productivity gains. The calculated Service TCO is used as proposal spend.",
        )
        st.info(
            "For Indirect / Services, every supplier proposal includes a performance scorecard and a mandatory productivity-gain field. "
            "This is designed for outsourced service providers such as Accenture, Fastenal-style VMI/MRO partners, BPOs, agencies and facilities providers."
        )

    proposal_inputs: Dict[str, Dict[str, Dict]] = {country: {} for country in COUNTRIES}
    for country in COUNTRIES:
        with st.expander(country, expanded=(country == PRIMARY_COUNTRY)):
            country_volume_default = float(country_inputs[country].get("direct_profile", {}).get("volume", DEFAULT_DIRECT_VOLUME[country])) if analysis_mode == "Direct Materials" else DEFAULT_DIRECT_VOLUME[country]
            for supplier in SUPPLIERS:
                display_supplier = supplier_display_name(supplier)
                proposal_label = f"📦 {supplier_short_name(supplier)} — {display_supplier}" if analysis_mode == "Direct Materials" else f"🧾 {supplier_short_name(supplier)} — {display_supplier}"
                with st.expander(proposal_label, expanded=(country == PRIMARY_COUNTRY and supplier == SUPPLIERS[0])):
                    st.markdown("<div class='supplier-expander-note'>Expand only the supplier proposal needed for the current review. This keeps the proposal tab clean even with up to 15 suppliers.</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='supplier-box'><span class='pill'>{supplier_short_html(supplier)}</span>", unsafe_allow_html=True)
                    direct_supplier_profile: Dict[str, float | str] = {}
                    service_supplier_profile: Dict[str, float | str] = {}
                    if analysis_mode == "Direct Materials":
                        direct_supplier_profile = render_landed_cost_builder(
                            key_prefix=f"proposal_direct__{country}__{supplier}",
                            default_spend=DEFAULT_PROPOSAL_SPEND[country][supplier],
                            default_volume=country_volume_default,
                            unit=negotiated_unit,
                            reporting_currency=currency_symbol,
                            currency_default=DEFAULT_DIRECT_CURRENCY[country],
                            supplier_label=f"{country} | {display_supplier}",
                        )
                        spend = float(direct_supplier_profile["spend"])
                    else:
                        service_supplier_profile = render_service_supplier_builder(
                            key_prefix=f"proposal_service__{country}__{supplier}",
                            country=country,
                            scope=service_scope or DEFAULT_SERVICE_SCOPE,
                            supplier_label=f"{country} | {display_supplier}",
                            default_spend=DEFAULT_PROPOSAL_SPEND[country][supplier],
                            reporting_currency=currency_symbol,
                        )
                        spend = float(service_supplier_profile["service_tco"])

                    c2, c3, c4, c5 = st.columns([0.75, 0.75, 0.75, 1.20])
                    with c2:
                        payment_days = st.number_input(
                            f"{country} | {display_supplier} | Payment term days",
                            min_value=0,
                            value=DEFAULT_PAYMENT_TERM[country][supplier],
                            step=1,
                            key=f"proposal_term__{country}__{supplier}",
                        )
                    with c3:
                        lead_time_days = st.number_input(
                            f"{country} | {display_supplier} | Lead time / transition days",
                            min_value=0,
                            value=(DEFAULT_LEAD_TIME_DAYS[country][supplier] if analysis_mode == "Direct Materials" else int(service_supplier_profile.get("transition_days", 30))),
                            step=1,
                            key=f"lead_time__{country}__{supplier}",
                            help="For services this represents implementation / transition days; for direct materials it represents physical lead time.",
                        )
                    with c4:
                        safety_stock_days = st.number_input(
                            f"{country} | {display_supplier} | Safety stock days",
                            min_value=0,
                            value=DEFAULT_SAFETY_STOCK_DAYS[country][supplier] if analysis_mode == "Direct Materials" else 0,
                            step=1,
                            key=f"safety_stock__{country}__{supplier}",
                            disabled=(analysis_mode != "Direct Materials"),
                        )
                    with c5:
                        inventory_ownership = st.selectbox(
                            f"{country} | {display_supplier} | Inventory ownership",
                            options=INVENTORY_OWNERSHIP_OPTIONS,
                            index=INVENTORY_OWNERSHIP_OPTIONS.index(DEFAULT_INVENTORY_OWNERSHIP[country][supplier] if analysis_mode == "Direct Materials" else "Supplier/trader owns until delivery"),
                            key=f"inventory_ownership__{country}__{supplier}",
                            help="Defines how many days are charged with inventory carrying cost. Services default to zero inventory days.",
                            disabled=(analysis_mode != "Direct Materials"),
                        )
                    st.markdown("</div>", unsafe_allow_html=True)
                    proposal_inputs[country][supplier] = {
                        "spend": float(spend),
                        "payment_days": int(payment_days),
                        "lead_time_days": int(lead_time_days),
                        "safety_stock_days": int(safety_stock_days),
                        "inventory_ownership": inventory_ownership,
                        "analysis_mode": analysis_mode,
                        "item_name": analysed_item_name,
                        "negotiated_unit": negotiated_unit,
                        "direct_profile": direct_supplier_profile,
                        "service_profile": service_supplier_profile,
                        "service_scope": service_scope,
                    }


with input_tabs[2]:
    render_section(
        "Supplier Management, Performance & Due Diligence",
        "Executive supplier governance layer. These scorecards automatically feed the proposal risk defaults used by the sourcing optimization engine.",
    )
    st.info(
        "Governance rule: performance and due-diligence inputs are converted into risk defaults for Supply, Quality, Financial, Compliance, ESG and Logistics. "
        "You can still fine-tune the final risk sliders in the Risk & Constraints tab."
    )
    supplier_management_inputs: Dict[str, Dict[str, float | str]] = {}
    governance_rows = []
    for supplier in SUPPLIERS:
        with st.expander(f"🛡️ {supplier_display_name(supplier)} — governance, KPIs and due diligence", expanded=(supplier == SUPPLIERS[0])):
            st.markdown("<div class='governance-card'>", unsafe_allow_html=True)
            gcols = st.columns(4)
            gov_scores: Dict[str, float] = {}
            dims = list(SUPPLIER_GOVERNANCE_WEIGHTS.keys())
            for idx, dim in enumerate(dims):
                with gcols[idx % 4]:
                    gov_scores[dim] = st.slider(
                        dim,
                        min_value=0.0,
                        max_value=100.0,
                        value=82.0,
                        step=1.0,
                        key=f"governance__{supplier}__{dim}",
                        help="0 = critical issue, 100 = best-in-class. These values feed sourcing risk defaults.",
                    )
            d1, d2, d3, d4 = st.columns(4)
            with d1:
                dd_status = st.selectbox(
                    "Due diligence status",
                    options=DUE_DILIGENCE_STATUS_OPTIONS,
                    index=0,
                    key=f"governance__{supplier}__dd_status",
                )
            with d2:
                qbr_frequency = st.selectbox(
                    "Governance cadence",
                    options=["Monthly", "Quarterly", "Semiannual", "Annual", "Ad hoc"],
                    index=1,
                    key=f"governance__{supplier}__qbr_frequency",
                )
            with d3:
                corrective_actions = st.number_input(
                    "Open corrective actions",
                    min_value=0,
                    value=0,
                    step=1,
                    key=f"governance__{supplier}__corrective_actions",
                )
            with d4:
                dependency_level = st.selectbox(
                    "Business dependency",
                    options=["Low", "Medium", "High", "Critical"],
                    index=1,
                    key=f"governance__{supplier}__dependency_level",
                )
            governance_score = weighted_governance_score(gov_scores)
            tier = governance_tier(governance_score)
            supplier_management_inputs[supplier] = {
                **gov_scores,
                "Due diligence status": dd_status,
                "Governance cadence": qbr_frequency,
                "Open corrective actions": float(corrective_actions),
                "Business dependency": dependency_level,
                "Governance score": float(governance_score),
                "Governance tier": tier,
            }
            st.markdown(
                f"""
                <div class="service-result">
                    <b>Governance score:</b> <span class="score-badge">{governance_score:,.1f}/100</span>
                    &nbsp; | &nbsp; <b>Tier:</b> {escape(tier)}
                    &nbsp; | &nbsp; <b>Due diligence:</b> {escape(dd_status)}
                    &nbsp; | &nbsp; <b>Business dependency:</b> {escape(dependency_level)}
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)
            governance_rows.append({
                "Supplier": supplier_display_name(supplier),
                "Governance Score": governance_score,
                "Tier": tier,
                "Due Diligence": dd_status,
                "Cadence": qbr_frequency,
                "Open Actions": corrective_actions,
                "Dependency": dependency_level,
                **gov_scores,
            })
    st.markdown("<div class='plain-title'>Supplier governance summary</div>", unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(governance_rows), use_container_width=True, hide_index=True)

with input_tabs[3]:
    render_section(
        "Custom Negotiated Items & Analysis Points",
        "Add buyer-specific items, cost adders, savings levers, risk adjustments and qualitative criteria. The model automatically applies cost and risk adjustments to the supplier analysis.",
    )
    st.info(
        "Use this area when a buyer needs more flexibility than the standard template. Examples: special tooling, transition credits, service credits, tax benefit, implementation risk, exclusivity premium, SLA penalty exposure or supplier-specific productivity commitment."
    )
    custom_factor_count = st.number_input(
        "Number of custom analysis points",
        min_value=0,
        max_value=12,
        value=0,
        step=1,
        key="custom_factor_count",
    )
    custom_cost_adjustments: Dict[str, Dict[str, float]] = {country: {supplier: 0.0 for supplier in SUPPLIERS} for country in COUNTRIES}
    custom_risk_adjustments: Dict[str, float] = {supplier: 0.0 for supplier in SUPPLIERS}
    custom_factor_rows: List[Dict[str, float | str]] = []
    for factor_idx in range(int(custom_factor_count)):
        with st.expander(f"➕ Custom analysis point {factor_idx + 1}", expanded=(factor_idx == 0)):
            st.markdown("<div class='custom-factor-card'>", unsafe_allow_html=True)
            h1, h2, h3, h4 = st.columns([1.3, .9, .85, .75])
            with h1:
                factor_name = st.text_input("Item / analysis point name", value=f"Custom point {factor_idx + 1}", key=f"custom_factor__{factor_idx}__name")
            with h2:
                factor_type = st.selectbox("Adjustment type", options=CUSTOM_FACTOR_TYPES, index=0, key=f"custom_factor__{factor_idx}__type")
            with h3:
                country_scope = st.selectbox("Country scope", options=CUSTOM_FACTOR_COUNTRIES, index=0, key=f"custom_factor__{factor_idx}__country")
            with h4:
                weight = st.number_input("Weight / multiplier", min_value=0.0, value=1.0, step=0.1, format="%.2f", key=f"custom_factor__{factor_idx}__weight")
            st.markdown("<div class='matrix-header'>Supplier values for this custom point</div>", unsafe_allow_html=True)
            value_cols = st.columns(min(5, len(SUPPLIERS)))
            for s_idx, supplier in enumerate(SUPPLIERS):
                with value_cols[s_idx % len(value_cols)]:
                    raw_value = st.number_input(
                        supplier_short_name(supplier),
                        value=0.0,
                        step=10_000.0 if "Cost" in factor_type or "Productivity" in factor_type else 0.1,
                        format="%.2f",
                        key=f"custom_factor__{factor_idx}__{supplier}__value",
                    )
                signed_value = float(raw_value) * float(weight)
                target_countries = COUNTRIES if country_scope == "All countries" else [country_scope]
                if factor_type == "Cost add-on":
                    for c in target_countries:
                        custom_cost_adjustments[c][supplier] += signed_value
                elif factor_type in {"Cost reduction / saving", "Productivity gain"}:
                    for c in target_countries:
                        custom_cost_adjustments[c][supplier] -= signed_value
                elif factor_type == "Risk increase":
                    custom_risk_adjustments[supplier] += safe_divide(signed_value, 100.0)
                elif factor_type == "Risk reduction":
                    custom_risk_adjustments[supplier] -= safe_divide(signed_value, 100.0)
                custom_factor_rows.append({
                    "Analysis Point": factor_name,
                    "Type": factor_type,
                    "Country Scope": country_scope,
                    "Supplier": supplier_display_name(supplier),
                    "Value": signed_value,
                })
            st.caption("Cost values are applied to proposal spend for the selected scope. Risk values are treated as basis points where 100 = 1.0 risk point. Score-only items remain in the audit table for buyer discussion.")
            st.markdown("</div>", unsafe_allow_html=True)

    # Apply custom cost adjustments to proposal spend before risk and optimization are calculated.
    for country in COUNTRIES:
        for supplier in SUPPLIERS:
            adj = float(custom_cost_adjustments[country][supplier])
            if abs(adj) > 1e-9:
                proposal_inputs[country][supplier]["spend_before_custom_adjustment"] = float(proposal_inputs[country][supplier]["spend"])
                proposal_inputs[country][supplier]["custom_cost_adjustment"] = adj
                proposal_inputs[country][supplier]["spend"] = max(float(proposal_inputs[country][supplier]["spend"]) + adj, 0.0)
            else:
                proposal_inputs[country][supplier]["custom_cost_adjustment"] = 0.0
    if custom_factor_rows:
        custom_df = pd.DataFrame(custom_factor_rows)
        display_custom = custom_df.copy()
        if "Value" in display_custom:
            display_custom["Value"] = display_custom["Value"].map(lambda x: format_money(x, currency_symbol, signed=True) if abs(float(x)) >= 100 else f"{x:,.2f}")
        st.markdown("<div class='plain-title'>Custom analysis audit trail</div>", unsafe_allow_html=True)
        st.dataframe(display_custom, use_container_width=True, hide_index=True)
    else:
        st.caption("No custom analysis points added. Standard proposal, risk, performance and TCO logic will be used.")

with input_tabs[4]:
    render_section("Supplier Risk & Strategic Constraints", "Add Kraljic minimum shares, max allocation/capacity and multi-dimensional risk scores. These constraints drive optimization.")
    cweights = st.columns(len(DEFAULT_RISK_WEIGHTS))
    risk_weights: Dict[str, float] = {}
    for idx, dim in enumerate(DEFAULT_RISK_WEIGHTS):
        with cweights[idx]:
            risk_weights[dim] = st.number_input(f"{dim} weight", min_value=0.0, value=DEFAULT_RISK_WEIGHTS[dim], step=1.0, key=f"risk_weight__{dim}")

    risk_inputs: Dict[str, Dict[str, float]] = {supplier: {} for supplier in SUPPLIERS}
    for supplier in SUPPLIERS:
        with st.expander(supplier_display_name(supplier), expanded=(supplier == "ChemPrime")):
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
            governance_based_risk = governance_risk_defaults(supplier_management_inputs, supplier)
            custom_risk_adj = float(custom_risk_adjustments.get(supplier, 0.0))
            rcols = st.columns(len(DEFAULT_RISK_WEIGHTS))
            for idx, dim in enumerate(DEFAULT_RISK_WEIGHTS):
                with rcols[idx]:
                    default_risk_value = blend_risk_default(DEFAULT_RISK[supplier][dim], governance_based_risk.get(dim, DEFAULT_RISK[supplier][dim]), custom_risk_adj)
                    risk_inputs[supplier][dim] = st.slider(
                        f"{dim}",
                        min_value=1.0,
                        max_value=5.0,
                        value=default_risk_value,
                        step=0.1,
                        key=f"risk__{supplier}__{dim}",
                        help="Default is blended from original sourcing risk + Supplier Management scorecard + custom risk adjustments.",
                    )
            st.caption(
                f"Governance feed: {supplier_management_inputs.get(supplier, {}).get('Governance score', 0):.1f}/100 | "
                f"Custom risk adjustment: {custom_risk_adj:+.2f} point(s)."
            )

with input_tabs[5]:
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
        with st.expander(f"{country} share projection", expanded=(country == PRIMARY_COUNTRY)):
            if share_mode == "Automatic":
                st.caption("Automatic mode: changing one supplier will rebalance the others proportionally while respecting min/max shares.")
            else:
                st.caption("Manual mode: sliders are normalized for the calculation if the raw total is not exactly 100%.")

            cols = st.columns(min(4, max(1, len(SUPPLIERS))))
            raw_shares = {}
            for idx, supplier in enumerate(SUPPLIERS):
                with cols[idx % len(cols)]:
                    min_value = float(mins_now[supplier])
                    max_value = float(maxs_now[supplier])
                    key = share_key(country, supplier)
                    current_value = float(st.session_state.get(key, DEFAULT_SHARES[country][supplier]))

                    if max_value < min_value - 1e-9:
                        # Infeasible constraint: do not render a broken slider.
                        raw = min_value
                        st.warning(
                            f"{supplier_short_name(supplier)} infeasible: floor {min_value:.0f}% > capacity {max_value:.0f}%."
                        )
                        st.slider(
                            supplier_short_name(supplier),
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
                            supplier_short_name(supplier),
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
                            supplier_short_name(supplier),
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
            share_df = pd.DataFrame([{"Supplier": supplier_short_name(s), "Effective Model Share %": effective[s]} for s in SUPPLIERS])
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

# Supplier focus lens: ranks all entered suppliers and highlights the top N offers
# selected in the sidebar. Core scenario calculations still use the modeled shares;
# this lens is intended to help executives quickly compare the best supplier offers.
def build_supplier_focus_df(supplier_df: pd.DataFrame, analysis_mode: str) -> pd.DataFrame:
    if supplier_df.empty:
        return pd.DataFrame()
    agg_map = {
        "Economic Total": "sum",
        "Allocated Spend": "sum",
        "Risk Score": "mean",
    }
    optional_sum = [
        "Performance-Adjusted Cost", "Productivity Gain", "Should-Cost Gap",
        "Overtime Hours / Month", "Overtime Cost", "Service TCO Before Productivity",
        "Proposed Contract Value",
    ]
    for col in optional_sum:
        if col in supplier_df.columns:
            agg_map[col] = "sum" if col not in {"Overtime Hours / Month"} else "mean"
    if "Performance Score" in supplier_df.columns:
        agg_map["Performance Score"] = "mean"
    focus = supplier_df.groupby(["Supplier ID", "Supplier"], as_index=False).agg(agg_map)
    if analysis_mode == "Indirect / Services" and "Performance-Adjusted Cost" in focus.columns:
        focus["Executive Focus Metric"] = focus["Performance-Adjusted Cost"].fillna(focus["Economic Total"])
        focus["Focus Rationale"] = "Lower performance-adjusted service cost, then lower risk"
    else:
        focus["Executive Focus Metric"] = focus["Economic Total"]
        focus["Focus Rationale"] = "Lower economic all-in cost, then lower risk"
    focus = focus.sort_values(["Executive Focus Metric", "Risk Score"], ascending=[True, True]).reset_index(drop=True)
    focus["Rank"] = range(1, len(focus) + 1)
    return focus

supplier_focus_df = build_supplier_focus_df(supplier_df, analysis_mode)
focused_supplier_count = int(st.session_state.get("focused_supplier_count", min(4, len(SUPPLIERS))))
top_focus_supplier_ids = supplier_focus_df.head(focused_supplier_count)["Supplier ID"].tolist() if not supplier_focus_df.empty else SUPPLIERS[:focused_supplier_count]

# =============================================================================
# Always-visible Cost Optimization panel
# =============================================================================

render_section(
    "Cost Optimization",
    "Run the optimizer from here at any time. It will respect Kraljic minimum shares, supplier capacity, approved-supplier flags, payment terms, financial rates, treasury return, inventory carrying cost and service TCO/productivity economics."
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
            Searches the best allocation by minimizing economic all-in cost first and weighted risk second. In Services mode, proposal spend already includes service TCO, productivity gains, leakage and expected risk cost.
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

render_section(
    "Executive Result",
    "Decision-ready cockpit. Expand only the result stacks needed for the meeting and keep the screen clean."
)

# Keep commonly used regional rows available even when the stacks are hidden.
primary_row = group_df[group_df["Group"] == PRIMARY_COUNTRY].iloc[0]
secondary_row = group_df[group_df["Group"] == SECONDARY_GROUP].iloc[0]

gross_total_saving_impact = total["Gross All-In Delta"]
working_capital_gain_offset = total["Treasury Return Offset Delta"]
total_saving_plus_working_capital = gross_total_saving_impact + working_capital_gain_offset
final_economic_all_in = total["Economic All-In Delta"]

if not supplier_focus_df.empty:
    with result_stack("Top supplier focus lens", f"Executive view focused on the top {focused_supplier_count} supplier offer(s) from the {len(SUPPLIERS)} supplier universe.", "🎛️", "#2563eb" if analysis_mode == "Direct Materials" else "#7c3aed", "Supplier focus", expanded=False):
        focus_accent = "#2563eb" if analysis_mode == "Direct Materials" else "#7c3aed"
        render_visual_breaker(
            "Top supplier focus lens",
            f"Executive view focused on the top {focused_supplier_count} supplier offer(s) from the {len(SUPPLIERS)} supplier universe.",
            "🎛️",
            focus_accent,
            "Supplier focus",
        )
        focus_display = supplier_focus_df.head(focused_supplier_count).copy()
        focus_cols = ["Rank", "Supplier", "Executive Focus Metric", "Economic Total", "Risk Score"]
        if analysis_mode != "Direct Materials":
            for extra in ["Performance Score", "Performance-Adjusted Cost", "Productivity Gain", "Should-Cost Gap", "Overtime Hours / Month"]:
                if extra in focus_display.columns:
                    focus_cols.append(extra)
        focus_cols = [c for c in focus_cols if c in focus_display.columns]
        focus_display = focus_display[focus_cols]
        for col in ["Executive Focus Metric", "Economic Total", "Performance-Adjusted Cost", "Productivity Gain", "Should-Cost Gap"]:
            if col in focus_display.columns:
                focus_display[col] = focus_display[col].map(lambda x: format_money(x, currency_symbol, compact=True, signed=(col == "Should-Cost Gap")))
        if "Risk Score" in focus_display.columns:
            focus_display["Risk Score"] = focus_display["Risk Score"].map(lambda x: f"{x:.2f}")
        if "Performance Score" in focus_display.columns:
            focus_display["Performance Score"] = focus_display["Performance Score"].map(lambda x: "" if pd.isna(x) else f"{x:.1f}/100")
        if "Overtime Hours / Month" in focus_display.columns:
            focus_display["Overtime Hours / Month"] = focus_display["Overtime Hours / Month"].map(lambda x: "" if pd.isna(x) else f"{x:.1f} h/mo")
        st.markdown(f"<div class='executive-panel {'direct-accent' if analysis_mode == 'Direct Materials' else 'service-accent'}'>", unsafe_allow_html=True)
        st.dataframe(focus_display, use_container_width=True, hide_index=True)
        st.caption("Use the sidebar focus slider to change how many top suppliers are highlighted. Share allocation and optimization respect the selected countries, modeled shares and constraints.")
        st.markdown("</div>", unsafe_allow_html=True)
    
with result_stack("Total project saving", "Final selected-market result, separating gross total saving, working-capital gain and inventory-adjusted economic all-in.", "🏁", GREEN if final_economic_all_in <= 0 else RED, "Final project result", expanded=True):
    project_result_color = GREEN if final_economic_all_in <= 0 else RED
    render_visual_breaker(
        "Total project saving",
        f"Final result for selected market scope: {PRIMARY_COUNTRY} + {len(LATAM_COUNTRIES)} other market(s).",
        "🏁",
        project_result_color,
        "Final project result",
    )
    project_cols = st.columns([1.2, 1.2, 1.55, 1.35], gap="medium")
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

    contribution_cols = st.columns(2, gap="medium")
    with contribution_cols[0]:
        render_kpi(
            f"{PRIMARY_COUNTRY} Contribution",
            format_money(primary_row["Economic All-In Delta"], currency_symbol, compact=True, signed=True),
            f"{PRIMARY_COUNTRY} economic all-in delta",
            delta_tone(primary_row["Economic All-In Delta"]),
            short=True,
        )
    with contribution_cols[1]:
        render_kpi(
            f"{SECONDARY_GROUP} Contribution",
            format_money(secondary_row["Economic All-In Delta"], currency_symbol, compact=True, signed=True),
            f"{len(LATAM_COUNTRIES)} other selected market(s) economic all-in delta",
            delta_tone(secondary_row["Economic All-In Delta"]),
            short=True,
        )

with result_stack("AI Executive Copilot", "One-click concise executive recommendation based on the current scenario. Local preview today; the prompt payload is ready for external AI/API integration.", "🤖", "#6366f1", "AI brief", expanded=False):
    render_visual_breaker(
        "AI Executive Copilot",
        "One-click concise executive recommendation based on the current scenario. Local preview today; the prompt payload is ready for external AI/API integration.",
        "🤖",
        "#6366f1",
        "AI brief",
    )
    ai_cols = st.columns([0.30, 0.70], gap="large")
    with ai_cols[0]:
        if st.button("Generate AI Executive Brief", type="primary", use_container_width=True, key="generate_ai_exec_brief"):
            st.session_state["ai_prompt_payload"] = build_ai_prompt_payload(
                analysis_mode=analysis_mode,
                total=total,
                group_df=group_df,
                supplier_focus_df=supplier_focus_df,
                focused_supplier_count=focused_supplier_count,
                currency=currency_symbol,
            )
            st.session_state["ai_exec_brief"] = generate_ai_executive_brief(
                analysis_mode=analysis_mode,
                total=total,
                group_df=group_df,
                supplier_focus_df=supplier_focus_df,
                focused_supplier_count=focused_supplier_count,
                currency=currency_symbol,
            )
        st.caption("For now this is a controlled in-app executive analysis. A future API key can replace the local logic with a real AI call.")
    with ai_cols[1]:
        st.markdown(
            "<div class='insight-box'><b>How it works</b><br>The app summarizes the current scenario, top suppliers, total saving, working capital, regional deltas, service KPIs and risk. The output is intentionally short for executive use.</div>",
            unsafe_allow_html=True,
        )
    if st.session_state.get("ai_exec_brief"):
        st.markdown(st.session_state["ai_exec_brief"], unsafe_allow_html=True)
        with st.expander("Copy/paste payload for external AI tool", expanded=False):
            st.text_area(
                "Prompt payload",
                value=st.session_state.get("ai_prompt_payload", ""),
                height=220,
                key="ai_prompt_payload_textarea",
            )

with result_stack("Total cost stack", "Commercial spend and gross payment-term cost comparison.", "🧾", "#3b82f6", "Cost baseline", expanded=False):
    render_visual_breaker("Total cost stack", "Commercial spend and gross payment-term cost comparison.", "🧾", "#3b82f6", "Cost baseline")
    row1 = st.columns(6, gap="medium")
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

if SUPPLIERS:
    with result_stack("Reference supplier condition stack", "Benchmark scenario assuming 100% volume under revised reference-supplier conditions.", "🏭", "#f59e0b", "Reference case", expanded=False):
        primary_reference_supplier = SUPPLIERS[0]
        primary_reference_name = supplier_display_name(primary_reference_supplier)
        primary_reference_short = supplier_short_name(primary_reference_supplier)
        chemprime_reference = calc_full_supplier_reference_stack(
            supplier=primary_reference_supplier,
            country_inputs=country_inputs,
            proposal_inputs=proposal_inputs,
            method=rate_method,
            payment_day_overrides={c: (90 if c == "Brazil" else 60 if c in ["Mexico", "Argentina", "Colombia"] else proposal_inputs[c][primary_reference_supplier]["payment_days"]) for c in COUNTRIES},
        )
        render_visual_breaker(
            f"New {primary_reference_short} condition stack",
            f"Benchmark scenario assuming 100% volume under revised {primary_reference_name} conditions.",
            "🏭",
            "#f59e0b",
            "Reference case",
        )
        row1b = st.columns(6, gap="medium")
        with row1b[0]:
            render_kpi(f"100% {primary_reference_short} Spend", format_money(chemprime_reference["Reference Spend"], currency_symbol, compact=True), f"100% awarded to {primary_reference_short} at proposed spend", "neutral")
        with row1b[1]:
            render_kpi("New Spend", format_money(total["New Spend"], currency_symbol, compact=True), "Supplier proposals x shares", "neutral")
        with row1b[2]:
            render_kpi(f"100% {primary_reference_short} Fin. Cost", format_money(chemprime_reference["Reference Financial Cost"], currency_symbol, compact=True), "Selected-market reference payment terms", "neutral")
        with row1b[3]:
            render_kpi("New Financial Cost", format_money(total["New Financial Cost"], currency_symbol, compact=True), "New spend x proposed payment-term rates", "neutral")
        with row1b[4]:
            render_kpi(f"100% {primary_reference_short} Total Spend", format_money(chemprime_reference["Reference Total Spend"], currency_symbol, compact=True), f"100% {primary_reference_short} spend + reference financial cost", "neutral")
        with row1b[5]:
            render_kpi("New Total Spend", format_money(total["New Total Spend"], currency_symbol, compact=True), "New spend + new financial cost", "neutral")
    
with result_stack("Working capital carry view", "Treasury return and net financial effect from payment-term differences.", "🏦", "#10b981", "Cash timing", expanded=False):
    render_visual_breaker("Working capital carry view", "Treasury return and net financial effect from payment-term differences.", "🏦", "#10b981", "Cash timing")
    wc_row = st.columns(5, gap="medium")
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

with result_stack("Total decomposition", "Decision-ready breakdown of spend, financial effect, inventory and risk.", "🧩", "#8b5cf6", "Decision view", expanded=False):
    render_visual_breaker("Total decomposition", "Decision-ready breakdown of spend, financial effect, inventory and risk.", "🧩", "#8b5cf6", "Decision view")
    row2 = st.columns(6, gap="medium")
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

with result_stack(f"{PRIMARY_COUNTRY} result", f"Country-level result and impact drivers for {PRIMARY_COUNTRY}, including payment-term movement.", "📍", "#06b6d4", "Anchor market", expanded=False):
    render_visual_breaker(f"{PRIMARY_COUNTRY} result", f"Country-level result and impact drivers for {PRIMARY_COUNTRY}, including payment-term movement.", "📍", "#06b6d4", "Anchor market")
    row3 = st.columns(7, gap="medium")
    with row3[0]:
        render_kpi("Current Avg Payment Term", f"{primary_row['Current Avg Payment Days']:.0f} dd", "Current baseline payment term", "neutral", short=True)
    with row3[1]:
        render_kpi("New Proposal Avg Payment Term", f"{primary_row['New Avg Payment Days']:.0f} dd", "Share-weighted proposed payment term", "neutral", short=True)
    with row3[2]:
        render_kpi("Spend Saving / Impact", format_money(primary_row["Spend Delta"], currency_symbol, compact=True, signed=True), f"{PRIMARY_COUNTRY} new spend - current spend", delta_tone(primary_row["Spend Delta"]), short=True)
    with row3[3]:
        render_kpi("Gross Financial Saving / Impact", format_money(primary_row["Financial Delta"], currency_symbol, compact=True, signed=True), f"{PRIMARY_COUNTRY} gross financial cost delta", delta_tone(primary_row["Financial Delta"]), short=True)
    with row3[4]:
        render_kpi("Treasury Return Offset", format_money(primary_row["Treasury Return Offset Delta"], currency_symbol, compact=True, signed=True), f"{PRIMARY_COUNTRY} current return - new return", delta_tone(primary_row["Treasury Return Offset Delta"]), short=True)
    with row3[5]:
        render_kpi("Net Financial Saving / Impact", format_money(primary_row["Net Financial Delta"], currency_symbol, compact=True, signed=True), f"{PRIMARY_COUNTRY} net financial effect after treasury return", delta_tone(primary_row["Net Financial Delta"]), short=True)
    with row3[6]:
        render_kpi("Economic All-In Saving / Impact", format_money(primary_row["Economic All-In Delta"], currency_symbol, compact=True, signed=True), f"{PRIMARY_COUNTRY} spend + net financial effect + inventory", delta_tone(primary_row["Economic All-In Delta"]), short=True)

with result_stack(f"{SECONDARY_GROUP} result", f"Consolidated impact view for {len(LATAM_COUNTRIES)} other selected market(s), including payment-term movement.", "🌎", "#ec4899", "Regional view", expanded=False):
    render_visual_breaker(f"{SECONDARY_GROUP} result", f"Consolidated impact view for {len(LATAM_COUNTRIES)} other selected market(s), including payment-term movement.", "🌎", "#ec4899", "Regional view")
    row4 = st.columns(7, gap="medium")
    with row4[0]:
        render_kpi("Current Avg Payment Term", f"{secondary_row['Current Avg Payment Days']:.0f} dd", "Current baseline payment term", "neutral", short=True)
    with row4[1]:
        render_kpi("New Proposal Avg Payment Term", f"{secondary_row['New Avg Payment Days']:.0f} dd", "Share-weighted proposed payment term", "neutral", short=True)
    with row4[2]:
        render_kpi("Spend Saving / Impact", format_money(secondary_row["Spend Delta"], currency_symbol, compact=True, signed=True), f"{SECONDARY_GROUP} new spend - current spend", delta_tone(secondary_row["Spend Delta"]), short=True)
    with row4[3]:
        render_kpi("Gross Financial Saving / Impact", format_money(secondary_row["Financial Delta"], currency_symbol, compact=True, signed=True), f"{SECONDARY_GROUP} gross financial cost delta", delta_tone(secondary_row["Financial Delta"]), short=True)
    with row4[4]:
        render_kpi("Treasury Return Offset", format_money(secondary_row["Treasury Return Offset Delta"], currency_symbol, compact=True, signed=True), f"{SECONDARY_GROUP} current return - new return", delta_tone(secondary_row["Treasury Return Offset Delta"]), short=True)
    with row4[5]:
        render_kpi("Net Financial Saving / Impact", format_money(secondary_row["Net Financial Delta"], currency_symbol, compact=True, signed=True), f"{SECONDARY_GROUP} net financial effect after treasury return", delta_tone(secondary_row["Net Financial Delta"]), short=True)
    with row4[6]:
        render_kpi("Economic All-In Saving / Impact", format_money(secondary_row["Economic All-In Delta"], currency_symbol, compact=True, signed=True), f"{SECONDARY_GROUP} spend + net financial effect + inventory", delta_tone(secondary_row["Economic All-In Delta"]), short=True)

with result_stack("Decision recommendation", "Clear go/no-go interpretation of the modeled scenario.", "✅", "#22c55e", "Recommendation", expanded=True):
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
            """,
            unsafe_allow_html=True,
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
            """,
            unsafe_allow_html=True,
        )

# =============================================================================
# Charts
# =============================================================================

with result_stack("Charts", "Visual comparison of cost stack, decomposition and cost-risk trade-offs.", "📈", "#2563eb", "Visual analytics", expanded=False):
    render_visual_breaker("Charts", "Visual comparison of cost stack, decomposition and cost-risk trade-offs.", "📈", "#2563eb", "Visual analytics")
    chart_col1, chart_col2 = st.columns([1.2, 1.0], gap="large")
    with chart_col1:
        st.markdown("<div class='chart-shell'>", unsafe_allow_html=True)
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
            st.plotly_chart(apply_chart_theme(fig), use_container_width=True, config={"displayModeBar": False})
        else:
            st.bar_chart(pd.DataFrame({"Value": [total["Current Spend"], total["New Spend"], total["Current Financial Cost"], total["New Financial Cost"], total["Current Total Spend"], total["New Total Spend"]]}, index=["Current Spend", "New Spend", "Current Fin. Cost", "New Fin. Cost", "Current Total", "New Total"]))
        st.markdown("</div>", unsafe_allow_html=True)

    with chart_col2:
        st.markdown("<div class='chart-shell'>", unsafe_allow_html=True)
        if PLOTLY_AVAILABLE:
            fig = go.Figure()
            decomp_names = ["Spend", "Net financial", "Inventory", "Economic all-in"]
            decomp_vals = [total["Spend Delta"], total["Net Financial Delta"], total["Inventory Delta"], total["Economic All-In Delta"]]
            fig.add_trace(go.Waterfall(
                name="Economic bridge",
                orientation="v",
                measure=["relative", "relative", "relative", "total"],
                x=decomp_names,
                y=decomp_vals,
                text=[format_money(v, currency_symbol, compact=True, signed=True) for v in decomp_vals],
                textposition="outside",
                connector={"line": {"color": "rgba(100,116,139,.55)", "width": 2}},
                increasing={"marker": {"color": RED}},
                decreasing={"marker": {"color": GREEN}},
                totals={"marker": {"color": BLUE}},
                hovertemplate="%{x}<br>" + currency_symbol + " %{y:,.2f}<extra></extra>",
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
            fig.update_layout(title="Economic Delta Waterfall", height=430, yaxis_title=f"Delta ({currency_symbol})")
            st.plotly_chart(apply_chart_theme(fig), use_container_width=True, config={"displayModeBar": False})
        else:
            st.bar_chart(pd.DataFrame({"Value": [total["Spend Delta"], total["Net Financial Delta"], total["Inventory Delta"], total["Economic All-In Delta"]]}, index=["Spend Delta", "Net Financial Delta", "Inventory Delta", "Economic Delta"]))
        st.markdown("</div>", unsafe_allow_html=True)

    frontier_rows = [
        {"Scenario": "Current scenario", "Risk": total["Weighted Risk"], "Economic Delta": total["Economic All-In Delta"]},
    ]
    try:
        opt_shares, _, _ = optimize_allocations(country_inputs, proposal_inputs, supplier_risk, rate_method, risk_threshold, int(optimization_step))
        _, _, _, opt_total = calc_scenario(opt_shares, country_inputs, proposal_inputs, supplier_risk, rate_method)
        frontier_rows.append({"Scenario": "Optimized", "Risk": opt_total["Weighted Risk"], "Economic Delta": opt_total["Economic All-In Delta"]})
    except Exception:
        pass
    try:
        low_risk_preferences = {s: max(0.0, 6.0 - supplier_risk[s]) for s in SUPPLIERS}
        low_risk_shares = {country: allocate_with_bounds(low_risk_preferences, get_min_shares(), get_max_shares(), 100.0) for country in COUNTRIES}
        _, _, _, low_risk_total = calc_scenario(low_risk_shares, country_inputs, proposal_inputs, supplier_risk, rate_method)
        frontier_rows.append({"Scenario": "Lowest risk", "Risk": low_risk_total["Weighted Risk"], "Economic Delta": low_risk_total["Economic All-In Delta"]})
    except Exception:
        pass
    frontier_df = pd.DataFrame(frontier_rows)
    st.markdown("<div class='chart-shell'>", unsafe_allow_html=True)
    if PLOTLY_AVAILABLE:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=frontier_df["Risk"],
            y=frontier_df["Economic Delta"],
            mode="markers+text",
            text=frontier_df["Scenario"],
            textposition="top center",
            marker=dict(size=15, color=[BLUE, GREEN, AMBER, "#7c3aed"][:len(frontier_df)]),
            hovertemplate="%{text}<br>Risk: %{x:.2f}/5<br>Economic delta: " + currency_symbol + " %{y:,.2f}<extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
        fig.update_layout(title="Cost x Risk Decision Map", height=430, xaxis_title="Weighted risk score", yaxis_title=f"Economic delta ({currency_symbol})")
        st.plotly_chart(apply_chart_theme(fig), use_container_width=True, config={"displayModeBar": False})
    else:
        st.dataframe(frontier_df, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

# =============================================================================
# Working capital economic view and rationale
# =============================================================================

if show_advanced_economic:
    with result_stack("Working capital economic view", "Separates P&L spend, payment-term financing, capital carry benefit and inventory carrying cost.", "💼", "#0f766e", "Economic view", expanded=False):
        render_section("Working Capital Economic View", "This view separates P&L spend, payment-term financing, capital carry benefit and inventory carrying cost.")
        econ_cols = st.columns(5, gap="medium")
        with econ_cols[0]:
            render_kpi("Current Capital Gain", format_money(total["Current Capital Gain"], currency_symbol, compact=True), "Uses current payment terms by country", "good", short=True)
        with econ_cols[1]:
            render_kpi("New Capital Gain", format_money(total["New Capital Gain"], currency_symbol, compact=True), f"Uses supplier payment terms | avg {total.get('New Avg Return Days', 0):.0f}dd", "good", short=True)
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
                if col in display_rat.columns:
                    display_rat[col] = display_rat[col].map(lambda x: format_money(x, currency_symbol, signed=True))
            st.dataframe(display_rat, use_container_width=True)
        else:
            st.info("Run Cost Optimization to generate a country-by-country allocation rationale.")
    
# =============================================================================
# Detailed tables
# =============================================================================

with result_stack("Detailed data", "Audit trail for Finance, Procurement and category strategy discussions.", "🧾", "#64748b", "Detailed data", expanded=False):
    render_section("Detailed Data", "Audit trail for Finance, Procurement and category strategy discussions.")
    detail_tab_names = ["Country summary", "Region summary", "Supplier allocation", "Risk scores", "Supplier governance", "Custom analysis"]
    if analysis_mode != "Direct Materials":
        detail_tab_names.append("Service scorecards")
    detail_tabs = st.tabs(detail_tab_names)
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
        if top_focus_supplier_ids:
            display_supplier["Executive Focus"] = display_supplier["Supplier ID"].isin(top_focus_supplier_ids).map({True: "Top focus", False: "Other"})
        supplier_money_cols = [
            "Allocated Spend", "Supplier Financial Cost", "Capital Gain Offset", "Inventory Carrying Cost", "Economic Total",
            "Proposed Contract Value", "Service TCO Before Productivity", "Productivity Gain", "Expected Risk Cost", "Performance-Adjusted Cost",
            "Price per Person / Month", "Hourly Rate", "Overtime Cost", "Should-Cost Target", "Should-Cost Gap", "Open-Cost Total", "Unexplained Quote Value", "Custom Cost Adjustment",
        ]
        for col in supplier_money_cols:
            if col in display_supplier.columns:
                display_supplier[col] = display_supplier[col].map(lambda x: "" if pd.isna(x) else format_money(x, currency_symbol, signed=(col == "Should-Cost Gap")))
        if "Share %" in display_supplier.columns:
            display_supplier["Share %"] = display_supplier["Share %"].map(lambda x: f"{x:.1f}%")
        if "Risk Score" in display_supplier.columns:
            display_supplier["Risk Score"] = display_supplier["Risk Score"].map(lambda x: f"{x:.2f}")
        if "Performance Score" in display_supplier.columns:
            display_supplier["Performance Score"] = display_supplier["Performance Score"].map(lambda x: "" if pd.isna(x) else f"{x:.1f}/100")
        if "Scope Creep %" in display_supplier.columns:
            display_supplier["Scope Creep %"] = display_supplier["Scope Creep %"].map(lambda x: "" if pd.isna(x) else f"{x*100:.1f}%")
        st.dataframe(display_supplier, use_container_width=True)
    with detail_tabs[3]:
        risk_df = pd.DataFrame([{"Supplier": supplier_display_name(s), "Weighted Risk": supplier_risk[s], **risk_inputs[s]} for s in SUPPLIERS])
        st.dataframe(risk_df, use_container_width=True)
    with detail_tabs[4]:
        if governance_rows:
            st.dataframe(pd.DataFrame(governance_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No supplier governance data available.")
    with detail_tabs[5]:
        if custom_factor_rows:
            st.dataframe(pd.DataFrame(custom_factor_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No custom analysis points were added.")
    if analysis_mode != "Direct Materials":
        with detail_tabs[6]:
            service_cols = [
                "Country", "Supplier", "Service Scope", "Pricing Model", "Proposed Contract Value",
                "Service TCO Before Productivity", "Productivity Gain", "Expected Risk Cost",
                "Performance Score", "Performance Tier", "Performance-Adjusted Cost", "Headcount / FTEs",
                "Price per Person / Month", "Hourly Rate", "Overtime Hours / Month", "Overtime Cost",
                "Should-Cost Target", "Should-Cost Gap", "Open-Cost Total", "Open-Cost Coverage %", "Unexplained Quote Value", "Custom Cost Adjustment", "Scope Creep %",
                "Share %", "Allocated Spend",
            ]
            available_cols = [c for c in service_cols if c in supplier_df.columns]
            service_df = supplier_df[available_cols].copy()
            for col in ["Proposed Contract Value", "Service TCO Before Productivity", "Productivity Gain", "Expected Risk Cost", "Performance-Adjusted Cost", "Allocated Spend", "Price per Person / Month", "Hourly Rate", "Overtime Cost", "Should-Cost Target", "Should-Cost Gap", "Open-Cost Total", "Unexplained Quote Value", "Custom Cost Adjustment"]:
                if col in service_df.columns:
                    service_df[col] = service_df[col].map(lambda x: "" if pd.isna(x) else format_money(x, currency_symbol, signed=(col == "Should-Cost Gap")))
            if "Performance Score" in service_df.columns:
                service_df["Performance Score"] = service_df["Performance Score"].map(lambda x: "" if pd.isna(x) else f"{x:.1f}/100")
            if "Scope Creep %" in service_df.columns:
                service_df["Scope Creep %"] = service_df["Scope Creep %"].map(lambda x: "" if pd.isna(x) else f"{x*100:.1f}%")
            if "Open-Cost Coverage %" in service_df.columns:
                service_df["Open-Cost Coverage %"] = service_df["Open-Cost Coverage %"].map(lambda x: "" if pd.isna(x) else f"{x*100:.1f}%")
            if "Share %" in service_df.columns:
                service_df["Share %"] = service_df["Share %"].map(lambda x: f"{x:.1f}%")
            st.dataframe(service_df, use_container_width=True)

# =============================================================================
# Download
# =============================================================================

with result_stack("Download export", "Export the country summary for offline review.", "⬇️", "#64748b", "Export", expanded=False):
    export_country = country_df.copy()
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
