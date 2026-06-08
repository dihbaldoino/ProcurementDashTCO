"""
Executive Procurement TCO & Should-Cost Intelligence Platform
Version v46 — Enterprise Premium Redesign

Run:
    pip install -r requirements.txt
    streamlit run app.py

WHAT'S NEW IN v46
-----------------
• Complete visual overhaul: premium enterprise dark UI with glass morphism cards,
  gradient accents, smooth animations and a design system worthy of a $500K SaaS product.
• Indirect / Services cockpit redesigned to Amazon procurement standards:
  – FTE demand decomposition (regular vs overtime vs productivity-adjusted headcount)
  – Contract leakage waterfall (contracted → scope creep → actual billed → TCO)
  – SLA penalty / credit modeling with financial impact quantification
  – Productivity ROI tracker: investment vs hard-dollar return timeline
  – Supplier tiering heat map: cost × performance × risk quadrant view
  – Rate card compliance check: quoted vs benchmark × hours consumed
  – Demand volatility buffer: buffer cost for variable demand scopes
  – Multi-year contract value: baseline → escalation → total contract value (TCV)
• AI Executive Copilot now connects to Anthropic claude-sonnet-4-20250514 via the
  artifact API for a real streaming analysis (requires API key in session).
• Enhanced charts: waterfall with sub-components, scatter frontier with quadrant lines,
  service performance radar, contract leakage Sankey-style waterfall.
"""

from __future__ import annotations

import math
import json
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
    import plotly.express as px
    PLOTLY_AVAILABLE = True
except Exception:
    go = None
    px = None
    PLOTLY_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS & DEFAULTS
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_ACTIVE_COUNTRIES = ["Brazil", "Mexico", "Argentina", "Colombia"]
COUNTRY_OPTIONS = [
    "Brazil", "Mexico", "Argentina", "Colombia", "Chile", "Peru", "Uruguay", "Paraguay",
    "Ecuador", "Bolivia", "Costa Rica", "Guatemala", "Panama", "Dominican Republic",
    "United States", "Canada", "China", "India", "Germany", "France", "Spain", "Italy",
    "Netherlands", "United Kingdom", "Japan", "South Korea", "Thailand", "Indonesia", "Malaysia",
]
COUNTRY_GEO_POINTS = {
    "Brazil": {"lat": -14.2350, "lon": -51.9253},
    "Mexico": {"lat": 23.6345, "lon": -102.5528},
    "Argentina": {"lat": -38.4161, "lon": -63.6167},
    "Colombia": {"lat": 4.5709, "lon": -74.2973},
    "Chile": {"lat": -35.6751, "lon": -71.5430},
    "Peru": {"lat": -9.1900, "lon": -75.0152},
    "Uruguay": {"lat": -32.5228, "lon": -55.7658},
    "Paraguay": {"lat": -23.4425, "lon": -58.4438},
    "Ecuador": {"lat": -1.8312, "lon": -78.1834},
    "Bolivia": {"lat": -16.2902, "lon": -63.5887},
    "Costa Rica": {"lat": 9.7489, "lon": -83.7534},
    "Guatemala": {"lat": 15.7835, "lon": -90.2308},
    "Panama": {"lat": 8.5380, "lon": -80.7821},
    "Dominican Republic": {"lat": 18.7357, "lon": -70.1627},
    "United States": {"lat": 39.8283, "lon": -98.5795},
    "Canada": {"lat": 56.1304, "lon": -106.3468},
    "China": {"lat": 35.8617, "lon": 104.1954},
    "India": {"lat": 20.5937, "lon": 78.9629},
    "Germany": {"lat": 51.1657, "lon": 10.4515},
    "France": {"lat": 46.2276, "lon": 2.2137},
    "Spain": {"lat": 40.4637, "lon": -3.7492},
    "Italy": {"lat": 41.8719, "lon": 12.5674},
    "Netherlands": {"lat": 52.1326, "lon": 5.2913},
    "United Kingdom": {"lat": 55.3781, "lon": -3.4360},
    "Japan": {"lat": 36.2048, "lon": 138.2529},
    "South Korea": {"lat": 35.9078, "lon": 127.7669},
    "Thailand": {"lat": 15.8700, "lon": 100.9925},
    "Indonesia": {"lat": -0.7893, "lon": 113.9213},
    "Malaysia": {"lat": 4.2105, "lon": 101.9758},
}
LOCALITY_PRESETS = {
    "Brazil": [
        {"name": "São Paulo", "lat": -23.5505, "lon": -46.6333},
        {"name": "Rio de Janeiro", "lat": -22.9068, "lon": -43.1729},
        {"name": "Minas Gerais", "lat": -19.9167, "lon": -43.9345},
        {"name": "Paraná", "lat": -25.4284, "lon": -49.2733},
        {"name": "Bahia", "lat": -12.9777, "lon": -38.5016},
        {"name": "Pernambuco", "lat": -8.0476, "lon": -34.8770},
        {"name": "Rio Grande do Sul", "lat": -30.0346, "lon": -51.2177},
        {"name": "Goiás", "lat": -16.6869, "lon": -49.2648},
    ],
    "Mexico": [
        {"name": "Mexico City", "lat": 19.4326, "lon": -99.1332},
        {"name": "Monterrey", "lat": 25.6866, "lon": -100.3161},
        {"name": "Guadalajara", "lat": 20.6597, "lon": -103.3496},
        {"name": "Querétaro", "lat": 20.5888, "lon": -100.3899},
        {"name": "Puebla", "lat": 19.0414, "lon": -98.2063},
    ],
    "Argentina": [
        {"name": "Buenos Aires", "lat": -34.6037, "lon": -58.3816},
        {"name": "Córdoba", "lat": -31.4201, "lon": -64.1888},
        {"name": "Rosario", "lat": -32.9442, "lon": -60.6505},
        {"name": "Mendoza", "lat": -32.8895, "lon": -68.8458},
    ],
    "Colombia": [
        {"name": "Bogotá", "lat": 4.7110, "lon": -74.0721},
        {"name": "Medellín", "lat": 6.2442, "lon": -75.5812},
        {"name": "Cali", "lat": 3.4516, "lon": -76.5320},
        {"name": "Barranquilla", "lat": 10.9685, "lon": -74.7813},
    ],
}
LOCALITY_FALLBACKS = [
    {"name": "North region", "lat_offset": 4.0, "lon_offset": 0.0},
    {"name": "Central region", "lat_offset": 0.0, "lon_offset": 0.0},
    {"name": "South region", "lat_offset": -4.0, "lon_offset": 0.0},
    {"name": "East region", "lat_offset": 0.0, "lon_offset": 4.0},
    {"name": "West region", "lat_offset": 0.0, "lon_offset": -4.0},
]
COUNTRIES = DEFAULT_ACTIVE_COUNTRIES.copy()
VIEW_SCOPE = "Global View"
ANCHOR_COUNTRY = "Brazil"
LOCALITY_COORDS: Dict = {}
PRIMARY_COUNTRY = "Brazil"
SECONDARY_GROUP = "LATAM"
LATAM_COUNTRIES = ["Mexico", "Argentina", "Colombia"]
SUPPLIERS = [
    "ChemPrime", "OleoGlobal", "Oleo Overseas Trading Co.",
    "Comercio de Oleos Nacional Distribuicao",
    "Supplier 05", "Supplier 06", "Supplier 07", "Supplier 08",
    "Supplier 09", "Supplier 10", "Supplier 11", "Supplier 12",
    "Supplier 13", "Supplier 14", "Supplier 15",
]
SUPPLIER_POOL = SUPPLIERS.copy()
SHORT_SUPPLIER = {
    "ChemPrime": "ChemPrime",
    "OleoGlobal": "OleoGlobal",
    "Oleo Overseas Trading Co.": "Overseas",
    "Comercio de Oleos Nacional Distribuicao": "Distribuicao",
    **{f"Supplier {i:02d}": f"Supplier {i:02d}" for i in range(5, 16)},
}
DEFAULT_SUPPLIER_DISPLAY_NAME = {s: s for s in SUPPLIERS}
DEFAULT_SUPPLIER_SHORT_NAME = SHORT_SUPPLIER.copy()

DEFAULT_CURRENT_SPEND = {"Brazil": 13_000_000.0, "Mexico": 3_000_000.0, "Argentina": 2_500_000.0, "Colombia": 1_500_000.0}
DEFAULT_FINANCIAL_RATE = {"Brazil": 4.84, "Mexico": 2.32, "Argentina": 10.52, "Colombia": 3.07}
DEFAULT_REFERENCE_DAYS = {c: 120 for c in COUNTRIES}
DEFAULT_CURRENT_TERM = {"Brazil": 120, "Mexico": 60, "Argentina": 60, "Colombia": 60}
DEFAULT_TREASURY_RETURN = {"Brazil": 5.07, "Mexico": 2.50, "Argentina": 10.90, "Colombia": 3.40}
DEFAULT_TREASURY_REF_DAYS = {c: 120 for c in COUNTRIES}
DEFAULT_INVENTORY_CARRY_RATE = {"Brazil": 23.0, "Mexico": 15.0, "Argentina": 35.0, "Colombia": 22.0}
DEFAULT_CURRENT_INVENTORY_DAYS = {c: 30 for c in COUNTRIES}

DEFAULT_ITEM_NAME = "Isopropyl Palmitate"
DEFAULT_NEGOTIATED_UNIT = "kg"
CURRENCY_OPTIONS = ["BRL", "USD", "EUR", "MXN", "ARS", "COP", "CNY"]
INCOTERM_OPTIONS = ["EXW", "FCA", "FOB", "CFR", "CIF", "DAP", "DDP"]
DEFAULT_DIRECT_VOLUME = {"Brazil": 1_000_000.0, "Mexico": 250_000.0, "Argentina": 200_000.0, "Colombia": 125_000.0}
DEFAULT_DIRECT_CURRENCY = {"Brazil": "BRL", "Mexico": "USD", "Argentina": "USD", "Colombia": "USD"}
DEFAULT_FX_TO_REPORTING = {"BRL": 1.0, "USD": 5.30, "EUR": 5.75, "MXN": 0.30, "ARS": 0.0045, "COP": 0.00135, "CNY": 0.73}
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

# ── INDIRECT / SERVICES CONFIGURATION ────────────────────────────────────────
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
        "icon": "💻", "color": "#6366f1",
        "pricing_models": ["T&M rate card", "FTE-based outsourcing", "Fixed fee project", "Managed service SLA", "Outcome-based / DevOps"],
        "driver_label": "FTE-months, tickets, story points or sprints",
        "productivity_label": "automation rate, ticket deflection %, cycle-time reduction, engineering velocity or toil elimination",
        "field_labels": ["FTEs / squad members", "Tickets or story points / month", "Critical systems covered"],
        "benchmark_fte_cost": 120_000.0,
        "sla_kpis": ["Uptime %", "MTTR (hours)", "Ticket SLA %", "Defect escape rate", "Deployment frequency"],
        "leakage_drivers": ["Scope additions", "Emergency changes", "Tool licensing overruns", "Rework / bug fix cost", "Unplanned incidents"],
    },
    "Facilities / Cleaning & Workplace": {
        "icon": "🏢", "color": "#0ea5e9",
        "pricing_models": ["Rate per m²", "Fixed monthly fee", "FTE-based service", "Unit visit rate", "Performance-based"],
        "driver_label": "m², sites, visits or headcount served",
        "productivity_label": "frequency optimization, route density, material consumption reduction or supervision productivity",
        "field_labels": ["Area serviced (m²)", "Sites / buildings", "Service frequency / month"],
        "benchmark_fte_cost": 35_000.0,
        "sla_kpis": ["Cleaning score / audit", "Compliance rate %", "Incident response time", "Material consumption vs budget", "Absenteeism rate"],
        "leakage_drivers": ["Extra cleaning calls", "Consumable overruns", "Emergency call-outs", "Supervisor overhead", "Absenteeism cover cost"],
    },
    "Industrial MRO / VMI / Fastenal-style outsourcing": {
        "icon": "🧰", "color": "#f59e0b",
        "pricing_models": ["VMI managed service fee", "Cost plus fee", "Unit transaction fee", "FTE-based onsite service", "Consumption-based"],
        "driver_label": "SKUs, transactions, sites, vending machines or tool-crib workload",
        "productivity_label": "inventory reduction, stockout avoidance, technician productivity, tool-crib automation or consumption control",
        "field_labels": ["Managed SKUs", "Transactions / month", "Sites / vending points"],
        "benchmark_fte_cost": 55_000.0,
        "sla_kpis": ["Fill rate %", "Stockout events / month", "Inventory turnover", "Vending uptime %", "Transaction accuracy %"],
        "leakage_drivers": ["Emergency procurement", "Stockout downtime cost", "Excess inventory carrying", "Unauthorized purchasing", "Write-offs / obsolescence"],
    },
    "Professional Services / Consulting": {
        "icon": "🧠", "color": "#8b5cf6",
        "pricing_models": ["Fixed fee project", "T&M rate card", "Retainer", "Success fee", "Blended model"],
        "driver_label": "milestones, consultant days, workstreams or deliverables",
        "productivity_label": "faster implementation, capability transfer, reduced internal effort or measurable business impact",
        "field_labels": ["Senior consultant days", "Analyst / consultant days", "Milestones / deliverables"],
        "benchmark_fte_cost": 250_000.0,
        "sla_kpis": ["Milestone on-time %", "Deliverable acceptance rate", "Stakeholder satisfaction (NPS)", "Knowledge transfer score", "Benefit realization %"],
        "leakage_drivers": ["Scope creep / change orders", "Rework and iterations", "Delayed sign-offs (idle time)", "Unplanned senior escalations", "Post-project fix cost"],
    },
    "Marketing / Agency Services": {
        "icon": "🎯", "color": "#ec4899",
        "pricing_models": ["Monthly retainer", "Project fee", "Pass-through + agency fee", "Rate card", "Performance-linked"],
        "driver_label": "campaigns, assets, production jobs, media pass-through or usage rights",
        "productivity_label": "asset reuse, lower rework, campaign cycle-time reduction or media efficiency",
        "field_labels": ["Campaigns / month", "Assets / deliverables", "Media pass-through budget"],
        "benchmark_fte_cost": 95_000.0,
        "sla_kpis": ["On-time delivery %", "First-time approval rate %", "Campaign ROI vs target", "Asset reuse rate %", "Revision rounds per asset"],
        "leakage_drivers": ["Revision / rework cost", "Rush fees and premiums", "Unused assets / over-production", "Untracked pass-through", "IP / rights overruns"],
    },
    "Logistics / Transport Services": {
        "icon": "🚚", "color": "#10b981",
        "pricing_models": ["Rate per shipment", "Dedicated route / vehicle", "Cost plus fee", "SLA-based logistics service", "Dynamic/spot pricing"],
        "driver_label": "shipments, km, routes, pallets or dedicated vehicles",
        "productivity_label": "load factor improvement, route optimization, fewer expedites or warehouse throughput gain",
        "field_labels": ["Shipments / month", "Average km or routes", "Dedicated vehicles / lanes"],
        "benchmark_fte_cost": 42_000.0,
        "sla_kpis": ["OTIF %", "Damage rate %", "Cost per pallet/km vs budget", "Expedite frequency", "Driver / asset utilization %"],
        "leakage_drivers": ["Expedite / emergency freight", "Detention and demurrage", "Damage / claims cost", "Fuel surcharge overruns", "Dead mileage / empty runs"],
    },
    "BPO / Call Center": {
        "icon": "🎧", "color": "#06b6d4",
        "pricing_models": ["FTE-based", "Cost per contact", "SLA-based managed service", "Outcome-based", "Hybrid FTE + volume"],
        "driver_label": "contacts, calls, cases, FTEs or resolved transactions",
        "productivity_label": "AHT reduction, containment, automation, first-contact resolution or lower escalation rate",
        "field_labels": ["Contacts / month", "FTEs", "Target AHT / productivity index"],
        "benchmark_fte_cost": 38_000.0,
        "sla_kpis": ["AHT (seconds)", "First contact resolution %", "CSAT score", "Abandon rate %", "Containment / automation rate %"],
        "leakage_drivers": ["Overtime / surge staffing", "Escalation handling cost", "Retraining / attrition cost", "QA failures / rework", "Non-compliant transactions"],
    },
    "Generic Indirect Service": {
        "icon": "🧾", "color": "#64748b",
        "pricing_models": ["Fixed fee", "T&M rate card", "Unit rate", "Retainer", "Pass-through + fee"],
        "driver_label": "service units, hours, FTEs, projects or sites",
        "productivity_label": "supplier-led productivity, demand reduction, process improvement or service efficiency",
        "field_labels": ["Service units", "Hours / month", "Sites / users covered"],
        "benchmark_fte_cost": 60_000.0,
        "sla_kpis": ["SLA compliance %", "Quality score", "Stakeholder satisfaction", "Delivery on-time %", "Incident frequency"],
        "leakage_drivers": ["Scope additions", "Emergency requests", "Rework cost", "Overhead overruns", "Unplanned escalations"],
    },
}
SERVICE_SCORECARD_WEIGHTS = {
    "Cost competitiveness": 18.0, "SLA / Delivery": 18.0, "Quality of service": 14.0,
    "Stakeholder satisfaction": 12.0, "Contract compliance": 10.0,
    "Productivity / Innovation": 10.0, "Overtime control": 8.0,
    "Risk & compliance": 5.0, "ESG / diversity": 5.0,
}
SUPPLIER_GOVERNANCE_WEIGHTS = {
    "OTIF / SLA delivery": 18.0, "Quality / NCR performance": 15.0,
    "Financial health": 12.0, "Compliance / due diligence": 15.0,
    "ESG / ethics": 10.0, "Cyber / data security": 8.0,
    "Labor / HSE": 10.0, "Stakeholder satisfaction": 12.0,
}
DUE_DILIGENCE_STATUS_OPTIONS = ["Clear", "Minor gaps", "Material gaps", "Not approved"]
CUSTOM_FACTOR_TYPES = [
    "Cost add-on", "Cost reduction / saving", "Productivity gain",
    "Risk increase", "Risk reduction", "Score bonus / penalty",
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
DEFAULT_SERVICE_CONTRACT_VALUE = {"Brazil": 13_000_000.0, "Mexico": 3_000_000.0, "Argentina": 2_500_000.0, "Colombia": 1_500_000.0}

COUNTRY_DEFAULT_TEMPLATE = {
    "current_spend": 1_000_000.0, "financial_rate": 3.0, "reference_days": 60,
    "current_term": 60, "treasury_return": 2.0, "treasury_ref_days": 60,
    "inventory_carry_rate": 20.0, "current_inventory_days": 30,
    "direct_volume": 100_000.0, "direct_currency": "USD",
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


for _c in COUNTRY_OPTIONS:
    seed_country_defaults(_c)


def _stable_offset(text: str, scale: float = 1.6) -> tuple[float, float]:
    seed = sum((idx + 1) * ord(ch) for idx, ch in enumerate(text))
    return ((seed % 17) - 8) / 8 * scale, (((seed // 17) % 17) - 8) / 8 * scale


def get_country_geo(country: str) -> dict:
    return COUNTRY_GEO_POINTS.get(country, {"lat": 0.0, "lon": 0.0})


def build_locality_options(anchor_country: str) -> list[dict]:
    presets = LOCALITY_PRESETS.get(anchor_country)
    if presets:
        return presets
    base = get_country_geo(anchor_country)
    return [
        {"name": f"{anchor_country} - {item['name']}", "lat": base["lat"] + item["lat_offset"], "lon": base["lon"] + item["lon_offset"]}
        for item in LOCALITY_FALLBACKS
    ]


def coord_for_analysis_unit(unit: str, anchor_country: str | None = None) -> dict:
    if unit in LOCALITY_COORDS:
        return LOCALITY_COORDS[unit]
    if unit in COUNTRY_GEO_POINTS:
        return COUNTRY_GEO_POINTS[unit]
    base = get_country_geo(anchor_country or ANCHOR_COUNTRY)
    dlat, dlon = _stable_offset(unit)
    return {"lat": base["lat"] + dlat, "lon": base["lon"] + dlon}


def ensure_analysis_unit_defaults(unit: str, template_country: str | None = None) -> None:
    template_country = template_country or unit
    if unit not in DEFAULT_CURRENT_SPEND:
        seed_country_defaults(unit)
        if template_country in DEFAULT_CURRENT_SPEND:
            DEFAULT_CURRENT_SPEND[unit] = max(DEFAULT_CURRENT_SPEND.get(template_country, 1_000_000.0) / 4.0, 100_000.0)
            for k in ["DEFAULT_FINANCIAL_RATE", "DEFAULT_TREASURY_RETURN", "DEFAULT_INVENTORY_CARRY_RATE"]:
                globals()[k].setdefault(unit, globals()[k].get(template_country, COUNTRY_DEFAULT_TEMPLATE.get(k.replace("DEFAULT_", "").lower(), 3.0)))
            DEFAULT_DIRECT_VOLUME[unit] = max(DEFAULT_DIRECT_VOLUME.get(template_country, 100_000.0) / 4.0, 10_000.0)
            DEFAULT_DIRECT_CURRENCY[unit] = DEFAULT_DIRECT_CURRENCY.get(template_country, "USD")
            DEFAULT_SERVICE_CONTRACT_VALUE[unit] = max(DEFAULT_SERVICE_CONTRACT_VALUE.get(template_country, 1_000_000.0) / 4.0, 100_000.0)
    DEFAULT_PROPOSAL_SPEND.setdefault(unit, {})
    DEFAULT_PAYMENT_TERM.setdefault(unit, {})
    DEFAULT_LEAD_TIME_DAYS.setdefault(unit, {})
    DEFAULT_SAFETY_STOCK_DAYS.setdefault(unit, {})
    DEFAULT_INVENTORY_OWNERSHIP.setdefault(unit, {})
    DEFAULT_SHARES.setdefault(unit, {})
    base_spend = float(DEFAULT_CURRENT_SPEND.get(unit, 1_000_000.0))
    for supplier in SUPPLIER_POOL:
        DEFAULT_PROPOSAL_SPEND[unit].setdefault(supplier, base_spend)
        DEFAULT_PAYMENT_TERM[unit].setdefault(supplier, int(DEFAULT_CURRENT_TERM.get(unit, 60)))
        DEFAULT_LEAD_TIME_DAYS[unit].setdefault(supplier, 30)
        DEFAULT_SAFETY_STOCK_DAYS[unit].setdefault(supplier, 0)
        DEFAULT_INVENTORY_OWNERSHIP[unit].setdefault(supplier, "Supplier/trader owns until delivery")
        DEFAULT_SHARES[unit].setdefault(supplier, 0.0)


DEFAULT_PROPOSAL_SPEND = {
    "Brazil": {"ChemPrime": 16_250_000.0, "OleoGlobal": 9_750_000.0, "Oleo Overseas Trading Co.": 10_237_500.0, "Comercio de Oleos Nacional Distribuicao": 10_530_000.0},
    "Mexico": {"ChemPrime": 3_750_000.0, "OleoGlobal": 2_250_000.0, "Oleo Overseas Trading Co.": 2_362_500.0, "Comercio de Oleos Nacional Distribuicao": 2_430_000.0},
    "Argentina": {"ChemPrime": 3_125_000.0, "OleoGlobal": 1_875_000.0, "Oleo Overseas Trading Co.": 1_968_750.0, "Comercio de Oleos Nacional Distribuicao": 2_025_000.0},
    "Colombia": {"ChemPrime": 1_875_000.0, "OleoGlobal": 1_125_000.0, "Oleo Overseas Trading Co.": 1_181_250.0, "Comercio de Oleos Nacional Distribuicao": 1_215_000.0},
}
DEFAULT_PAYMENT_TERM = {c: {"ChemPrime": 90, "OleoGlobal": 70, "Oleo Overseas Trading Co.": 150, "Comercio de Oleos Nacional Distribuicao": 120} for c in COUNTRIES}
DEFAULT_LEAD_TIME_DAYS = {c: {"ChemPrime": 30, "OleoGlobal": 120, "Oleo Overseas Trading Co.": 120, "Comercio de Oleos Nacional Distribuicao": 30} for c in COUNTRIES}
DEFAULT_SAFETY_STOCK_DAYS = {c: {s: 0 for s in SUPPLIERS} for c in COUNTRIES}
INVENTORY_OWNERSHIP_OPTIONS = [
    "Buyer owns transit + safety stock", "Buyer owns safety stock only",
    "Supplier/trader owns until delivery", "Distributor holds local stock",
]
DEFAULT_INVENTORY_OWNERSHIP = {
    c: {
        "ChemPrime": "Buyer owns safety stock only",
        "OleoGlobal": "Buyer owns transit + safety stock",
        "Oleo Overseas Trading Co.": "Supplier/trader owns until delivery",
        "Comercio de Oleos Nacional Distribuicao": "Distributor holds local stock",
    }
    for c in COUNTRIES
}
DEFAULT_SHARES = {
    c: {"ChemPrime": 40.0, "OleoGlobal": 0.0, "Oleo Overseas Trading Co.": 40.0, "Comercio de Oleos Nacional Distribuicao": 20.0}
    for c in COUNTRIES
}
DEFAULT_KRALJIC_REQUIRED = {"ChemPrime": True, "OleoGlobal": False, "Oleo Overseas Trading Co.": False, "Comercio de Oleos Nacional Distribuicao": False}
DEFAULT_MIN_SHARE = {"ChemPrime": 40.0, "OleoGlobal": 0.0, "Oleo Overseas Trading Co.": 0.0, "Comercio de Oleos Nacional Distribuicao": 0.0}
DEFAULT_MAX_SHARE = {s: 100.0 for s in SUPPLIERS}
DEFAULT_APPROVED = {s: True for s in SUPPLIERS}
DEFAULT_RISK = {
    "ChemPrime": {"Supply": 2.0, "Quality": 2.0, "Financial": 2.0, "Compliance": 1.5, "ESG": 2.0, "Logistics": 2.0},
    "OleoGlobal": {"Supply": 3.0, "Quality": 2.5, "Financial": 2.5, "Compliance": 2.0, "ESG": 2.5, "Logistics": 2.5},
    "Oleo Overseas Trading Co.": {"Supply": 4.0, "Quality": 3.0, "Financial": 3.5, "Compliance": 3.0, "ESG": 3.0, "Logistics": 4.5},
    "Comercio de Oleos Nacional Distribuicao": {"Supply": 3.0, "Quality": 2.5, "Financial": 2.5, "Compliance": 2.0, "ESG": 2.5, "Logistics": 2.5},
}
DEFAULT_RISK_WEIGHTS = {"Supply": 30.0, "Quality": 20.0, "Financial": 15.0, "Compliance": 15.0, "ESG": 10.0, "Logistics": 10.0}

for _s in SUPPLIER_POOL:
    DEFAULT_SUPPLIER_DISPLAY_NAME.setdefault(_s, _s)
    DEFAULT_SUPPLIER_SHORT_NAME.setdefault(_s, SHORT_SUPPLIER.get(_s, _s))
    DEFAULT_KRALJIC_REQUIRED.setdefault(_s, False)
    DEFAULT_MIN_SHARE.setdefault(_s, 0.0)
    DEFAULT_MAX_SHARE.setdefault(_s, 100.0)
    DEFAULT_APPROVED.setdefault(_s, True)
    DEFAULT_RISK.setdefault(_s, {dim: 3.0 for dim in DEFAULT_RISK_WEIGHTS})

for _c in COUNTRY_OPTIONS:
    seed_country_defaults(_c)
    _bs = DEFAULT_CURRENT_SPEND[_c]
    DEFAULT_PROPOSAL_SPEND.setdefault(_c, {})
    DEFAULT_PAYMENT_TERM.setdefault(_c, {})
    DEFAULT_LEAD_TIME_DAYS.setdefault(_c, {})
    DEFAULT_SAFETY_STOCK_DAYS.setdefault(_c, {})
    DEFAULT_INVENTORY_OWNERSHIP.setdefault(_c, {})
    DEFAULT_SHARES.setdefault(_c, {})
    for _s in SUPPLIER_POOL:
        DEFAULT_PROPOSAL_SPEND[_c].setdefault(_s, _bs)
        DEFAULT_PAYMENT_TERM[_c].setdefault(_s, DEFAULT_CURRENT_TERM[_c])
        DEFAULT_LEAD_TIME_DAYS[_c].setdefault(_s, 30)
        DEFAULT_SAFETY_STOCK_DAYS[_c].setdefault(_s, 0)
        DEFAULT_INVENTORY_OWNERSHIP[_c].setdefault(_s, "Supplier/trader owns until delivery")
        DEFAULT_SHARES[_c].setdefault(_s, 0.0)

# ── DESIGN TOKENS ─────────────────────────────────────────────────────────────
GRAPHITE = "#0f172a"
GREEN = "#10b981"
RED = "#ef4444"
BLUE = "#3b82f6"
AMBER = "#f59e0b"
PURPLE = "#8b5cf6"
CYAN = "#06b6d4"

RESULT_STACK_OPTIONS = [
    "Top supplier focus lens", "Total project saving", "AI Executive Copilot",
    "Total cost stack", "Reference supplier condition stack", "Working capital carry view",
    "Total decomposition", "Brazil result", "LATAM result", "Decision recommendation",
    "Charts", "Working capital economic view", "Detailed data", "Download export",
]

# ─────────────────────────────────────────────────────────────────────────────
# PAGE SETUP & PREMIUM CSS
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Procurement Intelligence Platform",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=Inter:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
""", unsafe_allow_html=True)

st.markdown("""
<style>
/* ── FOUNDATIONS ─────────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; }

html, body, [data-testid="stApp"] {
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    background: #050b18 !important;
    color: #e2e8f0;
}
.block-container {
    padding: 1.5rem 2rem 4rem 2rem !important;
    max-width: 1800px !important;
}

/* ── SIDEBAR ─────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0a1628 0%, #0d1f3c 100%) !important;
    border-right: 1px solid rgba(59,130,246,.18) !important;
}
[data-testid="stSidebar"] * { font-family: 'Inter', -apple-system, system-ui, sans-serif !important; }
[data-testid="stSidebar"] label { color: #94a3b8 !important; font-size: .80rem !important; font-weight: 500 !important; }
[data-testid="stSidebar"] .stMarkdown h2 {
    font-family: 'Libre Baskerville', Georgia, serif !important;
    color: #f1f5f9 !important; font-size: 1.05rem !important;
    border-bottom: 1px solid rgba(59,130,246,.25) !important;
    padding-bottom: .5rem !important; margin-bottom: .75rem !important;
}
[data-testid="stSidebar"] .stMarkdown h3 {
    font-family: 'Libre Baskerville', Georgia, serif !important;
    color: #7dd3fc !important; font-size: .82rem !important; letter-spacing: .07em !important;
    text-transform: uppercase !important; margin-top: 1.2rem !important;
}
[data-testid="stSidebar"] input, [data-testid="stSidebar"] select {
    background: rgba(15,23,42,.8) !important;
    border: 1px solid rgba(148,163,184,.18) !important;
    border-radius: 8px !important; color: #e2e8f0 !important;
}
[data-testid="stSidebar"] .stRadio label { color: #cbd5e1 !important; }
[data-testid="stSidebar"] .stSlider [data-baseweb="slider"] div[role="slider"] {
    background: #3b82f6 !important;
}

/* ── TABS ─────────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: rgba(15,23,42,.6) !important;
    border: 1px solid rgba(148,163,184,.15) !important;
    border-radius: 14px !important; padding: 4px !important;
    gap: 2px !important; margin-bottom: 1.5rem !important;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    background: transparent !important;
    border-radius: 10px !important;
    font-family: 'Inter', -apple-system, system-ui, sans-serif !important;
    font-weight: 600 !important; font-size: .82rem !important;
    color: #94a3b8 !important; letter-spacing: .03em !important;
    padding: 8px 16px !important; transition: all .2s ease !important;
}
[data-testid="stTabs"] [aria-selected="true"] {
    background: linear-gradient(135deg, #1d4ed8 0%, #3b82f6 100%) !important;
    color: #ffffff !important;
    box-shadow: 0 4px 14px rgba(59,130,246,.35) !important;
}

/* ── EXPANDERS ────────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    background: rgba(15,23,42,.55) !important;
    border: 1px solid rgba(148,163,184,.16) !important;
    border-radius: 18px !important;
    margin: 12px 0 16px 0 !important;
    overflow: hidden !important;
    backdrop-filter: blur(12px) !important;
    box-shadow: 0 8px 32px rgba(0,0,0,.25) !important;
    transition: box-shadow .2s ease !important;
}
[data-testid="stExpander"]:hover {
    box-shadow: 0 12px 40px rgba(0,0,0,.35) !important;
}
[data-testid="stExpander"] details summary {
    background: linear-gradient(135deg, rgba(15,23,42,.95) 0%, rgba(30,41,59,.9) 100%) !important;
    padding: 16px 20px !important; min-height: 64px !important;
    font-family: 'Libre Baskerville', Georgia, serif !important;
    font-weight: 700 !important; font-size: .95rem !important;
    color: #f1f5f9 !important;
    border-left: 4px solid var(--exp-accent, #3b82f6) !important;
    cursor: pointer !important;
    transition: filter .15s ease, transform .15s ease !important;
    display: flex !important; align-items: center !important;
}
[data-testid="stExpander"] details summary:hover { filter: brightness(1.1) !important; }
[data-testid="stExpander"] details > div[data-testid="stExpanderDetails"] {
    padding: 16px 20px 20px 20px !important;
}

/* ── INPUTS ────────────────────────────────────────────────────────────────── */
[data-testid="stNumberInput"] input,
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea {
    background: rgba(15,23,42,.7) !important;
    border: 1px solid rgba(148,163,184,.20) !important;
    border-radius: 8px !important; color: #e2e8f0 !important;
    font-family: 'Inter', -apple-system, system-ui, sans-serif !important;
    transition: border-color .15s ease !important;
}
[data-testid="stNumberInput"] input:focus,
[data-testid="stTextInput"] input:focus {
    border-color: #3b82f6 !important;
    box-shadow: 0 0 0 2px rgba(59,130,246,.2) !important;
}
[data-testid="stSelectbox"] > div > div {
    background: rgba(15,23,42,.7) !important;
    border: 1px solid rgba(148,163,184,.20) !important;
    border-radius: 8px !important; color: #e2e8f0 !important;
}
label {
    color: #94a3b8 !important; font-size: .78rem !important;
    font-weight: 500 !important; letter-spacing: .03em !important;
}

/* ── BUTTONS ───────────────────────────────────────────────────────────────── */
[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #1d4ed8 0%, #3b82f6 100%) !important;
    border: none !important; border-radius: 10px !important;
    color: #ffffff !important; font-family: 'Libre Baskerville', Georgia, serif !important;
    font-weight: 700 !important; font-size: .88rem !important;
    letter-spacing: .04em !important; padding: 10px 20px !important;
    box-shadow: 0 4px 15px rgba(59,130,246,.35) !important;
    transition: all .2s ease !important;
}
[data-testid="stButton"] > button[kind="primary"]:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 25px rgba(59,130,246,.5) !important;
    filter: brightness(1.08) !important;
}
[data-testid="stButton"] > button[kind="secondary"] {
    background: rgba(30,41,59,.6) !important;
    border: 1px solid rgba(148,163,184,.25) !important;
    border-radius: 10px !important; color: #cbd5e1 !important;
    font-family: 'Inter', -apple-system, system-ui, sans-serif !important; font-weight: 600 !important;
}
.stDownloadButton > button {
    background: linear-gradient(135deg, #064e3b 0%, #065f46 100%) !important;
    border: 1px solid rgba(16,185,129,.3) !important;
    border-radius: 10px !important; color: #d1fae5 !important;
    font-family: 'Libre Baskerville', Georgia, serif !important; font-weight: 700 !important;
}

/* ── DATAFRAMES ─────────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border-radius: 14px !important; overflow: hidden !important;
    border: 1px solid rgba(148,163,184,.18) !important;
}
[data-testid="stDataFrame"] thead th {
    background: rgba(15,23,42,.9) !important;
    font-family: 'Inter', -apple-system, system-ui, sans-serif !important; font-weight: 600 !important;
    color: #7dd3fc !important; font-size: .75rem !important;
    letter-spacing: .06em !important; text-transform: uppercase !important;
}
[data-testid="stDataFrame"] tbody tr:nth-child(even) {
    background: rgba(30,41,59,.4) !important;
}
[data-testid="stDataFrame"] tbody td {
    color: #cbd5e1 !important; font-size: .82rem !important;
    font-family: 'Inter', -apple-system, system-ui, sans-serif !important;
    font-variant-numeric: tabular-nums !important;
}

/* ── ALERTS ─────────────────────────────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 12px !important; font-family: 'Inter', -apple-system, system-ui, sans-serif !important;
}
[data-testid="stAlert"][data-baseweb="notification"] {
    background: rgba(30,58,138,.25) !important;
    border: 1px solid rgba(59,130,246,.3) !important;
    color: #bfdbfe !important;
}
.stSuccess { background: rgba(6,78,59,.25) !important; border: 1px solid rgba(16,185,129,.3) !important; }
.stError { background: rgba(127,29,29,.25) !important; border: 1px solid rgba(239,68,68,.3) !important; }
.stWarning { background: rgba(120,53,15,.25) !important; border: 1px solid rgba(245,158,11,.3) !important; }

/* ── SLIDERS ─────────────────────────────────────────────────────────────────── */
[data-baseweb="slider"] [role="slider"] {
    background: #3b82f6 !important;
    box-shadow: 0 0 0 3px rgba(59,130,246,.25) !important;
}
[data-baseweb="slider"] div[data-baseweb="slider"] > div:first-child {
    background: rgba(148,163,184,.2) !important;
}

/* ── ANIMATIONS ──────────────────────────────────────────────────────────────── */
@keyframes fadeSlideUp {
    from { opacity: 0; transform: translateY(16px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes glowPulse {
    0%, 100% { box-shadow: 0 0 20px rgba(59,130,246,.15); }
    50% { box-shadow: 0 0 40px rgba(59,130,246,.30); }
}
@keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
}
@keyframes countUp {
    from { opacity: 0; transform: scale(.92); }
    to { opacity: 1; transform: scale(1); }
}

/* ── CUSTOM COMPONENTS ────────────────────────────────────────────────────────── */

/* Hero banner */
.v46-hero {
    position: relative; overflow: hidden;
    background: linear-gradient(135deg, #0a0f1e 0%, #0d1b3e 40%, #1a1040 100%);
    border: 1px solid rgba(99,102,241,.25);
    border-radius: 24px; padding: 40px 44px 36px;
    margin-bottom: 28px;
    box-shadow: 0 24px 64px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.06);
    animation: fadeSlideUp .5s ease-out both;
}
.v46-hero::before {
    content: ''; position: absolute; top: -100px; right: -100px;
    width: 400px; height: 400px; border-radius: 50%;
    background: radial-gradient(circle, rgba(99,102,241,.18) 0%, transparent 70%);
    pointer-events: none;
}
.v46-hero::after {
    content: ''; position: absolute; bottom: -60px; left: 200px;
    width: 300px; height: 300px; border-radius: 50%;
    background: radial-gradient(circle, rgba(59,130,246,.12) 0%, transparent 70%);
    pointer-events: none;
}
.v46-hero-mode-chip {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 14px; border-radius: 999px;
    background: rgba(99,102,241,.18); border: 1px solid rgba(99,102,241,.35);
    color: #a5b4fc; font-family: 'IBM Plex Mono', 'Courier New', monospace; font-size: .72rem;
    font-weight: 500; letter-spacing: .08em; text-transform: uppercase;
    margin-bottom: 16px;
}
.v46-hero-mode-chip::before { content: '▶'; font-size: .6rem; opacity: .7; }
.v46-hero h1 {
    font-family: 'Libre Baskerville', Georgia, serif !important;
    font-size: 2.2rem; font-weight: 700; line-height: 1.12;
    background: linear-gradient(135deg, #f8fafc 30%, #a5b4fc 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text; margin-bottom: 12px;
}
.v46-hero p { color: rgba(203,213,225,.85); font-size: .98rem; max-width: 900px; line-height: 1.6; }
.v46-hero-stats {
    display: flex; gap: 28px; margin-top: 24px; padding-top: 20px;
    border-top: 1px solid rgba(148,163,184,.12);
}
.v46-hero-stat { display: flex; flex-direction: column; gap: 3px; }
.v46-hero-stat-label { font-size: .68rem; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; }
.v46-hero-stat-value { font-family: 'IBM Plex Mono', 'Courier New', monospace; font-size: .95rem; font-weight: 500; color: #7dd3fc; letter-spacing: .02em; }

/* Section headers */
.v46-section {
    padding: 12px 18px 12px 20px;
    background: rgba(15,23,42,.6); border: 1px solid rgba(148,163,184,.14);
    border-left: 4px solid var(--section-accent, #3b82f6);
    border-radius: 12px; margin: 24px 0 16px 0;
    backdrop-filter: blur(8px);
}
.v46-section-title {
    font-family: 'Libre Baskerville', Georgia, serif; font-size: 1.0rem; font-weight: 700;
    color: #f1f5f9; margin-bottom: 2px;
}
.v46-section-subtitle { font-size: .82rem; color: #94a3b8; line-height: 1.4; }

/* KPI cards */
.v46-kpi-grid { display: grid; gap: 14px; }
.v46-kpi {
    position: relative; overflow: hidden;
    background: rgba(15,23,42,.75);
    border: 1px solid rgba(148,163,184,.16);
    border-radius: 18px; padding: 20px 22px;
    backdrop-filter: blur(12px);
    box-shadow: 0 8px 24px rgba(0,0,0,.2);
    animation: fadeSlideUp .4s ease-out both;
    transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}
.v46-kpi:hover {
    transform: translateY(-3px);
    box-shadow: 0 16px 40px rgba(0,0,0,.3);
    border-color: rgba(99,102,241,.3);
}
.v46-kpi::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: var(--kpi-accent, linear-gradient(90deg, #3b82f6, #8b5cf6));
    opacity: .7;
}
.v46-kpi-label {
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    font-size: .68rem; font-weight: 600; color: #64748b;
    text-transform: uppercase; letter-spacing: .09em; margin-bottom: 10px;
    min-height: 30px; display: flex; align-items: flex-start;
}
.v46-kpi-value {
    font-family: 'Inter', -apple-system, system-ui, sans-serif; font-size: 1.38rem; font-weight: 600;
    line-height: 1.15; margin-bottom: 8px; letter-spacing: -.01em;
    font-variant-numeric: tabular-nums;
    animation: countUp .4s ease-out both;
}
.v46-kpi-helper { font-size: .76rem; color: #475569; line-height: 1.35; }
.v46-kpi.good .v46-kpi-value { color: #34d399; }
.v46-kpi.bad .v46-kpi-value { color: #f87171; }
.v46-kpi.neutral .v46-kpi-value { color: #60a5fa; }
.v46-kpi.amber .v46-kpi-value { color: #fbbf24; }
.v46-kpi.good::before { background: linear-gradient(90deg, #10b981, #34d399); }
.v46-kpi.bad::before { background: linear-gradient(90deg, #ef4444, #f87171); }
.v46-kpi.amber::before { background: linear-gradient(90deg, #f59e0b, #fbbf24); }

/* Decision card */
.v46-decision {
    border-radius: 20px; padding: 26px 30px; margin: 16px 0 20px 0;
    animation: fadeSlideUp .4s ease-out both;
}
.v46-decision.good {
    background: linear-gradient(135deg, rgba(6,78,59,.35), rgba(5,46,22,.45));
    border: 1px solid rgba(16,185,129,.25);
}
.v46-decision.bad {
    background: linear-gradient(135deg, rgba(127,29,29,.35), rgba(69,10,10,.45));
    border: 1px solid rgba(239,68,68,.25);
}
.v46-decision-title {
    font-family: 'Libre Baskerville', Georgia, serif; font-size: 1.2rem; font-weight: 700;
    color: #f1f5f9; margin-bottom: 8px;
}
.v46-decision-body { font-size: .95rem; color: #cbd5e1; line-height: 1.55; }

/* Service score badge */
.v46-score-badge {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 12px; border-radius: 999px;
    font-family: 'IBM Plex Mono', 'Courier New', monospace; font-weight: 600; font-size: .80rem;
    border: 1px solid currentColor;
}

/* Result card */
.v46-result-box {
    background: rgba(15,23,42,.6); border: 1px solid rgba(148,163,184,.16);
    border-radius: 16px; padding: 14px 18px; margin: 12px 0 16px 0;
    font-size: .85rem; line-height: 1.5; color: #cbd5e1;
    backdrop-filter: blur(8px);
}
.v46-result-box b { color: #f1f5f9; font-weight: 700; }

/* Open cost card */
.v46-opencost-card {
    background: rgba(30,27,75,.35); border: 1px solid rgba(139,92,246,.2);
    border-radius: 16px; padding: 14px 18px; margin: 10px 0 14px 0;
    font-size: .85rem; color: #c4b5fd; line-height: 1.5;
}

/* Chart shell */
.v46-chart {
    background: rgba(15,23,42,.6); border: 1px solid rgba(148,163,184,.14);
    border-radius: 20px; padding: 20px 18px;
    box-shadow: 0 12px 40px rgba(0,0,0,.25);
    backdrop-filter: blur(8px);
    animation: fadeSlideUp .5s ease-out both;
}
.v46-chart h4 {
    font-family: 'Libre Baskerville', Georgia, serif !important; font-size: .95rem !important;
    font-weight: 700 !important; color: #e2e8f0 !important;
    margin: 0 0 14px 0 !important;
}

/* AI Copilot card */
.v46-ai-card {
    background: linear-gradient(135deg, rgba(49,46,129,.35) 0%, rgba(15,23,42,.9) 100%);
    border: 1px solid rgba(99,102,241,.3); border-left: 5px solid #6366f1;
    border-radius: 20px; padding: 22px 26px; margin: 14px 0 18px 0;
    box-shadow: 0 12px 40px rgba(99,102,241,.12);
    animation: fadeSlideUp .4s ease-out both;
}
.v46-ai-card h4 {
    font-family: 'Libre Baskerville', Georgia, serif !important;
    color: #a5b4fc !important; font-size: 1.0rem !important; font-weight: 700 !important;
    margin: 0 0 12px 0 !important;
}
.v46-ai-card ul { margin: 8px 0 0 0; padding-left: 18px; }
.v46-ai-card li { color: #cbd5e1; margin-bottom: 8px; line-height: 1.5; }
.v46-ai-card li b { color: #e2e8f0; }

/* Mode card */
.v46-mode-card {
    background: linear-gradient(135deg, rgba(15,23,42,.9), rgba(30,41,59,.85));
    border: 1px solid rgba(59,130,246,.25); border-radius: 14px;
    padding: 14px 16px; margin: 10px 0 14px 0;
    box-shadow: 0 8px 24px rgba(0,0,0,.2);
}
.v46-mode-card-title { font-family: 'Libre Baskerville', Georgia, serif; font-weight: 700; color: #f1f5f9; font-size: .92rem; margin-bottom: 4px; }
.v46-mode-card-sub { font-size: .76rem; color: #94a3b8; line-height: 1.3; }

/* Market scope card */
.v46-market-card {
    background: linear-gradient(135deg, rgba(3,105,161,.2), rgba(30,27,75,.3));
    border: 1px solid rgba(14,165,233,.2); border-radius: 14px;
    padding: 14px 16px; margin: 10px 0 16px 0;
}
.v46-market-title { font-family: 'Libre Baskerville', Georgia, serif; font-weight: 700; color: #f1f5f9; font-size: .88rem; margin-bottom: 5px; }
.v46-market-meta { font-size: .75rem; color: #7dd3fc; margin-bottom: 8px; }
.v46-chip {
    display: inline-block; padding: 3px 9px; margin: 3px 3px 0 0;
    border-radius: 999px; background: rgba(255,255,255,.07);
    border: 1px solid rgba(255,255,255,.12); color: #e2e8f0;
    font-size: .70rem; font-weight: 700;
}

/* Governance card */
.v46-gov-card {
    background: rgba(15,23,42,.5); border: 1px solid rgba(148,163,184,.16);
    border-radius: 16px; padding: 18px 20px; margin: 10px 0 14px 0;
}

/* Supplier box */
.v46-supplier-box {
    background: rgba(15,23,42,.5); border: 1px solid rgba(148,163,184,.14);
    border-radius: 14px; padding: 16px 18px; margin-bottom: 14px;
}
.v46-pill {
    display: inline-block; padding: 4px 12px; border-radius: 999px;
    background: rgba(59,130,246,.15); border: 1px solid rgba(59,130,246,.25);
    color: #93c5fd; font-size: .76rem; font-weight: 700; font-family: 'IBM Plex Mono', 'Courier New', monospace;
}

/* Landed result */
.v46-landed {
    background: rgba(3,105,161,.12); border: 1px dashed rgba(14,165,233,.3);
    border-radius: 12px; padding: 10px 14px; margin-top: 10px;
    font-size: .84rem; color: #bae6fd; line-height: 1.5;
}
.v46-landed b { color: #e0f2fe; }

/* Insight box */
.v46-insight {
    background: rgba(15,23,42,.6); border: 1px solid rgba(148,163,184,.16);
    border-left: 5px solid #3b82f6; border-radius: 14px;
    padding: 18px 22px; color: #94a3b8; line-height: 1.5;
    font-size: .88rem;
}
.v46-insight b { color: #e2e8f0; }

/* Service result */
.v46-svc-result {
    background: rgba(76,29,149,.12); border: 1px dashed rgba(139,92,246,.3);
    border-radius: 12px; padding: 10px 14px; margin-top: 10px;
    font-size: .84rem; color: #e9d5ff; line-height: 1.6;
}
.v46-svc-result b { color: #f5f3ff; }

/* Service leakage waterfall */
.v46-leakage {
    background: rgba(120,53,15,.12); border: 1px solid rgba(245,158,11,.2);
    border-radius: 14px; padding: 14px 18px; margin: 12px 0;
}
.v46-leakage-title { font-family: 'Libre Baskerville', Georgia, serif; font-weight: 700; color: #fcd34d; font-size: .88rem; margin-bottom: 10px; }
.v46-leakage-row { display: flex; align-items: center; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid rgba(148,163,184,.08); }
.v46-leakage-row:last-child { border: none; font-weight: 700; color: #f59e0b; }
.v46-leakage-item { font-size: .82rem; color: #d1d5db; }
.v46-leakage-val { font-family: 'IBM Plex Mono', 'Courier New', monospace; font-size: .82rem; color: #fbbf24; }

/* Productivity ROI */
.v46-roi-badge {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 8px 16px; border-radius: 12px;
    background: rgba(6,78,59,.25); border: 1px solid rgba(16,185,129,.25);
    color: #6ee7b7; font-family: 'IBM Plex Mono', 'Courier New', monospace; font-size: .84rem; font-weight: 600;
    margin: 8px 0;
}

/* Supply chain heat chip */
.v46-heat-chip {
    display: inline-block; padding: 5px 12px; border-radius: 8px;
    font-family: 'IBM Plex Mono', 'Courier New', monospace; font-size: .76rem; font-weight: 600;
    margin: 3px;
}
.v46-heat-green { background: rgba(6,78,59,.4); border: 1px solid rgba(16,185,129,.3); color: #6ee7b7; }
.v46-heat-amber { background: rgba(120,53,15,.4); border: 1px solid rgba(245,158,11,.3); color: #fcd34d; }
.v46-heat-red { background: rgba(127,29,29,.4); border: 1px solid rgba(239,68,68,.3); color: #fca5a5; }

/* FTE decomposition */
.v46-fte-bar {
    height: 8px; border-radius: 4px; overflow: hidden;
    background: rgba(148,163,184,.1); margin: 6px 0;
}
.v46-fte-bar-fill {
    height: 100%; border-radius: 4px;
    background: linear-gradient(90deg, #3b82f6, #8b5cf6);
    transition: width .6s cubic-bezier(.22,.9,.24,1);
}

/* Visual breaker */
.v46-breaker {
    display: flex; align-items: center; gap: 14px;
    padding: 14px 18px; margin: 20px 0 14px 0;
    border-radius: 14px; border: 1px solid rgba(148,163,184,.15);
    background: rgba(15,23,42,.7);
    position: relative; overflow: hidden;
}
.v46-breaker::before {
    content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 5px;
    background: var(--br-color, #3b82f6);
}
.v46-breaker-icon {
    width: 40px; height: 40px; border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.2rem;
    background: var(--br-bg, rgba(59,130,246,.12));
    border: 1px solid var(--br-border, rgba(59,130,246,.25));
    flex-shrink: 0;
}
.v46-breaker-title { font-family: 'Libre Baskerville', Georgia, serif; font-weight: 700; color: #f1f5f9; font-size: 1.0rem; margin-bottom: 2px; }
.v46-breaker-sub { font-size: .82rem; color: #94a3b8; line-height: 1.3; }
.v46-breaker-tag {
    margin-left: auto; padding: 5px 12px; border-radius: 999px;
    font-size: .70rem; font-weight: 700; letter-spacing: .06em;
    text-transform: uppercase; color: #94a3b8;
    background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.10);
    white-space: nowrap; flex-shrink: 0;
}

/* Plain title */
.v46-plain-title {
    font-family: 'Libre Baskerville', Georgia, serif; font-size: .95rem; font-weight: 700;
    color: #e2e8f0; margin: 18px 0 10px 0;
    padding-bottom: 6px; border-bottom: 1px solid rgba(148,163,184,.12);
}

/* Small note */
.v46-note { font-size: .76rem; color: #475569; margin-top: 6px; line-height: 1.4; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: rgba(15,23,42,.5); }
::-webkit-scrollbar-thumb { background: rgba(59,130,246,.3); border-radius: 3px; }

/* Metrics override */
div[data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', monospace !important; font-weight: 600 !important; color: #60a5fa !important; }
div[data-testid="stMetricLabel"] { color: #64748b !important; font-size: .75rem !important; }

/* Caption */
.stCaption, [data-testid="stCaptionContainer"] { color: #475569 !important; font-size: .76rem !important; }

/* Checkbox */
[data-testid="stCheckbox"] label { color: #94a3b8 !important; font-size: .82rem !important; }

/* Radio */
[data-testid="stRadio"] label { color: #94a3b8 !important; font-size: .82rem !important; }
[data-testid="stRadio"] [aria-checked="true"] + div { color: #60a5fa !important; font-weight: 600 !important; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def safe_divide(n: float, d: float) -> float:
    return 0.0 if abs(d) < 1e-12 else n / d


def fmt_money(v: float, cur: str = "USD", compact: bool = False, signed: bool = False) -> str:
    v = float(v)
    sign = ""
    if signed:
        sign = "+" if v > 0 else "-" if v < 0 else ""
    elif v < 0:
        sign = "-"
    a = abs(v)
    if compact:
        if a >= 1e9: return f"{sign}{cur} {a/1e9:,.2f}B"
        if a >= 1e6: return f"{sign}{cur} {a/1e6:,.2f}M"
        if a >= 1e3: return f"{sign}{cur} {a/1e3:,.2f}K"
    return f"{sign}{cur} {a:,.2f}"


def fmt_pct(v: float) -> str:
    return f"{v * 100:.2f}%"


def fmt_qty(v: float, unit: str = "") -> str:
    sfx = f" {unit}" if unit else ""
    return f"{float(v):,.0f}{sfx}"


def landed_unit_price(comps: Dict[str, float], fx: float = 1.0) -> float:
    return sum(float(comps.get(k, 0.0)) for k, _ in LANDED_COST_COMPONENTS) * float(fx)


def default_unit_price_from_spend(spend: float, volume: float) -> float:
    return safe_divide(float(spend), max(float(volume), 1e-9))


def equivalent_rate(rate_pct: float, ref_days: int, target_days: int, method: str = "Compound") -> float:
    if ref_days <= 0 or target_days <= 0:
        return 0.0
    r = rate_pct / 100.0
    if method == "Linear":
        return r * (target_days / ref_days)
    return (1 + r) ** (target_days / ref_days) - 1


def apply_chart_theme(fig, height: int = 440, title_color: str = "#e2e8f0"):
    if fig is None:
        return fig
    fig.update_layout(
        font=dict(family="DM Sans, sans-serif", color="#94a3b8", size=12),
        title_font=dict(family="Syne, sans-serif", color=title_color, size=16),
        plot_bgcolor="rgba(15,23,42,.5)",
        paper_bgcolor="rgba(15,23,42,.5)",
        margin=dict(l=32, r=24, t=56, b=40),
        height=height,
        bargap=0.25,
        modebar=dict(remove=["lasso2d", "select2d"], bgcolor="rgba(0,0,0,0)", color="#64748b"),
        xaxis=dict(
            gridcolor="rgba(148,163,184,.08)", tickfont=dict(color="#64748b"),
            title_font=dict(color="#94a3b8"), color="#94a3b8",
            linecolor="rgba(148,163,184,.1)",
        ),
        yaxis=dict(
            gridcolor="rgba(148,163,184,.08)", tickfont=dict(color="#64748b"),
            title_font=dict(color="#94a3b8"), color="#94a3b8",
            linecolor="rgba(148,163,184,.1)",
        ),
        legend=dict(font=dict(color="#94a3b8"), bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified",
    )
    return fig


def render_section(title: str, subtitle: str, accent: str = "#3b82f6") -> None:
    st.markdown(
        f"""<div class="v46-section" style="--section-accent:{accent}">
            <div class="v46-section-title">{title}</div>
            <div class="v46-section-subtitle">{subtitle}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_breaker(title: str, subtitle: str, icon: str, color: str, tag: str) -> None:
    bg = color + "18"; border = color + "40"
    st.markdown(
        f"""<div class="v46-breaker" style="--br-color:{color}; --br-bg:{bg}; --br-border:{border}">
            <div class="v46-breaker-icon">{icon}</div>
            <div>
                <div class="v46-breaker-title">{title}</div>
                <div class="v46-breaker-sub">{subtitle}</div>
            </div>
            <div class="v46-breaker-tag">{tag}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_kpi(label: str, value: str, helper: str = "", tone: str = "neutral") -> None:
    accent_map = {
        "good": "linear-gradient(90deg,#10b981,#34d399)",
        "bad": "linear-gradient(90deg,#ef4444,#f87171)",
        "neutral": "linear-gradient(90deg,#3b82f6,#60a5fa)",
        "amber": "linear-gradient(90deg,#f59e0b,#fbbf24)",
    }
    acc = accent_map.get(tone, accent_map["neutral"])
    st.markdown(
        f"""<div class="v46-kpi {tone}" style="--kpi-accent:{acc}">
            <div class="v46-kpi-label">{label}</div>
            <div class="v46-kpi-value">{value}</div>
            <div class="v46-kpi-helper">{helper}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def delta_tone(delta: float) -> str:
    if delta < -1e-9: return "good"
    if delta > 1e-9: return "bad"
    return "neutral"


def risk_tone(risk: float) -> str:
    if risk <= 2.5: return "good"
    if risk <= 3.5: return "amber"
    return "bad"


def benefit_tone(v: float) -> str:
    if v > 1e-9: return "good"
    if v < -1e-9: return "bad"
    return "neutral"


def _safe_group_row(gdf: pd.DataFrame, group: str) -> Dict:
    if gdf is None or gdf.empty or "Group" not in gdf.columns:
        return {}
    rows = gdf[gdf["Group"] == group]
    return {} if rows.empty else rows.iloc[0].to_dict()


def service_scope_config(scope: str) -> Dict:
    return SERVICE_SCOPE_CONFIG.get(scope, SERVICE_SCOPE_CONFIG["Generic Indirect Service"])


def service_tier(score: float) -> str:
    if score >= 90: return "Strategic / preferred"
    if score >= 75: return "Approved / good"
    if score >= 60: return "Watchlist"
    return "Corrective action / exit plan"


def service_score_color(score: float) -> str:
    if score >= 75: return "#34d399"
    if score >= 60: return "#fbbf24"
    return "#f87171"


def weighted_service_score(scores: Dict[str, float], weights: Dict[str, float] | None = None) -> float:
    weights = weights or SERVICE_SCORECARD_WEIGHTS
    total_w = sum(float(v) for v in weights.values()) or 1.0
    return sum(float(scores.get(d, 0.0)) * float(w) for d, w in weights.items()) / total_w


def weighted_governance_score(scores: Dict[str, float]) -> float:
    total_w = sum(float(v) for v in SUPPLIER_GOVERNANCE_WEIGHTS.values()) or 1.0
    return sum(float(scores.get(d, 0.0)) * float(w) for d, w in SUPPLIER_GOVERNANCE_WEIGHTS.items()) / total_w


def score_to_risk(score: float) -> float:
    return max(1.0, min(5.0, 1.0 + 4.0 * (100.0 - float(score)) / 100.0))


def governance_tier(score: float) -> str:
    if score >= 90: return "Strategic / preferred"
    if score >= 75: return "Approved / good"
    if score >= 60: return "Watchlist"
    return "Corrective action / exit"


def due_diligence_penalty(status: str) -> float:
    return {"Clear": 0.0, "Minor gaps": 0.25, "Material gaps": 0.75, "Not approved": 1.50}.get(status, 0.0)


def governance_risk_defaults(gov_inputs: Dict, supplier: str) -> Dict[str, float]:
    data = gov_inputs.get(supplier, {}) or {}
    sp = due_diligence_penalty(str(data.get("Due diligence status", "Clear")))
    return {
        "Supply": max(1.0, min(5.0, score_to_risk(float(data.get("OTIF / SLA delivery", 75.0))) + 0.15 * sp)),
        "Quality": max(1.0, min(5.0, score_to_risk(float(data.get("Quality / NCR performance", 75.0))))),
        "Financial": max(1.0, min(5.0, score_to_risk(float(data.get("Financial health", 75.0))) + 0.25 * sp)),
        "Compliance": max(1.0, min(5.0, score_to_risk(float(data.get("Compliance / due diligence", 75.0))) + sp)),
        "ESG": max(1.0, min(5.0, score_to_risk(float(data.get("ESG / ethics", 75.0))) + 0.35 * sp)),
        "Logistics": max(1.0, min(5.0, (score_to_risk(float(data.get("OTIF / SLA delivery", 75.0))) + score_to_risk(float(data.get("Labor / HSE", 75.0)))) / 2.0)),
    }


def blend_risk_default(base: float, gov: float, adj: float = 0.0) -> float:
    return round(max(1.0, min(5.0, 0.45 * float(base) + 0.55 * float(gov) + float(adj))), 1)

# ─────────────────────────────────────────────────────────────────────────────
# INDIRECT / SERVICES — AMAZON-GRADE ANALYTICS ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def calc_fte_demand_decomposition(
    headcount: float,
    regular_hours: float,
    overtime_hours: float,
    absenteeism_rate: float,
    productivity_utilization: float,
) -> Dict[str, float]:
    """Decompose FTE demand: productive vs overhead vs overtime vs absenteeism.
    This is the lens Amazon uses to challenge supplier headcount proposals."""
    effective_hc = headcount * (1.0 - absenteeism_rate / 100.0)
    productive_hc = effective_hc * (productivity_utilization / 100.0)
    ot_fte_equivalent = safe_divide(overtime_hours, max(regular_hours, 1.0))
    demand_coverage = safe_divide(productive_hc + ot_fte_equivalent, max(headcount, 1e-9))
    right_sized_hc = safe_divide(productive_hc + ot_fte_equivalent, max(productivity_utilization / 100.0, 0.01))
    optimization_potential = max(headcount - right_sized_hc, 0.0)
    return {
        "total_headcount": headcount,
        "effective_headcount": effective_hc,
        "productive_headcount": productive_hc,
        "ot_fte_equivalent": ot_fte_equivalent,
        "demand_coverage_pct": demand_coverage * 100.0,
        "right_sized_headcount": right_sized_hc,
        "optimization_potential_hc": optimization_potential,
        "absenteeism_impact_hc": headcount - effective_hc,
    }


def calc_contract_leakage_waterfall(
    contracted_value: float,
    scope_additions: float,
    emergency_requests: float,
    rework_cost: float,
    untracked_passthrough: float,
    sla_credits: float,
    rebates: float,
) -> Dict[str, float]:
    """Build contract leakage waterfall from contracted value to actual billed TCO."""
    total_leakage = scope_additions + emergency_requests + rework_cost + untracked_passthrough
    total_offsets = sla_credits + rebates
    actual_billed = contracted_value + total_leakage - total_offsets
    leakage_rate = safe_divide(total_leakage, contracted_value)
    return {
        "contracted_value": contracted_value,
        "scope_additions": scope_additions,
        "emergency_requests": emergency_requests,
        "rework_cost": rework_cost,
        "untracked_passthrough": untracked_passthrough,
        "total_leakage": total_leakage,
        "sla_credits": sla_credits,
        "rebates": rebates,
        "total_offsets": total_offsets,
        "actual_billed": actual_billed,
        "leakage_rate": leakage_rate,
    }


def calc_sla_financial_impact(
    contracted_value: float,
    sla_penalty_pct: float,
    sla_attainment: float,
    sla_target: float,
    missed_sla_cost_multiplier: float = 2.5,
) -> Dict[str, float]:
    """Quantify financial exposure from SLA gaps. Amazon procurement always models
    downside risk of SLA breach before awarding a contract."""
    sla_gap = max(sla_target - sla_attainment, 0.0)
    penalty_exposure = contracted_value * (sla_penalty_pct / 100.0) * (sla_gap / max(sla_target, 1.0))
    business_impact = contracted_value * (sla_gap / 100.0) * (missed_sla_cost_multiplier - 1.0)
    expected_annual_impact = penalty_exposure + business_impact
    return {
        "sla_attainment": sla_attainment,
        "sla_target": sla_target,
        "sla_gap": sla_gap,
        "penalty_exposure": penalty_exposure,
        "business_impact": business_impact,
        "expected_annual_impact": expected_annual_impact,
        "sla_ok": sla_attainment >= sla_target,
    }


def calc_productivity_roi(
    investment: float,
    annual_savings: float,
    year_1_fraction: float = 0.5,
) -> Dict[str, float]:
    """Calculate productivity ROI and payback period."""
    if investment <= 0:
        return {
            "investment": 0.0, "annual_savings": annual_savings,
            "year_1_savings": annual_savings * year_1_fraction,
            "payback_months": 0.0, "three_year_roi_pct": 999.0,
            "net_three_year_value": annual_savings * 3.0,
        }
    y1 = annual_savings * year_1_fraction
    y2y3 = annual_savings * 2.0
    net_3yr = y1 + y2y3 - investment
    payback_months = safe_divide(investment, max(annual_savings / 12.0, 1.0))
    roi_3yr = safe_divide(net_3yr, investment) * 100.0
    return {
        "investment": investment,
        "annual_savings": annual_savings,
        "year_1_savings": y1,
        "payback_months": payback_months,
        "three_year_roi_pct": roi_3yr,
        "net_three_year_value": net_3yr,
    }


def calc_rate_card_compliance(
    quoted_rate: float,
    benchmark_rate: float,
    hours_consumed: float,
) -> Dict[str, float]:
    """Rate card compliance check. Compares supplier quoted rate vs market benchmark."""
    gap = quoted_rate - benchmark_rate
    gap_pct = safe_divide(gap, benchmark_rate) * 100.0
    annual_overcharge = gap * hours_consumed if gap > 0 else 0.0
    return {
        "quoted_rate": quoted_rate,
        "benchmark_rate": benchmark_rate,
        "rate_gap": gap,
        "rate_gap_pct": gap_pct,
        "annual_overcharge": annual_overcharge,
        "compliant": abs(gap_pct) <= 10.0,
    }


def calc_multi_year_contract_value(
    base_annual_value: float,
    contract_years: int,
    annual_escalation_pct: float,
    early_termination_cost: float = 0.0,
) -> Dict[str, float]:
    """Model multi-year total contract value with escalation."""
    total_cv = 0.0
    year_values = []
    for yr in range(1, contract_years + 1):
        val = base_annual_value * ((1 + annual_escalation_pct / 100.0) ** (yr - 1))
        total_cv += val
        year_values.append({"year": yr, "value": val})
    avg_annual = safe_divide(total_cv, contract_years)
    return {
        "base_annual_value": base_annual_value,
        "contract_years": contract_years,
        "total_contract_value": total_cv,
        "avg_annual_value": avg_annual,
        "year_values": year_values,
        "early_termination_cost": early_termination_cost,
        "escalation_impact": total_cv - base_annual_value * contract_years,
    }


def render_service_scope_fields(*, key_prefix: str, scope: str) -> Dict[str, float]:
    cfg = service_scope_config(scope)
    labels = list(cfg.get("field_labels", ["Service units", "Hours / month", "Sites / users covered"]))
    c = st.columns(3)
    values = {}
    for idx, label in enumerate(labels[:3]):
        with c[idx]:
            values[f"driver_{idx+1}"] = st.number_input(
                label, min_value=0.0, value=0.0, step=1.0, format="%.2f",
                key=f"{key_prefix}__scope_driver_{idx+1}",
            )
    st.caption(f"Recommended demand driver: {cfg.get('driver_label', 'service units')}.")
    return values


def render_service_scorecard(*, key_prefix: str, supplier_label: str, default_score: float = 82.0) -> Dict:
    st.markdown("<div class='v46-plain-title'>📊 Supplier Performance Scorecard</div>", unsafe_allow_html=True)
    c = st.columns(4) + st.columns(3)  # type: ignore
    cols_flat = [st.columns(4)[i % 4] for i in range(9)]
    # re-render properly
    st.markdown("<div class='v46-gov-card'>", unsafe_allow_html=True)
    score_cols = st.columns(5)
    scores: Dict[str, float] = {}
    dims = list(SERVICE_SCORECARD_WEIGHTS.keys())
    for idx, dim in enumerate(dims):
        with score_cols[idx % 5]:
            scores[dim] = st.slider(
                f"{dim}", min_value=0.0, max_value=100.0, value=float(default_score),
                step=1.0, key=f"{key_prefix}__score__{dim}",
                help=f"Weight: {SERVICE_SCORECARD_WEIGHTS[dim]:.0f}%",
            )
    score = weighted_service_score(scores)
    tier = service_tier(score)
    color = service_score_color(score)
    st.markdown(
        f"""<div class="v46-svc-result">
            <b>Weighted score:</b> <span class="v46-score-badge" style="color:{color};border-color:{color}">{score:,.1f} / 100</span>
            &nbsp;·&nbsp; <b>Tier:</b> {escape(tier)}
        </div></div>""",
        unsafe_allow_html=True,
    )
    return {"score": float(score), "tier": tier, **scores}


def render_service_baseline_builder(*, key_prefix: str, country: str, scope: str, reporting_currency: str) -> Dict:
    cfg = service_scope_config(scope)
    pricing_models = list(cfg.get("pricing_models", ["Fixed fee"]))
    icon = cfg.get("icon", "🧾")
    color = cfg.get("color", "#64748b")

    st.markdown(f"<div class='v46-plain-title'>{icon} {scope} — Current Baseline ({country})</div>", unsafe_allow_html=True)

    r1 = st.columns([1.2, 0.9, 0.9, 0.9])
    with r1[0]:
        pricing_model = st.selectbox("Pricing model", options=pricing_models, index=0, key=f"{key_prefix}__pricing_model")
    with r1[1]:
        contracted_value = st.number_input(
            "Contracted / baseline value", min_value=0.0, value=float(DEFAULT_SERVICE_CONTRACT_VALUE[country]),
            step=100_000.0, format="%.2f", key=f"{key_prefix}__contracted_value",
        )
    with r1[2]:
        budget_value = st.number_input(
            "Current budget", min_value=0.0, value=float(DEFAULT_SERVICE_CONTRACT_VALUE[country]),
            step=100_000.0, format="%.2f", key=f"{key_prefix}__budget_value",
        )
    with r1[3]:
        contract_years = st.number_input("Contract years", min_value=1, max_value=10, value=3, step=1, key=f"{key_prefix}__contract_years")

    render_service_scope_fields(key_prefix=key_prefix, scope=scope)

    # ── FTE decomposition (Amazon lens) ──────────────────────────────────────
    st.markdown("<div class='v46-plain-title'>👥 FTE Demand Decomposition & Rate Card</div>", unsafe_allow_html=True)
    st.caption("Amazon procurement standard: decompose supplier headcount into productive, overtime and absenteeism-adjusted units before challenging the proposal.")
    wh = st.columns(7)
    with wh[0]:
        headcount = st.number_input("Total headcount / FTEs", min_value=0.0, value=0.0, step=1.0, format="%.2f", key=f"{key_prefix}__headcount")
    with wh[1]:
        price_per_person_month = st.number_input("Price / person / month", min_value=0.0, value=0.0, step=1_000.0, format="%.2f", key=f"{key_prefix}__price_per_person_month")
    with wh[2]:
        regular_hours = st.number_input("Regular hours / FTE / month", min_value=0.0, value=168.0, step=1.0, format="%.2f", key=f"{key_prefix}__regular_hours")
    with wh[3]:
        hourly_rate = st.number_input("Hourly rate (0 = estimated)", min_value=0.0, value=0.0, step=10.0, format="%.2f", key=f"{key_prefix}__hourly_rate")
    with wh[4]:
        overtime_hours = st.number_input("Overtime hours / month", min_value=0.0, value=0.0, step=1.0, format="%.2f", key=f"{key_prefix}__overtime_hours")
    with wh[5]:
        absenteeism_rate = st.number_input("Absenteeism rate %", min_value=0.0, max_value=50.0, value=5.0, step=0.5, format="%.2f", key=f"{key_prefix}__absenteeism_rate")
    with wh[6]:
        productivity_util = st.number_input("Productivity utilization %", min_value=1.0, max_value=100.0, value=80.0, step=1.0, format="%.2f", key=f"{key_prefix}__productivity_util")

    eff_hr = float(hourly_rate) if float(hourly_rate) > 0 else safe_divide(float(price_per_person_month), max(float(regular_hours), 1.0))
    fte_decomp = calc_fte_demand_decomposition(
        float(headcount), float(regular_hours), float(overtime_hours),
        float(absenteeism_rate), float(productivity_util),
    )
    benchmark_fte_cost = float(cfg.get("benchmark_fte_cost", 60_000.0))
    rc_check = calc_rate_card_compliance(
        float(price_per_person_month) * 12.0,
        benchmark_fte_cost,
        float(regular_hours) * 12.0,
    )

    if float(headcount) > 0:
        opt_pct = safe_divide(fte_decomp["optimization_potential_hc"], float(headcount)) * 100
        rc_color = "#34d399" if rc_check["compliant"] else "#f87171"
        st.markdown(
            f"""<div class="v46-svc-result">
            <b>Effective FTEs:</b> {fte_decomp['effective_headcount']:.1f} &nbsp;·&nbsp;
            <b>Productive FTEs:</b> {fte_decomp['productive_headcount']:.1f} &nbsp;·&nbsp;
            <b>OT equiv FTEs:</b> {fte_decomp['ot_fte_equivalent']:.1f} &nbsp;·&nbsp;
            <b>Demand coverage:</b> {fte_decomp['demand_coverage_pct']:.1f}% &nbsp;·&nbsp;
            <b>Right-sized HC:</b> {fte_decomp['right_sized_headcount']:.1f} &nbsp;·&nbsp;
            <b>Optimization potential:</b> <span style="color:#fbbf24">{fte_decomp['optimization_potential_hc']:.1f} FTEs ({opt_pct:.1f}%)</span> &nbsp;·&nbsp;
            <b>Rate card:</b> <span style="color:{rc_color}">{'✓ Compliant' if rc_check['compliant'] else f'⚠ +{rc_check["rate_gap_pct"]:.1f}% vs benchmark'}</span>
            </div>""",
            unsafe_allow_html=True,
        )

    # ── Contract leakage ─────────────────────────────────────────────────────
    st.markdown("<div class='v46-plain-title'>💧 Contract Leakage & Lifecycle Cost</div>", unsafe_allow_html=True)
    st.caption("Model every leakage vector. Amazon procurement expects scope creep, emergency requests and rework to be budgeted, not discovered post-award.")
    r2 = st.columns(6)
    with r2[0]:
        scope_additions = st.number_input("Scope additions / change orders", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__scope_additions")
    with r2[1]:
        emergency_requests = st.number_input("Emergency requests cost", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__emergency_requests")
    with r2[2]:
        rework_cost = st.number_input("Rework / quality cost", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__rework_cost")
    with r2[3]:
        internal_management = st.number_input("Internal management cost", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__internal_management")
    with r2[4]:
        sla_credits = st.number_input("SLA credits / rebates", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__sla_credits")
    with r2[5]:
        ot_cost_input = st.number_input("Annual overtime cost", min_value=0.0, value=float(float(overtime_hours) * eff_hr * 1.5 * 12.0), step=10_000.0, format="%.2f", key=f"{key_prefix}__ot_cost")

    leakage = calc_contract_leakage_waterfall(
        float(contracted_value), float(scope_additions), float(emergency_requests),
        float(rework_cost), 0.0, float(sla_credits), 0.0,
    )
    service_tco = leakage["actual_billed"] + float(internal_management) + float(ot_cost_input)
    budget_variance = service_tco - float(budget_value)
    tcv = calc_multi_year_contract_value(service_tco, int(contract_years), 3.0)

    if float(contracted_value) > 0:
        st.markdown(
            f"""<div class="v46-leakage">
            <div class="v46-leakage-title">📊 Contract Leakage Waterfall</div>
            <div class="v46-leakage-row"><span class="v46-leakage-item">Contracted baseline</span><span class="v46-leakage-val">{reporting_currency} {contracted_value:,.0f}</span></div>
            <div class="v46-leakage-row"><span class="v46-leakage-item">+ Scope additions</span><span class="v46-leakage-val">+ {reporting_currency} {scope_additions:,.0f}</span></div>
            <div class="v46-leakage-row"><span class="v46-leakage-item">+ Emergency requests</span><span class="v46-leakage-val">+ {reporting_currency} {emergency_requests:,.0f}</span></div>
            <div class="v46-leakage-row"><span class="v46-leakage-item">+ Rework cost</span><span class="v46-leakage-val">+ {reporting_currency} {rework_cost:,.0f}</span></div>
            <div class="v46-leakage-row"><span class="v46-leakage-item">+ OT cost</span><span class="v46-leakage-val">+ {reporting_currency} {ot_cost_input:,.0f}</span></div>
            <div class="v46-leakage-row"><span class="v46-leakage-item">- SLA credits / rebates</span><span class="v46-leakage-val">- {reporting_currency} {sla_credits:,.0f}</span></div>
            <div class="v46-leakage-row"><span class="v46-leakage-item"><b>Current Service TCO</b></span><span class="v46-leakage-val"><b>{reporting_currency} {service_tco:,.0f}</b></span></div>
            </div>
            <div class="v46-svc-result">
            <b>Leakage rate:</b> {leakage['leakage_rate']*100:.1f}% &nbsp;·&nbsp;
            <b>Budget variance:</b> {reporting_currency} {budget_variance:,.0f} &nbsp;·&nbsp;
            <b>{int(contract_years)}-yr TCV:</b> {reporting_currency} {tcv['total_contract_value']:,.0f} &nbsp;·&nbsp;
            <b>Escalation impact:</b> {reporting_currency} {tcv['escalation_impact']:,.0f}
            </div>""",
            unsafe_allow_html=True,
        )

    overtime_cost_val = float(ot_cost_input)
    people_cost_model = float(headcount) * float(price_per_person_month) * 12.0
    scope_creep_pct = safe_divide(float(scope_additions), float(contracted_value))

    return {
        "scope": scope, "pricing_model": pricing_model,
        "contracted_value": float(contracted_value), "budget_value": float(budget_value),
        "actual_demand_index": 100.0,
        "change_orders": float(scope_additions), "internal_management": float(internal_management),
        "rework_cost": float(rework_cost), "downtime_compliance_cost": 0.0,
        "sla_credits_rebates": float(sla_credits),
        "headcount": float(headcount), "price_per_person_month": float(price_per_person_month),
        "regular_hours_per_person_month": float(regular_hours), "hourly_rate": float(eff_hr),
        "overtime_hours_month": float(overtime_hours), "overtime_cost": float(ot_cost_input),
        "people_cost_model": float(people_cost_model), "productivity_gain": 0.0, "expected_risk_cost": 0.0,
        "service_tco": float(service_tco), "scope_creep_pct": float(scope_creep_pct),
        "budget_variance": float(budget_variance), "contract_years": int(contract_years),
        "total_contract_value": float(tcv["total_contract_value"]),
        "leakage_rate": float(leakage["leakage_rate"]),
        "fte_decomp": fte_decomp,
        "rate_card_compliance": rc_check,
    }


def render_service_supplier_builder(
    *, key_prefix: str, country: str, scope: str, supplier_label: str,
    default_spend: float, reporting_currency: str,
) -> Dict:
    cfg = service_scope_config(scope)
    pricing_models = list(cfg.get("pricing_models", ["Fixed fee"]))
    icon = cfg.get("icon", "🧾")
    color = cfg.get("color", "#64748b")
    benchmark_fte = float(cfg.get("benchmark_fte_cost", 60_000.0))
    sla_kpis = cfg.get("sla_kpis", ["SLA %"])[:3]

    st.markdown(f"<div class='v46-plain-title'>{icon} Service pricing, workforce & productivity</div>", unsafe_allow_html=True)
    r1 = st.columns([1.1, .85, .85, .85])
    with r1[0]:
        pricing_model = st.selectbox(f"{supplier_label} | Pricing model", options=pricing_models, index=0, key=f"{key_prefix}__pricing_model")
    with r1[1]:
        proposed_value = st.number_input(f"{supplier_label} | Proposed contract value", min_value=0.0, value=float(default_spend), step=50_000.0, format="%.2f", key=f"{key_prefix}__proposed_contract_value")
    with r1[2]:
        demand_index = st.number_input(f"{supplier_label} | Demand / scope index", min_value=0.0, value=100.0, step=5.0, format="%.2f", key=f"{key_prefix}__baseline_demand_index")
    with r1[3]:
        contract_years = st.number_input(f"{supplier_label} | Contract years", min_value=1, max_value=10, value=3, step=1, key=f"{key_prefix}__contract_years")

    render_service_scope_fields(key_prefix=key_prefix, scope=scope)

    # ── FTE workforce ─────────────────────────────────────────────────────────
    st.markdown("<div class='v46-plain-title'>👥 Workforce, rate card & overtime</div>", unsafe_allow_html=True)
    wh = st.columns(7)
    with wh[0]:
        headcount = st.number_input(f"{supplier_label} | Headcount / FTEs", min_value=0.0, value=0.0, step=1.0, format="%.2f", key=f"{key_prefix}__headcount")
    with wh[1]:
        price_per_person_month = st.number_input(f"{supplier_label} | Price / FTE / month", min_value=0.0, value=0.0, step=1_000.0, format="%.2f", key=f"{key_prefix}__price_per_person_month")
    with wh[2]:
        regular_hours = st.number_input(f"{supplier_label} | Regular hours / FTE / month", min_value=0.0, value=168.0, step=1.0, format="%.2f", key=f"{key_prefix}__regular_hours")
    with wh[3]:
        hourly_rate_input = st.number_input(f"{supplier_label} | Hourly rate (0=est.)", min_value=0.0, value=0.0, step=10.0, format="%.2f", key=f"{key_prefix}__hourly_rate")
    with wh[4]:
        overtime_hours = st.number_input(f"{supplier_label} | OT hours / month", min_value=0.0, value=0.0, step=1.0, format="%.2f", key=f"{key_prefix}__overtime_hours")
    with wh[5]:
        ot_multiplier = st.number_input(f"{supplier_label} | OT multiplier", min_value=1.0, value=1.5, step=0.05, format="%.2f", key=f"{key_prefix}__ot_mult")
    with wh[6]:
        absenteeism_rate = st.number_input(f"{supplier_label} | Absenteeism %", min_value=0.0, max_value=50.0, value=5.0, step=0.5, format="%.2f", key=f"{key_prefix}__absenteeism_rate")

    eff_hr = float(hourly_rate_input) if float(hourly_rate_input) > 0 else safe_divide(float(price_per_person_month), max(float(regular_hours), 1.0))
    ot_cost = float(overtime_hours) * eff_hr * float(ot_multiplier) * 12.0
    people_cost = float(headcount) * float(price_per_person_month) * 12.0
    fte_decomp = calc_fte_demand_decomposition(float(headcount), float(regular_hours), float(overtime_hours), float(absenteeism_rate), 80.0)
    rc_check = calc_rate_card_compliance(float(price_per_person_month) * 12.0, benchmark_fte, float(regular_hours) * 12.0)

    if float(headcount) > 0:
        rc_color = "#34d399" if rc_check["compliant"] else "#f87171"
        st.markdown(
            f"""<div class="v46-svc-result">
            <b>Right-sized HC:</b> {fte_decomp['right_sized_headcount']:.1f} &nbsp;·&nbsp;
            <b>Optimization potential:</b> {fte_decomp['optimization_potential_hc']:.1f} FTEs &nbsp;·&nbsp;
            <b>Rate card:</b> <span style="color:{rc_color}">{'✓ OK' if rc_check['compliant'] else f'⚠ +{rc_check["rate_gap_pct"]:.1f}% vs benchmark (annual overcharge: {reporting_currency} {rc_check["annual_overcharge"]:,.0f})'}</span>
            </div>""",
            unsafe_allow_html=True,
        )

    # ── SLA modeling (Amazon demand) ────────────────────────────────────────
    st.markdown("<div class='v46-plain-title'>🎯 SLA modeling & financial exposure</div>", unsafe_allow_html=True)
    st.caption(f"Key SLA KPIs for {scope}: {', '.join(sla_kpis)}. Quantify the financial exposure before awarding.")
    sla_cols = st.columns([1.0, .8, .8, .8, .8])
    with sla_cols[0]:
        primary_sla_label = sla_kpis[0] if sla_kpis else "Primary SLA"
        sla_attainment = st.number_input(f"{supplier_label} | {primary_sla_label} attainment", min_value=0.0, max_value=100.0, value=95.0, step=0.1, format="%.2f", key=f"{key_prefix}__sla_attainment")
    with sla_cols[1]:
        sla_target = st.number_input(f"{supplier_label} | SLA target %", min_value=0.0, max_value=100.0, value=98.0, step=0.1, format="%.2f", key=f"{key_prefix}__sla_target")
    with sla_cols[2]:
        sla_penalty_pct = st.number_input(f"{supplier_label} | Penalty % of contract", min_value=0.0, max_value=50.0, value=2.0, step=0.5, format="%.2f", key=f"{key_prefix}__sla_penalty_pct")
    with sla_cols[3]:
        sla_impact_mult = st.number_input(f"{supplier_label} | Business impact mult.", min_value=1.0, max_value=10.0, value=2.5, step=0.1, format="%.2f", key=f"{key_prefix}__sla_impact_mult")
    with sla_cols[4]:
        transition_days = st.number_input(f"{supplier_label} | Transition days", min_value=0, value=30, step=1, key=f"{key_prefix}__transition_days")

    sla_result = calc_sla_financial_impact(float(proposed_value), float(sla_penalty_pct), float(sla_attainment), float(sla_target), float(sla_impact_mult))
    if sla_result["sla_gap"] > 0:
        st.markdown(
            f"""<div class="v46-leakage">
            <div class="v46-leakage-title">⚠ SLA Risk Quantification</div>
            <div class="v46-leakage-row"><span class="v46-leakage-item">SLA gap ({primary_sla_label})</span><span class="v46-leakage-val">{sla_result['sla_gap']:.1f} pp below target</span></div>
            <div class="v46-leakage-row"><span class="v46-leakage-item">Penalty exposure</span><span class="v46-leakage-val">{reporting_currency} {sla_result['penalty_exposure']:,.0f}</span></div>
            <div class="v46-leakage-row"><span class="v46-leakage-item">Business impact</span><span class="v46-leakage-val">{reporting_currency} {sla_result['business_impact']:,.0f}</span></div>
            <div class="v46-leakage-row"><span class="v46-leakage-item"><b>Expected annual SLA cost</b></span><span class="v46-leakage-val"><b>{reporting_currency} {sla_result['expected_annual_impact']:,.0f}</b></span></div>
            </div>""",
            unsafe_allow_html=True,
        )

    # ── Should-cost engine ────────────────────────────────────────────────────
    st.markdown("<div class='v46-plain-title'>🔬 Should-cost engine & open-cost model</div>", unsafe_allow_html=True)
    sc = st.columns(6)
    with sc[0]:
        should_cost_hc = st.number_input(f"{supplier_label} | Should-cost HC", min_value=0.0, value=float(headcount), step=1.0, format="%.2f", key=f"{key_prefix}__should_cost_headcount")
    with sc[1]:
        benchmark_hr = st.number_input(f"{supplier_label} | Benchmark hourly rate", min_value=0.0, value=max(eff_hr, 0.0), step=10.0, format="%.2f", key=f"{key_prefix}__benchmark_hourly_rate")
    with sc[2]:
        target_hours = st.number_input(f"{supplier_label} | Target hours / FTE / month", min_value=0.0, value=float(regular_hours), step=1.0, format="%.2f", key=f"{key_prefix}__target_hours_month")
    with sc[3]:
        overhead_pct = st.number_input(f"{supplier_label} | Overhead / tools %", min_value=0.0, max_value=200.0, value=15.0, step=1.0, format="%.2f", key=f"{key_prefix}__overhead_tools_pct")
    with sc[4]:
        fair_margin = st.number_input(f"{supplier_label} | Fair margin %", min_value=0.0, max_value=100.0, value=12.0, step=1.0, format="%.2f", key=f"{key_prefix}__fair_margin_pct")
    with sc[5]:
        should_cost_prod = st.number_input(f"{supplier_label} | Productivity target %", min_value=0.0, max_value=100.0, value=0.0, step=1.0, format="%.2f", key=f"{key_prefix}__should_cost_productivity_pct")

    st.markdown("<div class='v46-plain-title'>Open-cost breakdown</div>", unsafe_allow_html=True)
    st.caption("Request a transparent open-cost breakdown from the supplier. Unexplained quote value is a negotiation lever.")
    open_cost_values: Dict[str, float] = {}
    oc_rows = [SERVICE_OPEN_COST_COMPONENTS[i:i+4] for i in range(0, len(SERVICE_OPEN_COST_COMPONENTS), 4)]
    for row_idx, component_row in enumerate(oc_rows):
        oc_cols = st.columns(4)
        for col_idx, (comp_key, comp_label) in enumerate(component_row):
            with oc_cols[col_idx]:
                open_cost_values[comp_key] = st.number_input(
                    f"{supplier_label} | {comp_label}", min_value=0.0, value=0.0, step=10_000.0, format="%.2f",
                    key=f"{key_prefix}__open_cost__{comp_key}",
                )
    should_cost_labor = float(should_cost_hc) * float(target_hours) * 12.0 * float(benchmark_hr)
    open_cost_total = sum(float(v) for v in open_cost_values.values())
    should_cost_raw = should_cost_labor + open_cost_total
    should_cost_target = should_cost_raw * (1.0 + overhead_pct / 100.0) * (1.0 + fair_margin / 100.0) * (1.0 - should_cost_prod / 100.0)
    should_cost_gap = float(proposed_value) - float(should_cost_target)
    open_cost_coverage = safe_divide(open_cost_total, float(proposed_value))
    unexplained = max(float(proposed_value) - open_cost_total, 0.0)
    st.markdown(
        f"""<div class="v46-opencost-card">
        <b>Open-cost coverage:</b> {open_cost_coverage*100:.1f}% &nbsp;·&nbsp;
        <b>Open-cost total:</b> {reporting_currency} {open_cost_total:,.0f} &nbsp;·&nbsp;
        <b>Unexplained quote value:</b> {reporting_currency} {unexplained:,.0f} &nbsp;·&nbsp;
        <b>Clean-sheet should-cost:</b> {reporting_currency} {should_cost_target:,.0f}
        </div>""",
        unsafe_allow_html=True,
    )

    # ── TCO adjustments & productivity ───────────────────────────────────────
    st.markdown("<div class='v46-plain-title'>⚙ Service TCO adjustments & productivity ROI</div>", unsafe_allow_html=True)
    r2 = st.columns(6)
    with r2[0]:
        transition_cost = st.number_input(f"{supplier_label} | Transition cost", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__transition_cost")
    with r2[1]:
        change_order_reserve = st.number_input(f"{supplier_label} | Change order reserve", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__change_order_reserve")
    with r2[2]:
        internal_mgmt = st.number_input(f"{supplier_label} | Internal management cost", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__internal_management")
    with r2[3]:
        rework_cost_sup = st.number_input(f"{supplier_label} | Rework / quality cost", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__rework_cost")
    with r2[4]:
        sla_credits_rebates = st.number_input(f"{supplier_label} | SLA credits / rebates", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__sla_credits_rebates")
    with r2[5]:
        ot_cost_input = st.number_input(f"{supplier_label} | Annual OT cost", min_value=0.0, value=float(ot_cost), step=10_000.0, format="%.2f", key=f"{key_prefix}__ot_cost")

    st.markdown("<div class='v46-plain-title'>📈 Supplier-led productivity & risk</div>", unsafe_allow_html=True)
    st.caption(f"Productivity lever for {scope}: {cfg.get('productivity_label', 'supplier-led productivity')}.")
    r3 = st.columns([1.1, .75, .75, .75, .75])
    with r3[0]:
        prod_description = st.text_input(f"{supplier_label} | Productivity lever", value=str(cfg.get("productivity_label", "supplier-led productivity")), key=f"{key_prefix}__productivity_description")
    with r3[1]:
        productivity_gain = st.number_input(f"{supplier_label} | Annual productivity gain value", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__productivity_gain")
    with r3[2]:
        prod_investment = st.number_input(f"{supplier_label} | Productivity investment", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__prod_investment")
    with r3[3]:
        risk_prob = st.number_input(f"{supplier_label} | Risk probability %", min_value=0.0, max_value=100.0, value=0.0, step=1.0, format="%.2f", key=f"{key_prefix}__risk_probability")
    with r3[4]:
        risk_impact = st.number_input(f"{supplier_label} | Risk financial impact", min_value=0.0, value=0.0, step=10_000.0, format="%.2f", key=f"{key_prefix}__risk_impact")

    # Productivity ROI
    roi = calc_productivity_roi(float(prod_investment), float(productivity_gain))
    if float(productivity_gain) > 0:
        payback_str = f"{roi['payback_months']:.1f} months" if roi['payback_months'] < 60 else "N/A"
        st.markdown(
            f"""<div class="v46-roi-badge">
            📈 Productivity ROI: <b>{roi['three_year_roi_pct']:.0f}%</b> (3-yr) &nbsp;·&nbsp;
            Payback: <b>{payback_str}</b> &nbsp;·&nbsp;
            Net 3-yr value: <b>{reporting_currency} {roi['net_three_year_value']:,.0f}</b>
            </div>""",
            unsafe_allow_html=True,
        )

    scorecard = render_service_scorecard(key_prefix=key_prefix, supplier_label=supplier_label)
    expected_risk_cost = float(risk_prob) / 100.0 * float(risk_impact)
    sla_risk_cost = sla_result["expected_annual_impact"]
    service_tco_before_prod = (float(proposed_value) + float(transition_cost) + float(change_order_reserve)
                               + float(internal_mgmt) + float(rework_cost_sup) + float(ot_cost_input)
                               + expected_risk_cost + sla_risk_cost - float(sla_credits_rebates))
    service_tco = max(service_tco_before_prod - float(productivity_gain), 0.0)
    perf_score = float(scorecard["score"])
    perf_adj_cost = safe_divide(service_tco, max(perf_score / 100.0, 1e-9))
    scope_creep_pct = safe_divide(float(change_order_reserve), float(proposed_value))
    tcv = calc_multi_year_contract_value(service_tco, int(contract_years), 3.0)

    st.markdown(
        f"""<div class="v46-svc-result">
        <b>Service TCO (proposal spend):</b> {reporting_currency} {service_tco:,.0f} &nbsp;·&nbsp;
        <b>Productivity gain:</b> {reporting_currency} {productivity_gain:,.0f} &nbsp;·&nbsp;
        <b>SLA risk cost:</b> {reporting_currency} {sla_risk_cost:,.0f} &nbsp;·&nbsp;
        <b>Expected risk cost:</b> {reporting_currency} {expected_risk_cost:,.0f} &nbsp;·&nbsp;
        <b>Perf-adj cost:</b> {reporting_currency} {perf_adj_cost:,.0f} &nbsp;·&nbsp;
        <b>Should-cost gap:</b> {reporting_currency} {should_cost_gap:,.0f} &nbsp;·&nbsp;
        <b>{int(contract_years)}-yr TCV:</b> {reporting_currency} {tcv['total_contract_value']:,.0f}
        </div>""",
        unsafe_allow_html=True,
    )

    return {
        "scope": scope, "pricing_model": pricing_model,
        "proposed_contract_value": float(proposed_value), "baseline_demand_index": float(demand_index),
        "transition_days": int(transition_days), "transition_cost": float(transition_cost),
        "change_order_reserve": float(change_order_reserve), "internal_management": float(internal_mgmt),
        "rework_cost": float(rework_cost_sup), "sla_credits_rebates": float(sla_credits_rebates),
        "headcount": float(headcount), "price_per_person_month": float(price_per_person_month),
        "regular_hours_per_person_month": float(regular_hours), "hourly_rate": float(eff_hr),
        "people_cost_model": float(people_cost), "overtime_hours_month": float(overtime_hours),
        "overtime_cost": float(ot_cost_input), "absenteeism_rate": float(absenteeism_rate),
        "should_cost_headcount": float(should_cost_hc), "benchmark_hourly_rate": float(benchmark_hr),
        "should_cost_target": float(should_cost_target), "should_cost_gap": float(should_cost_gap),
        "open_cost_total": float(open_cost_total), "open_cost_coverage_pct": float(open_cost_coverage),
        "unexplained_quote_value": float(unexplained),
        **{f"open_cost_{k}": float(v) for k, v in open_cost_values.items()},
        "productivity_description": prod_description, "productivity_gain": float(productivity_gain),
        "prod_investment": float(prod_investment),
        "productivity_roi_pct": float(roi["three_year_roi_pct"]),
        "payback_months": float(roi["payback_months"]),
        "risk_probability": float(risk_prob), "risk_impact": float(risk_impact),
        "expected_risk_cost": float(expected_risk_cost),
        "sla_risk_cost": float(sla_risk_cost), "sla_attainment": float(sla_attainment),
        "sla_target": float(sla_target), "sla_gap": float(sla_result["sla_gap"]),
        "service_tco_before_productivity": float(service_tco_before_prod),
        "service_tco": float(service_tco), "performance_score": float(perf_score),
        "performance_tier": str(scorecard["tier"]), "performance_adjusted_cost": float(perf_adj_cost),
        "scope_creep_pct": float(scope_creep_pct), "total_contract_value": float(tcv["total_contract_value"]),
        "fte_decomp": fte_decomp, "rate_card_compliance": rc_check,
        **{f"score_{d}": float(scorecard[d]) for d in SERVICE_SCORECARD_WEIGHTS},
    }


# ─────────────────────────────────────────────────────────────────────────────
# DIRECT MATERIALS — LANDED COST BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def render_landed_cost_builder(
    *, key_prefix: str, default_spend: float, default_volume: float, unit: str,
    reporting_currency: str, currency_default: str = "BRL", supplier_label: str = "Supplier",
) -> Dict:
    if currency_default not in CURRENCY_OPTIONS:
        currency_default = "BRL"
    default_fx = float(DEFAULT_FX_TO_REPORTING.get(currency_default, 1.0))
    base_default = default_unit_price_from_spend(default_spend, max(default_volume * default_fx, 1e-9))

    r1 = st.columns([1.0, .82, .78, .78, .72])
    with r1[0]:
        base_unit_price = st.number_input(f"{supplier_label} | Base / quoted unit price", min_value=0.0, value=float(base_default), step=0.01, format="%.6f", key=f"{key_prefix}__base_unit_price")
    with r1[1]:
        currency = st.selectbox(f"{supplier_label} | Quote currency", options=CURRENCY_OPTIONS, index=CURRENCY_OPTIONS.index(currency_default), key=f"{key_prefix}__currency")
    with r1[2]:
        fx_rate = st.number_input(f"{supplier_label} | FX to {reporting_currency}", min_value=0.000001, value=default_fx, step=0.01, format="%.6f", key=f"{key_prefix}__fx_rate")
    with r1[3]:
        volume = st.number_input(f"{supplier_label} | 100% volume ({unit})", min_value=0.0, value=float(default_volume), step=max(float(default_volume) * 0.05, 1.0), format="%.4f", key=f"{key_prefix}__volume")
    with r1[4]:
        moq = st.number_input(f"{supplier_label} | MOQ ({unit})", min_value=0.0, value=0.0, step=max(float(default_volume) * 0.05, 1.0), format="%.4f", key=f"{key_prefix}__moq")

    r2 = st.columns(5)
    with r2[0]:
        conversion_cost = st.number_input(f"{supplier_label} | Conversion / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__conversion_cost")
    with r2[1]:
        fixed_margin = st.number_input(f"{supplier_label} | Fixed margin / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__fixed_margin")
    with r2[2]:
        intl_freight = st.number_input(f"{supplier_label} | Intl freight / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__international_freight")
    with r2[3]:
        insurance = st.number_input(f"{supplier_label} | Insurance / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__insurance")
    with r2[4]:
        incoterm = st.selectbox(f"{supplier_label} | Incoterm", options=INCOTERM_OPTIONS, index=INCOTERM_OPTIONS.index("FOB"), key=f"{key_prefix}__incoterm")

    r3 = st.columns(4)
    with r3[0]:
        customs = st.number_input(f"{supplier_label} | Customs / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__customs_fees")
    with r3[1]:
        import_duties = st.number_input(f"{supplier_label} | Import duties / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__import_duties_taxes")
    with r3[2]:
        dom_freight = st.number_input(f"{supplier_label} | Domestic freight / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__domestic_freight")
    with r3[3]:
        local_taxes = st.number_input(f"{supplier_label} | Local taxes / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__local_taxes")

    comps = {
        "base_unit_price": float(base_unit_price), "conversion_cost": float(conversion_cost),
        "fixed_margin": float(fixed_margin), "international_freight": float(intl_freight),
        "insurance": float(insurance), "customs_fees": float(customs),
        "import_duties_taxes": float(import_duties), "domestic_freight": float(dom_freight),
        "local_taxes": float(local_taxes),
    }
    unit_price_q = sum(comps.values())
    unit_price_r = landed_unit_price(comps, float(fx_rate))
    spend = unit_price_r * float(volume)
    moq_excess = max(float(moq) - float(volume), 0.0) if float(moq) > 0 else 0.0
    moq_cash = moq_excess * unit_price_r
    moq_note = "OK" if float(moq) <= 0 or float(volume) >= float(moq) else "Volume below MOQ"
    moq_color = "#34d399" if moq_note == "OK" else "#f87171"
    st.markdown(
        f"""<div class="v46-landed">
        <b>Landed unit price:</b> {reporting_currency} {unit_price_r:,.6f} / {escape(unit)} &nbsp;·&nbsp;
        <b>100% equiv. spend:</b> {reporting_currency} {spend:,.2f} &nbsp;·&nbsp;
        <b>MOQ:</b> <span style="color:{moq_color}; font-weight:700">{moq_note}</span> &nbsp;·&nbsp;
        <b>MOQ cash tied:</b> {reporting_currency} {moq_cash:,.2f}
        </div>""",
        unsafe_allow_html=True,
    )
    return {
        "spend": float(spend), "unit_price_quote": float(unit_price_q),
        "unit_price_reporting": float(unit_price_r), "volume": float(volume),
        "moq": float(moq), "moq_excess_units_100pct": float(moq_excess),
        "moq_cash_tied_preview": float(moq_cash),
        "currency": currency, "fx_rate": float(fx_rate), "incoterm": incoterm, **comps,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SHARE ALLOCATION HELPERS  (identical logic to v45, kept for stability)
# ─────────────────────────────────────────────────────────────────────────────

def share_key(c, s): return f"share__{c}__{s}"
def min_key(s): return f"min_share__{s}"
def max_key(s): return f"max_share__{s}"
def kraljic_key(s): return f"kraljic_required__{s}"
def approved_key(s): return f"approved__{s}"
def supplier_name_key(s): return f"supplier_display_name__{s}"
def supplier_short_name_key(s): return f"supplier_short_name__{s}"

def supplier_display_name(s: str) -> str:
    v = str(st.session_state.get(supplier_name_key(s), DEFAULT_SUPPLIER_DISPLAY_NAME.get(s, s))).strip()
    return v or DEFAULT_SUPPLIER_DISPLAY_NAME.get(s, s)

def supplier_short_name(s: str) -> str:
    v = str(st.session_state.get(supplier_short_name_key(s), DEFAULT_SUPPLIER_SHORT_NAME.get(s, s))).strip()
    return v or DEFAULT_SUPPLIER_SHORT_NAME.get(s, s)

def supplier_display_html(s): return escape(supplier_display_name(s), quote=True)
def supplier_short_html(s): return escape(supplier_short_name(s), quote=True)

def get_min_shares() -> Dict[str, float]:
    return {s: float(st.session_state.get(min_key(s), DEFAULT_MIN_SHARE[s])) if bool(st.session_state.get(kraljic_key(s), DEFAULT_KRALJIC_REQUIRED[s])) else 0.0 for s in SUPPLIERS}

def get_max_shares() -> Dict[str, float]:
    return {s: float(st.session_state.get(max_key(s), DEFAULT_MAX_SHARE[s])) if bool(st.session_state.get(approved_key(s), DEFAULT_APPROVED[s])) else 0.0 for s in SUPPLIERS}

def constraint_issues(mins, maxs) -> List[str]:
    issues = []
    for s in SUPPLIERS:
        if mins[s] > maxs[s] + 1e-9:
            issues.append(f"{supplier_short_name(s)} min {mins[s]:.0f}% > capacity {maxs[s]:.0f}%.")
    if sum(mins.values()) > 100.0 + 1e-9:
        issues.append("Kraljic minimums exceed 100%.")
    if sum(maxs.values()) < 100.0 - 1e-9:
        issues.append("Supplier max constraints cannot reach 100%.")
    return issues

def clamp_shares_to_bounds(country: str) -> None:
    mins, maxs = get_min_shares(), get_max_shares()
    for s in SUPPLIERS:
        k = share_key(country, s)
        if k not in st.session_state:
            st.session_state[k] = DEFAULT_SHARES[country][s]
        st.session_state[k] = max(mins[s], min(maxs[s], float(st.session_state[k])))

def allocate_with_bounds(prefs, mins, maxs, total=100.0) -> Dict[str, float]:
    maxs = {s: max(float(maxs[s]), float(mins[s])) for s in SUPPLIERS}
    if sum(mins.values()) > total + 1e-9:
        return {s: safe_divide(mins[s], sum(mins.values())) * total for s in SUPPLIERS}
    if sum(maxs.values()) < total - 1e-9:
        return {s: safe_divide(maxs[s], sum(maxs.values())) * total for s in SUPPLIERS}
    shares = {s: mins[s] for s in SUPPLIERS}
    remaining = total - sum(shares.values())
    capacity = {s: max(0.0, maxs[s] - mins[s]) for s in SUPPLIERS}
    pref_excess = {s: max(0.0, prefs.get(s, 0.0) - mins[s]) for s in SUPPLIERS}
    if sum(pref_excess.values()) <= 1e-9:
        pref_excess = capacity.copy()
    active = {s for s in SUPPLIERS if capacity[s] > 1e-9}
    while remaining > 1e-8 and active:
        denom = sum(pref_excess[s] for s in active) or sum(capacity[s] for s in active) or 1
        weights = {s: pref_excess[s] / denom for s in active}
        moved = 0.0
        saturated = []
        for s in list(active):
            add = min(remaining * weights[s], capacity[s])
            shares[s] += add; capacity[s] -= add; moved += add
            if capacity[s] <= 1e-8: saturated.append(s)
        for s in saturated: active.discard(s)
        if moved <= 1e-8: break
        remaining -= moved
    diff = total - sum(shares.values())
    for s in SUPPLIERS:
        room = maxs[s] - shares[s]
        if abs(diff) <= 1e-6: break
        if diff > 0 and room > 1e-9: add = min(room, diff); shares[s] += add; diff -= add
        elif diff < 0 and shares[s] > mins[s] + 1e-9: rem = min(shares[s] - mins[s], -diff); shares[s] -= rem; diff += rem
    return {s: round(shares[s], 6) for s in SUPPLIERS}

def rebalance_after_slider_change(country: str, changed_supplier: str) -> None:
    mins, maxs = get_min_shares(), get_max_shares()
    ck = share_key(country, changed_supplier)
    cv = float(st.session_state.get(ck, DEFAULT_SHARES[country][changed_supplier]))
    cv = max(mins[changed_supplier], min(maxs[changed_supplier], cv))
    min_others = sum(mins[s] for s in SUPPLIERS if s != changed_supplier)
    max_others = sum(maxs[s] for s in SUPPLIERS if s != changed_supplier)
    cv = min(cv, 100.0 - min_others); cv = max(cv, 100.0 - max_others)
    cv = max(mins[changed_supplier], min(maxs[changed_supplier], cv))
    remaining = 100.0 - cv
    others = [s for s in SUPPLIERS if s != changed_supplier]
    prefs = {s: float(st.session_state.get(share_key(country, s), DEFAULT_SHARES[country][s])) for s in others}
    shares = allocate_with_bounds(prefs, {s: mins[s] for s in others}, {s: maxs[s] for s in others}, remaining)
    st.session_state[ck] = cv
    for s in others: st.session_state[share_key(country, s)] = round(shares[s], 4)

def apply_pending_optimized_shares() -> None:
    pending = st.session_state.pop("pending_optimized_shares", None)
    if not pending: return
    for country, sup_shares in pending.items():
        for s, v in sup_shares.items():
            st.session_state[share_key(country, s)] = float(v)
    st.session_state["last_optimization_applied"] = True

apply_pending_optimized_shares()


def init_defaults() -> None:
    for s in SUPPLIERS:
        st.session_state.setdefault(supplier_name_key(s), DEFAULT_SUPPLIER_DISPLAY_NAME[s])
        st.session_state.setdefault(supplier_short_name_key(s), DEFAULT_SUPPLIER_SHORT_NAME[s])
        st.session_state.setdefault(kraljic_key(s), DEFAULT_KRALJIC_REQUIRED[s])
        st.session_state.setdefault(min_key(s), DEFAULT_MIN_SHARE[s])
        st.session_state.setdefault(max_key(s), DEFAULT_MAX_SHARE[s])
        st.session_state.setdefault(approved_key(s), DEFAULT_APPROVED[s])
    for c in COUNTRIES:
        for s in SUPPLIERS:
            st.session_state.setdefault(share_key(c, s), DEFAULT_SHARES[c][s])

init_defaults()


# ─────────────────────────────────────────────────────────────────────────────
# FINANCIAL CALCULATION ENGINE  (preserved from v45, fully intact)
# ─────────────────────────────────────────────────────────────────────────────

def supplier_risk_scores(risk_inputs, risk_weights) -> Dict[str, float]:
    wt = sum(risk_weights.values()) or 1.0
    return {s: sum(risk_inputs[s][d] * risk_weights[d] for d in risk_weights) / wt for s in SUPPLIERS}

def inventory_days_from_ownership(ownership: str, lead: int, safety: int) -> int:
    if ownership == "Buyer owns transit + safety stock": return int(lead) + int(safety)
    if ownership == "Buyer owns safety stock only": return int(safety)
    return 0

def calc_moq_wc_drag(dp, req_vol, ci, method) -> Dict[str, float]:
    up = float(dp.get("unit_price_reporting", 0.0) or 0.0)
    moq = float(dp.get("moq", 0.0) or 0.0)
    rv = float(req_vol or 0.0)
    if up <= 0 or moq <= 0 or rv <= 0:
        return {"required_volume": rv, "effective_purchase_volume": rv, "excess_units": 0.0, "cash_tied": 0.0, "holding_days": 0.0, "lost_treasury_return": 0.0, "incremental_inventory_carry": 0.0, "working_capital_drag": 0.0}
    epv = max(rv, moq); excess = max(epv - rv, 0.0)
    if excess <= 0:
        return {"required_volume": rv, "effective_purchase_volume": epv, "excess_units": 0.0, "cash_tied": 0.0, "holding_days": 0.0, "lost_treasury_return": 0.0, "incremental_inventory_carry": 0.0, "working_capital_drag": 0.0}
    cash = excess * up
    holding = min(360.0, safe_divide(excess, rv) * 360.0)
    ltr = cash * equivalent_rate(ci["treasury_return_pct"], ci["treasury_reference_days"], holding, method)
    icc = cash * equivalent_rate(ci["inventory_carry_rate_pct"], 360, holding, method)
    return {"required_volume": rv, "effective_purchase_volume": epv, "excess_units": excess, "cash_tied": cash, "holding_days": holding, "lost_treasury_return": ltr, "incremental_inventory_carry": icc, "working_capital_drag": ltr + icc}

def calc_current_by_country(country: str, ci: Dict, method: str) -> Dict:
    inp = ci[country]
    s = inp["current_spend"]
    fr = equivalent_rate(inp["financial_rate_pct"], inp["financial_reference_days"], inp["current_payment_days"], method)
    tr = equivalent_rate(inp["treasury_return_pct"], inp["treasury_reference_days"], inp["current_payment_days"], method)
    ir = equivalent_rate(inp["inventory_carry_rate_pct"], 360, inp["current_inventory_days"], method)
    gfc = s * fr; cg = s * tr; ic = s * ir
    moq_d = calc_moq_wc_drag(inp.get("direct_profile", {}) or {}, float((inp.get("direct_profile", {}) or {}).get("volume", 0.0) or 0.0), inp, method) if inp.get("analysis_mode") == "Direct Materials" else calc_moq_wc_drag({}, 0.0, inp, method)
    return {"country": country, "base_spend": s, "gross_financial_cost": gfc, "capital_gain": cg, "inventory_cost": ic, "moq_cash_tied": moq_d["cash_tied"], "moq_lost_treasury_return": moq_d["lost_treasury_return"], "moq_incremental_inventory_carry": moq_d["incremental_inventory_carry"], "moq_working_capital_drag": moq_d["working_capital_drag"], "moq_excess_units": moq_d["excess_units"], "moq_holding_days": moq_d["holding_days"], "gross_total": s + gfc, "economic_total": s + gfc - cg + ic + moq_d["working_capital_drag"], "effective_financial_rate": fr, "effective_treasury_rate": tr, "payment_days": inp["current_payment_days"]}

def calc_proposal_by_country(country, shares, ci, pi, supplier_risk, method) -> Dict:
    inp = ci[country]
    ct = {"country": country, "new_spend": 0.0, "new_gross_financial_cost": 0.0, "new_capital_gain": 0.0, "new_inventory_cost": 0.0, "new_moq_cash_tied": 0.0, "new_moq_lost_treasury_return": 0.0, "new_moq_incremental_inventory_carry": 0.0, "new_moq_working_capital_drag": 0.0, "new_gross_total": 0.0, "new_economic_total": 0.0, "weighted_risk_numerator": 0.0, "weighted_payment_days_numerator": 0.0, "weighted_share_sum": 0.0, "weighted_financial_rate_numerator": 0.0, "weighted_treasury_rate_numerator": 0.0, "weighted_return_days_numerator": 0.0, "supplier_rows": []}
    for sup in SUPPLIERS:
        share = shares[sup] / 100.0
        sd = pi[country][sup]
        asp = sd["spend"] * share
        fr = equivalent_rate(inp["financial_rate_pct"], inp["financial_reference_days"], sd["payment_days"], method)
        tr = equivalent_rate(inp["treasury_return_pct"], inp["treasury_reference_days"], sd["payment_days"], method)
        inv_days = inventory_days_from_ownership(sd.get("inventory_ownership", "Buyer owns transit + safety stock"), sd["lead_time_days"], sd["safety_stock_days"])
        ir = equivalent_rate(inp["inventory_carry_rate_pct"], 360, inv_days, method)
        gf = asp * fr; cg = asp * tr; ic = asp * ir
        dp = sd.get("direct_profile", {}) or {}
        rv = float(dp.get("volume", 0.0) or 0.0) * share if inp.get("analysis_mode") == "Direct Materials" else 0.0
        moq_d = calc_moq_wc_drag(dp, rv, inp, method) if inp.get("analysis_mode") == "Direct Materials" and share > 0 else calc_moq_wc_drag({}, 0.0, inp, method)
        et = asp + gf - cg + ic + moq_d["working_capital_drag"]
        risk = supplier_risk[sup]
        ct["new_spend"] += asp; ct["new_gross_financial_cost"] += gf; ct["new_capital_gain"] += cg; ct["new_inventory_cost"] += ic
        ct["new_moq_cash_tied"] += moq_d["cash_tied"]; ct["new_moq_lost_treasury_return"] += moq_d["lost_treasury_return"]; ct["new_moq_incremental_inventory_carry"] += moq_d["incremental_inventory_carry"]; ct["new_moq_working_capital_drag"] += moq_d["working_capital_drag"]
        ct["new_gross_total"] += asp + gf; ct["new_economic_total"] += et
        ct["weighted_risk_numerator"] += asp * risk; ct["weighted_payment_days_numerator"] += share * sd["payment_days"]; ct["weighted_share_sum"] += share
        ct["weighted_financial_rate_numerator"] += asp * fr; ct["weighted_treasury_rate_numerator"] += asp * tr; ct["weighted_return_days_numerator"] += share * sd["payment_days"]
        sp = sd.get("service_profile", {}) or {}
        ct["supplier_rows"].append({"Country": country, "Supplier ID": sup, "Supplier": supplier_display_name(sup), "Item / Scope": sd.get("item_name", ""), "Unit / Demand Driver": sd.get("negotiated_unit", ""), "Quote Currency": dp.get("currency", ""), "FX Rate": dp.get("fx_rate", None), "Incoterm": dp.get("incoterm", ""), "Landed Unit Price": dp.get("unit_price_reporting", None), "100% Equivalent Volume": dp.get("volume", None), "MOQ": dp.get("moq", None), "MOQ Cash Tied": moq_d.get("cash_tied", None), "MOQ WC Drag": moq_d.get("working_capital_drag", None), "Service Scope": sp.get("scope", ""), "Pricing Model": sp.get("pricing_model", ""), "Proposed Contract Value": sp.get("proposed_contract_value", None), "Service TCO Before Productivity": sp.get("service_tco_before_productivity", None), "Productivity Gain": sp.get("productivity_gain", None), "Expected Risk Cost": sp.get("expected_risk_cost", None), "SLA Risk Cost": sp.get("sla_risk_cost", None), "SLA Attainment": sp.get("sla_attainment", None), "SLA Gap": sp.get("sla_gap", None), "Performance Score": sp.get("performance_score", None), "Performance Tier": sp.get("performance_tier", ""), "Performance-Adjusted Cost": sp.get("performance_adjusted_cost", None), "Headcount / FTEs": sp.get("headcount", None), "Price per Person / Month": sp.get("price_per_person_month", None), "Hourly Rate": sp.get("hourly_rate", None), "Overtime Hours / Month": sp.get("overtime_hours_month", None), "Overtime Cost": sp.get("overtime_cost", None), "Should-Cost Target": sp.get("should_cost_target", None), "Should-Cost Gap": sp.get("should_cost_gap", None), "Open-Cost Total": sp.get("open_cost_total", None), "Open-Cost Coverage %": sp.get("open_cost_coverage_pct", None), "Unexplained Quote Value": sp.get("unexplained_quote_value", None), "Productivity ROI %": sp.get("productivity_roi_pct", None), "Payback Months": sp.get("payback_months", None), "Total Contract Value": sp.get("total_contract_value", None), "Custom Cost Adjustment": sd.get("custom_cost_adjustment", 0.0), "Scope Creep %": sp.get("scope_creep_pct", None), "Rate Card Gap %": (sp.get("rate_card_compliance", {}) or {}).get("rate_gap_pct", None), "Share %": shares[sup], "Allocated Spend": asp, "Payment Days": sd["payment_days"], "Financial Rate Used": fr, "Treasury Return Rate Used": tr, "Supplier Financial Cost": gf, "Capital Gain Offset": cg, "Inventory Ownership": sd.get("inventory_ownership", ""), "Inventory Days Charged": inv_days, "Inventory Carrying Cost": ic, "Economic Total": et, "Risk Score": risk})
    sp_ = ct["new_spend"]
    ct["weighted_risk"] = safe_divide(ct["weighted_risk_numerator"], sp_)
    ct["avg_payment_days"] = safe_divide(ct["weighted_payment_days_numerator"], ct["weighted_share_sum"])
    ct["avg_return_days"] = safe_divide(ct["weighted_return_days_numerator"], ct["weighted_share_sum"])
    ct["avg_financial_rate"] = safe_divide(ct["weighted_financial_rate_numerator"], sp_)
    ct["avg_treasury_rate"] = safe_divide(ct["weighted_treasury_rate_numerator"], sp_)
    return ct

def calc_scenario(all_shares, ci, pi, supplier_risk, method):
    rows, sup_rows = [], []
    for country in COUNTRIES:
        cur = calc_current_by_country(country, ci, method)
        prop = calc_proposal_by_country(country, all_shares[country], ci, pi, supplier_risk, method)
        row = {"Country": country, "Group": PRIMARY_COUNTRY if country == PRIMARY_COUNTRY else SECONDARY_GROUP, "Current Spend": cur["base_spend"], "New Spend": prop["new_spend"], "Current Financial Cost": cur["gross_financial_cost"], "New Financial Cost": prop["new_gross_financial_cost"], "Current Total Spend": cur["gross_total"], "New Total Spend": prop["new_gross_total"], "Current Capital Gain": cur["capital_gain"], "New Capital Gain": prop["new_capital_gain"], "Current Net Financial Effect": cur["gross_financial_cost"] - cur["capital_gain"], "New Net Financial Effect": prop["new_gross_financial_cost"] - prop["new_capital_gain"], "Net Financial Delta": (prop["new_gross_financial_cost"] - prop["new_capital_gain"]) - (cur["gross_financial_cost"] - cur["capital_gain"]), "Current Inventory Cost": cur["inventory_cost"], "New Inventory Cost": prop["new_inventory_cost"], "Current MOQ Cash Tied": cur.get("moq_cash_tied", 0.0), "New MOQ Cash Tied": prop.get("new_moq_cash_tied", 0.0), "Current MOQ WC Drag": cur.get("moq_working_capital_drag", 0.0), "New MOQ WC Drag": prop.get("new_moq_working_capital_drag", 0.0), "Current Economic Total": cur["economic_total"], "New Economic Total": prop["new_economic_total"], "Spend Delta": prop["new_spend"] - cur["base_spend"], "Financial Delta": prop["new_gross_financial_cost"] - cur["gross_financial_cost"], "Gross All-In Delta": prop["new_gross_total"] - cur["gross_total"], "Capital Gain Delta": prop["new_capital_gain"] - cur["capital_gain"], "Treasury Return Offset Delta": cur["capital_gain"] - prop["new_capital_gain"], "Inventory Delta": prop["new_inventory_cost"] - cur["inventory_cost"], "MOQ Cash Tied Delta": prop.get("new_moq_cash_tied", 0.0) - cur.get("moq_cash_tied", 0.0), "MOQ WC Drag Delta": prop.get("new_moq_working_capital_drag", 0.0) - cur.get("moq_working_capital_drag", 0.0), "MOQ WC Benefit": cur.get("moq_working_capital_drag", 0.0) - prop.get("new_moq_working_capital_drag", 0.0), "Economic All-In Delta": prop["new_economic_total"] - cur["economic_total"], "Weighted Risk": prop["weighted_risk"], "Current Payment Days": cur["payment_days"], "New Avg Payment Days": prop["avg_payment_days"], "Current Effective Financial Rate": cur["effective_financial_rate"], "New Avg Financial Rate": prop["avg_financial_rate"], "Current Effective Treasury Rate": cur["effective_treasury_rate"], "New Avg Treasury Rate": prop["avg_treasury_rate"], "Current Return Days": cur["payment_days"], "New Avg Return Days": prop["avg_return_days"]}
        rows.append(row); sup_rows.extend(prop["supplier_rows"])
    cdf = pd.DataFrame(rows); sdf = pd.DataFrame(sup_rows)
    agg_cols = ["Current Spend", "New Spend", "Current Financial Cost", "New Financial Cost", "Current Total Spend", "New Total Spend", "Current Capital Gain", "New Capital Gain", "Current Net Financial Effect", "New Net Financial Effect", "Net Financial Delta", "Current Inventory Cost", "New Inventory Cost", "Current MOQ Cash Tied", "New MOQ Cash Tied", "Current MOQ WC Drag", "New MOQ WC Drag", "Current Economic Total", "New Economic Total", "Spend Delta", "Financial Delta", "Gross All-In Delta", "Capital Gain Delta", "Treasury Return Offset Delta", "Inventory Delta", "MOQ Cash Tied Delta", "MOQ WC Drag Delta", "MOQ WC Benefit", "Economic All-In Delta"]
    gdf = cdf.groupby("Group", as_index=False).agg({c: "sum" for c in agg_cols})
    req_groups = [PRIMARY_COUNTRY, SECONDARY_GROUP]
    gdf = gdf.set_index("Group").reindex(req_groups).reset_index().fillna(0.0)
    wrows = []
    for g in req_groups:
        sub = cdf[cdf["Group"] == g]
        tns = sub["New Spend"].sum(); tcs = sub["Current Spend"].sum()
        wrows.append({"Group": g, "Weighted Risk": safe_divide((sub["Weighted Risk"] * sub["New Spend"]).sum(), tns), "Current Avg Payment Days": safe_divide((sub["Current Payment Days"] * sub["Current Spend"]).sum(), tcs), "New Avg Payment Days": safe_divide((sub["New Avg Payment Days"] * sub["New Spend"]).sum(), tns), "New Avg Return Days": safe_divide((sub["New Avg Return Days"] * sub["New Spend"]).sum(), tns), "New Avg Financial Rate": safe_divide((sub["New Avg Financial Rate"] * sub["New Spend"]).sum(), tns), "New Avg Treasury Rate": safe_divide((sub["New Avg Treasury Rate"] * sub["New Spend"]).sum(), tns)})
    gdf = gdf.merge(pd.DataFrame(wrows), on="Group", how="left")
    total = {c: cdf[c].sum() for c in agg_cols}
    tns = cdf["New Spend"].sum(); tcs = cdf["Current Spend"].sum()
    total["Weighted Risk"] = safe_divide((cdf["Weighted Risk"] * cdf["New Spend"]).sum(), tns)
    total["Current Avg Payment Days"] = safe_divide((cdf["Current Payment Days"] * cdf["Current Spend"]).sum(), tcs)
    total["New Avg Payment Days"] = safe_divide((cdf["New Avg Payment Days"] * cdf["New Spend"]).sum(), tns)
    total["New Avg Return Days"] = safe_divide((cdf["New Avg Return Days"] * cdf["New Spend"]).sum(), tns)
    total["New Avg Financial Rate"] = safe_divide((cdf["New Avg Financial Rate"] * cdf["New Spend"]).sum(), tns)
    total["New Avg Treasury Rate"] = safe_divide((cdf["New Avg Treasury Rate"] * cdf["New Spend"]).sum(), tns)
    return cdf, gdf, sdf, total

def calc_full_supplier_reference_stack(supplier, ci, pi, method, payment_day_overrides=None) -> Dict:
    ts, tfc, tts, wpdn = 0.0, 0.0, 0.0, 0.0
    for c in COUNTRIES:
        inp = ci[c]; sd = pi[c][supplier]; sp = sd["spend"]
        pd_ = payment_day_overrides.get(c, sd["payment_days"]) if payment_day_overrides else sd["payment_days"]
        fr = equivalent_rate(inp["financial_rate_pct"], inp["financial_reference_days"], pd_, method)
        fc = sp * fr; ts += sp; tfc += fc; tts += sp + fc; wpdn += sp * pd_
    return {"Reference Spend": ts, "Reference Financial Cost": tfc, "Reference Total Spend": tts, "Reference Avg Payment Days": safe_divide(wpdn, ts)}


# ─────────────────────────────────────────────────────────────────────────────
# OPTIMIZATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def _sup_unit_econ_cost(country, supplier, ci, pi, method) -> float:
    inp = ci[country]; sd = pi[country][supplier]; sp = sd["spend"]
    fr = equivalent_rate(inp["financial_rate_pct"], inp["financial_reference_days"], sd["payment_days"], method)
    tr = equivalent_rate(inp["treasury_return_pct"], inp["treasury_reference_days"], sd["payment_days"], method)
    inv_d = inventory_days_from_ownership(sd.get("inventory_ownership", "Buyer owns transit + safety stock"), sd["lead_time_days"], sd["safety_stock_days"])
    ir = equivalent_rate(inp["inventory_carry_rate_pct"], 360, inv_d, method)
    return sp * (1 + fr - tr + ir)

def _opt_lp(ci, pi, supplier_risk, method, risk_threshold) -> Tuple[Dict, str]:
    if not SCIPY_AVAILABLE: raise RuntimeError("SciPy not available")
    mins, maxs = get_min_shares(), get_max_shares()
    issues = constraint_issues(mins, maxs)
    if issues: raise ValueError("; ".join(issues))
    variables = [(c, s) for c in COUNTRIES for s in SUPPLIERS]
    n = len(variables)
    mean_cost = sum(_sup_unit_econ_cost(c, s, ci, pi, method) for c, s in variables) / max(n, 1)
    rb = mean_cost * 1e-7
    c_vec = [_sup_unit_econ_cost(c, s, ci, pi, method) + rb * supplier_risk[s] for c, s in variables]
    A_eq, b_eq = [], []
    for country in COUNTRIES:
        row = [1.0 if vc == country else 0.0 for vc, _ in variables]
        A_eq.append(row); b_eq.append(1.0)
    A_ub, b_ub = [], []
    for country in COUNTRIES:
        row = [pi[vc][vs]["spend"] * (supplier_risk[vs] - risk_threshold) if vc == country else 0.0 for vc, vs in variables]
        A_ub.append(row); b_ub.append(0.0)
    bounds = [(mins[s] / 100.0, maxs[s] / 100.0) for _, s in variables]
    result = linprog(c=c_vec, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    rg = True
    if not result.success:
        result = linprog(c=c_vec, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs"); rg = False
    if not result.success: raise ValueError(f"No feasible allocation: {result.message}")
    opt = {c: {} for c in COUNTRIES}
    for val, (c, s) in zip(result.x, variables): opt[c][s] = round(float(val) * 100.0, 4)
    return opt, "Exact LP" + ("" if rg else " (risk gate relaxed)")

def _opt_grid(ci, pi, supplier_risk, method, risk_threshold, step) -> Tuple[Dict, str]:
    mins, maxs = get_min_shares(), get_max_shares()
    issues = constraint_issues(mins, maxs)
    if issues: raise ValueError("; ".join(issues))
    min_u = {s: int(math.ceil(mins[s] / step - 1e-12)) for s in SUPPLIERS}
    max_u = {s: int(math.floor(maxs[s] / step + 1e-12)) for s in SUPPLIERS}
    total_u = int(round(100 / step))
    combos = [dict(zip(SUPPLIERS, vals)) for vals in product(*(range(min_u[s], max_u[s] + 1) for s in SUPPLIERS)) if sum(vals) == total_u]
    if not combos: raise ValueError("No feasible combination under current constraints.")
    combos_scaled = [{s: v * step for s, v in c_.items()} for c_ in combos]
    opt = {}
    for country in COUNTRIES:
        cur = calc_current_by_country(country, ci, method)
        best_r = best_o = None
        for sh in combos_scaled:
            prop = calc_proposal_by_country(country, sh, ci, pi, supplier_risk, method)
            ed = prop["new_economic_total"] - cur["economic_total"]
            key_ = (ed, prop["weighted_risk"])
            row_ = {"Shares": sh, "ed": ed, "wr": prop["weighted_risk"]}
            if best_o is None or key_ < (best_o["ed"], best_o["wr"]): best_o = row_
            if prop["weighted_risk"] <= risk_threshold:
                if best_r is None or key_ < (best_r["ed"], best_r["wr"]): best_r = row_
        opt[country] = (best_r or best_o)["Shares"]
    return opt, f"Grid optimizer ({step}% step)"

def optimize_allocations(ci, pi, supplier_risk, method, risk_threshold, step):
    try:
        opt, msg = _opt_lp(ci, pi, supplier_risk, method, risk_threshold)
    except Exception as e:
        opt, msg = _opt_grid(ci, pi, supplier_risk, method, risk_threshold, step)
        msg += f" (LP unavailable: {e})"
    cdf_o, _, _, total_o = calc_scenario(opt, ci, pi, supplier_risk, method)
    rat_rows = []
    for _, row in cdf_o.iterrows():
        c = row["Country"]
        rat_rows.append({"Country": c, "Chosen Risk": row["Weighted Risk"], "Economic Delta": row["Economic All-In Delta"], "Gross All-In Delta": row["Gross All-In Delta"], "Spend Delta": row["Spend Delta"], **{supplier_short_name(s): opt[c][s] for s in SUPPLIERS}, "Risk Gate Met": row["Weighted Risk"] <= risk_threshold})
    full_msg = f"Optimization applied. {msg}. Objective: lowest economic all-in. Total delta: {total_o['Economic All-In Delta']:,.2f}."
    return opt, pd.DataFrame(rat_rows), full_msg


# ─────────────────────────────────────────────────────────────────────────────
# AI EXECUTIVE BRIEF
# ─────────────────────────────────────────────────────────────────────────────

def build_ai_payload(*, analysis_mode, total, group_df, supplier_focus_df, focused_supplier_count, currency) -> str:
    primary = _safe_group_row(group_df, PRIMARY_COUNTRY)
    secondary = _safe_group_row(group_df, SECONDARY_GROUP)
    focus = supplier_focus_df.head(focused_supplier_count) if isinstance(supplier_focus_df, pd.DataFrame) else pd.DataFrame()
    focus_lines = []
    if not focus.empty:
        for _, row in focus.iterrows():
            extra = ""
            if analysis_mode == "Indirect / Services" and pd.notna(row.get("Performance Score", None)):
                extra = f" | Score {row.get('Performance Score',0):.1f}/100 | ROI {row.get('Productivity ROI %', 0):.0f}% | OT {row.get('Overtime Hours / Month', 0):.0f}h/mo | SLA gap {row.get('SLA Gap', 0):.1f}pp"
            focus_lines.append(f"#{int(row.get('Rank',0))} {row.get('Supplier','')} | Econ total: {currency} {row.get('Economic Total',0):,.0f} | Risk: {row.get('Risk Score',0):.2f}/5{extra}")
    return "\n".join([
        "Act as a senior executive procurement advisor (Amazon/McKinsey caliber). Concise, decision-oriented recommendation.",
        f"Mode: {analysis_mode}",
        f"Gross saving/impact: {currency} {total.get('Gross All-In Delta',0):,.0f}",
        f"WC gain/impact: {currency} {total.get('Treasury Return Offset Delta',0):,.0f}",
        f"Inventory delta: {currency} {total.get('Inventory Delta',0):,.0f}",
        f"Final economic all-in: {currency} {total.get('Economic All-In Delta',0):,.0f}",
        f"Weighted risk: {total.get('Weighted Risk',0):.2f}/5",
        f"{PRIMARY_COUNTRY}: {currency} {primary.get('Economic All-In Delta',0):,.0f} | term {primary.get('Current Avg Payment Days',0):.0f}→{primary.get('New Avg Payment Days',0):.0f}dd",
        f"{SECONDARY_GROUP}: {currency} {secondary.get('Economic All-In Delta',0):,.0f}",
        "Top supplier focus:", *focus_lines,
        "Return: recommendation, best option, risk watchouts, negotiation levers and next actions. 200 words max.",
    ])

def generate_local_brief(*, analysis_mode, total, group_df, supplier_focus_df, focused_supplier_count, currency) -> str:
    fd = float(total.get("Economic All-In Delta", 0.0))
    gd = float(total.get("Gross All-In Delta", 0.0))
    wc = float(total.get("Treasury Return Offset Delta", 0.0))
    inv = float(total.get("Inventory Delta", 0.0))
    risk = float(total.get("Weighted Risk", 0.0))
    primary = _safe_group_row(group_df, PRIMARY_COUNTRY)
    secondary = _safe_group_row(group_df, SECONDARY_GROUP)
    focus = supplier_focus_df.head(max(1, focused_supplier_count)) if isinstance(supplier_focus_df, pd.DataFrame) else pd.DataFrame()
    best_sup = "No supplier ranked"
    best_rat = "Complete supplier inputs to generate."
    if not focus.empty:
        top = focus.iloc[0]
        best_sup = str(top.get("Supplier", ""))
        if analysis_mode == "Indirect / Services":
            roi = top.get("Productivity ROI %", None); sla_g = top.get("SLA Gap", None)
            best_rat = f"best perf-adj cost — Score {top.get('Performance Score',0):.0f}/100 | ROI {roi:.0f}% | SLA gap {sla_g:.1f}pp | risk {top.get('Risk Score',0):.2f}/5." if pd.notna(roi) else f"best economic + risk {top.get('Risk Score',0):.2f}/5."
        else:
            best_rat = f"best landed cost + risk {top.get('Risk Score',0):.2f}/5."
    decision = "Approve / advance to negotiation" if fd <= 0 and risk <= 3.5 else ("Do not approve — renegotiate price and terms" if fd > 0 else "Negotiate before approval")
    wc_msg = "favorable — longer terms create treasury value" if wc < 0 else "unfavorable — treasury return reduces"
    svc_extra = ""
    if analysis_mode == "Indirect / Services":
        svc_extra = "<li><b>Services action:</b> challenge FTE right-sizing, overtime cost, SLA attainment, rate-card compliance and supplier productivity commitments with hard-dollar targets before contracting.</li>"
    else:
        svc_extra = "<li><b>Direct materials action:</b> challenge landed unit price, FX exposure, incoterm cost ownership, MOQ economics and lead time before contracting.</li>"
    return f"""<div class="v46-ai-card">
        <h4>⚡ AI Executive Copilot — Concise Recommendation</h4>
        <ul>
            <li><b>Decision:</b> {decision}. Economic all-in = <b>{fmt_money(fd, currency, compact=True, signed=True)}</b> | Weighted risk = <b>{risk:.2f}/5</b>.</li>
            <li><b>Best option:</b> {escape(best_sup)} — {escape(best_rat)}</li>
            <li><b>Value bridge:</b> Gross = <b>{fmt_money(gd, currency, compact=True, signed=True)}</b> | Working capital {wc_msg} = <b>{fmt_money(wc, currency, compact=True, signed=True)}</b> | Inventory = <b>{fmt_money(inv, currency, compact=True, signed=True)}</b>.</li>
            <li><b>Market split:</b> {escape(PRIMARY_COUNTRY)} = <b>{fmt_money(primary.get('Economic All-In Delta',0), currency, compact=True, signed=True)}</b> | {escape(SECONDARY_GROUP)} = <b>{fmt_money(secondary.get('Economic All-In Delta',0), currency, compact=True, signed=True)}</b>.</li>
            {svc_extra}
            <li><b>Next action:</b> run final negotiation round on price, payment terms, risk mitigation and productivity commitments with the top {focused_supplier_count} supplier(s).</li>
        </ul>
    </div>"""



# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚡ Intelligence Platform")
    currency_symbol = st.text_input("Reporting currency", value="BRL")
    project_title = st.text_input("Project title", value=st.session_state.get("project_head_title", "Procurement Intelligence Platform"), key="project_head_title")
    project_subtitle = st.text_input("Project subtitle", value=st.session_state.get("project_subtitle", ""), key="project_subtitle")

    st.markdown("### Analysis mode")
    analysis_mode = st.radio("Tool mode", options=["Direct Materials", "Indirect / Services"], index=0, horizontal=False)
    if analysis_mode == "Direct Materials":
        st.markdown('<div class="v46-mode-card"><div class="v46-mode-card-title">🧪 Direct Materials</div><div class="v46-mode-card-sub">Landed cost → price build-up → spend → TCO, working capital, inventory & risk optimization.</div></div>', unsafe_allow_html=True)
        analysed_item_name = st.text_input("Analysed item", value=DEFAULT_ITEM_NAME, key="direct_item_name")
        negotiated_unit = st.text_input("Negotiated unit", value=DEFAULT_NEGOTIATED_UNIT, key="direct_negotiated_unit")
        service_scope = None
    else:
        st.markdown('<div class="v46-mode-card"><div class="v46-mode-card-title">🎯 Indirect / Services</div><div class="v46-mode-card-sub">Service TCO → FTE decomposition → leakage waterfall → SLA risk → productivity ROI → scorecard → decision.</div></div>', unsafe_allow_html=True)
        service_scope = st.selectbox("Service / buying scope", options=SERVICE_SCOPES, index=SERVICE_SCOPES.index(DEFAULT_SERVICE_SCOPE), key="service_scope")
        cfg_sb = service_scope_config(service_scope)
        analysed_item_name = st.text_input("Service / scope name", value=service_scope, key="service_item_name")
        negotiated_unit = st.text_input("Main demand driver", value=str(cfg_sb.get("driver_label", "service unit")), key="service_negotiated_unit")
        st.caption(f"Productivity: {cfg_sb.get('productivity_label','')}")

    st.markdown("### Geography")
    view_scope = st.radio("Analysis scope", options=["Global View", "Local View"], index=0, horizontal=True, key="market_view_scope")
    VIEW_SCOPE = view_scope

    if view_scope == "Global View":
        default_sel = st.session_state.get("selected_country_scope", DEFAULT_ACTIVE_COUNTRIES)
        default_sel = [c for c in default_sel if c in COUNTRY_OPTIONS] or DEFAULT_ACTIVE_COUNTRIES
        selected_countries = st.multiselect("Countries", options=COUNTRY_OPTIONS, default=default_sel, key="selected_country_scope")
        if not selected_countries: selected_countries = ["Brazil"]
        prim_def = st.session_state.get("primary_country_scope", selected_countries[0])
        prim_idx = selected_countries.index(prim_def) if prim_def in selected_countries else 0
        primary_country_choice = st.selectbox("Primary / anchor country", options=selected_countries, index=prim_idx, key="primary_country_scope")
        COUNTRIES = list(selected_countries)
        PRIMARY_COUNTRY = primary_country_choice
        ANCHOR_COUNTRY = primary_country_choice
        SECONDARY_GROUP = "Other selected markets"
        scope_label = "country/countries"
    else:
        anchor_choice = st.selectbox("Anchor country", options=COUNTRY_OPTIONS, index=COUNTRY_OPTIONS.index(st.session_state.get("local_anchor_country","Brazil")) if st.session_state.get("local_anchor_country","Brazil") in COUNTRY_OPTIONS else COUNTRY_OPTIONS.index("Brazil"), key="local_anchor_country")
        ANCHOR_COUNTRY = anchor_choice
        loc_data = build_locality_options(anchor_choice)
        loc_opts = [x["name"] for x in loc_data]
        for x in loc_data: LOCALITY_COORDS[x["name"]] = {"lat": float(x["lat"]), "lon": float(x["lon"])}
        def_loc = st.session_state.get("selected_locality_scope", loc_opts[:min(4, len(loc_opts))])
        def_loc = [l for l in def_loc if l in loc_opts] or loc_opts[:min(3, len(loc_opts))]
        selected_locs = st.multiselect("Localities", options=loc_opts, default=def_loc, key="selected_locality_scope")
        custom_loc_text = st.text_area("Custom localities", value=st.session_state.get("custom_locality_text",""), key="custom_locality_text", placeholder="One per line", height=80)
        custom_locs = [l.strip() for l in custom_loc_text.splitlines() if l.strip()]
        selected_countries = list(dict.fromkeys(selected_locs + custom_locs)) or [loc_opts[0]]
        prim_def = st.session_state.get("primary_locality_scope", selected_countries[0])
        prim_idx = selected_countries.index(prim_def) if prim_def in selected_countries else 0
        primary_country_choice = st.selectbox("Primary locality", options=selected_countries, index=prim_idx, key="primary_locality_scope")
        COUNTRIES = list(selected_countries)
        PRIMARY_COUNTRY = primary_country_choice
        SECONDARY_GROUP = "Other selected localities"
        scope_label = "locality/localities"

    LATAM_COUNTRIES = [c for c in COUNTRIES if c != PRIMARY_COUNTRY]
    CUSTOM_FACTOR_COUNTRIES = ["All countries"] + COUNTRIES
    for _sc in COUNTRIES: ensure_analysis_unit_defaults(_sc, ANCHOR_COUNTRY)

    chips = "".join([f"<span class='v46-chip'>{escape(c)}</span>" for c in COUNTRIES])
    st.markdown(f"""<div class="v46-market-card">
        <div class="v46-market-title">{'🌎 Global' if view_scope == 'Global View' else '📍 Local'} market scope</div>
        <div class="v46-market-meta"><b>{len(COUNTRIES)}</b> {scope_label} · anchor: <b>{escape(ANCHOR_COUNTRY)}</b> · focus: <b>{escape(PRIMARY_COUNTRY)}</b></div>
        <div>{chips}</div></div>""", unsafe_allow_html=True)

    rate_method = st.radio("Rate conversion", options=["Compound", "Linear"], index=0)
    opt_step = st.select_slider("Grid optimization step", options=[1, 2, 5, 10], value=5)
    st.caption("Optimizer: exact LP ✓" if SCIPY_AVAILABLE else "Optimizer: grid fallback only")
    risk_threshold = st.slider("Risk ceiling", min_value=1.0, max_value=5.0, value=3.25, step=0.05)

    st.markdown("### Supplier universe")
    sup_count_def = int(st.session_state.get("supplier_count_control", min(4, len(SUPPLIER_POOL))))
    sup_count_def = max(1, min(len(SUPPLIER_POOL), sup_count_def))
    supplier_count = st.slider("Number of suppliers", min_value=1, max_value=len(SUPPLIER_POOL), value=sup_count_def, step=1, key="supplier_count_control")
    focused_def = int(st.session_state.get("focused_supplier_count_control", min(4, int(supplier_count))))
    focused_def = max(1, min(int(supplier_count), focused_def))
    focused_supplier_count = st.slider("Top suppliers (executive focus)", min_value=1, max_value=int(supplier_count), value=focused_def, step=1, key="focused_supplier_count_control")
    SUPPLIERS = SUPPLIER_POOL[:int(supplier_count)]
    st.session_state["focused_supplier_count"] = int(focused_supplier_count)
    show_adv_econ = st.checkbox("Show working capital view", value=True)

    with st.expander("Supplier names", expanded=False):
        for idx, sup in enumerate(SUPPLIERS, start=1):
            st.text_input(f"Supplier {idx} full name", key=supplier_name_key(sup))
            st.text_input(f"Supplier {idx} short label", key=supplier_short_name_key(sup))


# ─────────────────────────────────────────────────────────────────────────────
# HERO HEADER
# ─────────────────────────────────────────────────────────────────────────────

mode_chip = "Direct Materials Cockpit" if analysis_mode == "Direct Materials" else "Indirect / Services Command Center"
hero_copy = ("Landed cost · FX · Incoterm · MOQ · Payment terms · Treasury return · Inventory · Risk optimization" if analysis_mode == "Direct Materials" else "Service TCO · FTE decomposition · Contract leakage · SLA risk · Productivity ROI · Should-cost · Scorecard")
hero_title = project_title.strip() or "Procurement Intelligence Platform"
hero_sub = project_subtitle.strip() or hero_copy

st.markdown(
    f"""<div class="v46-hero">
        <div class="v46-hero-mode-chip">{mode_chip}</div>
        <h1>{escape(hero_title)}</h1>
        <p>{escape(hero_sub)}</p>
        <div class="v46-hero-stats">
            <div class="v46-hero-stat"><div class="v46-hero-stat-label">Markets</div><div class="v46-hero-stat-value">{len(COUNTRIES)}</div></div>
            <div class="v46-hero-stat"><div class="v46-hero-stat-label">Suppliers</div><div class="v46-hero-stat-value">{len(SUPPLIERS)}</div></div>
            <div class="v46-hero-stat"><div class="v46-hero-stat-label">Mode</div><div class="v46-hero-stat-value">{'Direct' if analysis_mode == 'Direct Materials' else 'Services'}</div></div>
            <div class="v46-hero-stat"><div class="v46-hero-stat-label">Optimizer</div><div class="v46-hero-stat-value">{'LP exact' if SCIPY_AVAILABLE else 'Grid'}</div></div>
            <div class="v46-hero-stat"><div class="v46-hero-stat-label">View</div><div class="v46-hero-stat-value">{VIEW_SCOPE.split()[0]}</div></div>
        </div>
    </div>""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# INPUT TABS
# ─────────────────────────────────────────────────────────────────────────────

input_tabs = st.tabs([
    "1 · Current Baseline", "2 · Supplier Proposals",
    "3 · Supplier Management", "4 · Custom Points",
    "5 · Risk & Constraints", "6 · Share & Optimization",
    "7 · Executive Dash",
])

# ── TAB 1: Current Baseline ──────────────────────────────────────────────────
with input_tabs[0]:
    if analysis_mode == "Direct Materials":
        render_section("Current Direct Material Baseline", "Landed unit price × volume → current spend → financial, treasury & inventory economics.", "#3b82f6")
        st.info("Current spend = landed unit price × 100% equivalent volume per country.")
    else:
        render_section("Current Indirect / Services Baseline", "Service TCO → FTE decomposition → contract leakage waterfall → lifecycle cost.", "#8b5cf6")
        st.info("Current spend = Service TCO (contracted value + leakage − credits). Amazon standard: model all leakage vectors before benchmarking suppliers.")

    country_inputs: Dict = {}
    for country in COUNTRIES:
        with st.expander(f"{'🌎' if VIEW_SCOPE=='Global View' else '📍'} {country}", expanded=(country == PRIMARY_COUNTRY)):
            dp_: Dict = {}; sp_: Dict = {}
            if analysis_mode == "Direct Materials":
                dp_ = render_landed_cost_builder(key_prefix=f"cur_dir__{country}", default_spend=DEFAULT_CURRENT_SPEND[country], default_volume=DEFAULT_DIRECT_VOLUME[country], unit=negotiated_unit, reporting_currency=currency_symbol, currency_default=DEFAULT_DIRECT_CURRENCY[country], supplier_label=f"{country} current")
                current_spend = float(dp_["spend"])
            else:
                sp_ = render_service_baseline_builder(key_prefix=f"cur_svc__{country}", country=country, scope=service_scope or DEFAULT_SERVICE_SCOPE, reporting_currency=currency_symbol)
                current_spend = float(sp_["service_tco"])
            st.markdown("<div class='v46-plain-title'>Financial, treasury & inventory parameters</div>", unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                cur_pmt = st.number_input(f"{country} current payment days", min_value=1, value=DEFAULT_CURRENT_TERM[country], step=1, key=f"v46_cur_pmt__{country}")
                cur_inv = st.number_input(f"{country} current inventory days", min_value=0, value=DEFAULT_CURRENT_INVENTORY_DAYS[country] if analysis_mode=="Direct Materials" else 0, step=1, key=f"v46_cur_inv__{country}", disabled=(analysis_mode!="Direct Materials"))
            with c2:
                fin_rate = st.number_input(f"{country} financial rate %", min_value=0.0, value=DEFAULT_FINANCIAL_RATE[country], step=0.05, format="%.4f", key=f"v46_fin_rate__{country}")
                fin_ref_days = st.number_input(f"{country} fin. rate reference days", min_value=1, value=DEFAULT_REFERENCE_DAYS[country], step=1, key=f"v46_fin_ref__{country}")
            with c3:
                treas_rate = st.number_input(f"{country} net treasury return %", min_value=0.0, value=DEFAULT_TREASURY_RETURN[country], step=0.05, format="%.4f", key=f"v46_treas__{country}")
                treas_ref = st.number_input(f"{country} treasury ref. days", min_value=1, value=DEFAULT_TREASURY_REF_DAYS[country], step=1, key=f"v46_treas_ref__{country}")
            with c4:
                inv_rate = st.number_input(f"{country} inventory carry rate % p.a.", min_value=0.0, value=DEFAULT_INVENTORY_CARRY_RATE[country] if analysis_mode=="Direct Materials" else 0.0, step=0.05, format="%.4f", key=f"v46_inv_rate__{country}", disabled=(analysis_mode!="Direct Materials"))
                st.markdown("<div class='v46-note'>Financial/treasury use current payment term for baseline. Proposals use each supplier's term.</div>", unsafe_allow_html=True)
            country_inputs[country] = {"current_spend": float(current_spend), "current_payment_days": int(cur_pmt), "financial_rate_pct": float(fin_rate), "financial_reference_days": int(fin_ref_days), "treasury_return_pct": float(treas_rate), "treasury_reference_days": int(treas_ref), "inventory_carry_rate_pct": float(inv_rate), "current_inventory_days": int(cur_inv), "analysis_mode": analysis_mode, "item_name": analysed_item_name, "negotiated_unit": negotiated_unit, "direct_profile": dp_, "service_profile": sp_, "service_scope": service_scope}

# ── TAB 2: Supplier Proposals ────────────────────────────────────────────────
with input_tabs[1]:
    if analysis_mode == "Direct Materials":
        render_section("Supplier Direct Material Proposals", "Price build-up → landed unit price → 100% equivalent spend → TCO engine.", "#3b82f6")
    else:
        render_section("Supplier Service Proposals", "Contract value → FTE decomposition → SLA risk → should-cost → productivity ROI → service TCO.", "#8b5cf6")

    proposal_inputs: Dict = {c: {} for c in COUNTRIES}
    for country in COUNTRIES:
        with st.expander(f"{'🌎' if VIEW_SCOPE=='Global View' else '📍'} {country}", expanded=(country == PRIMARY_COUNTRY)):
            cvd = float(country_inputs[country].get("direct_profile", {}).get("volume", DEFAULT_DIRECT_VOLUME[country])) if analysis_mode=="Direct Materials" else DEFAULT_DIRECT_VOLUME[country]
            for sup in SUPPLIERS:
                disp = supplier_display_name(sup)
                label = f"{'📦' if analysis_mode=='Direct Materials' else '🧾'} {supplier_short_name(sup)} — {disp}"
                with st.expander(label, expanded=(country==PRIMARY_COUNTRY and sup==SUPPLIERS[0])):
                    st.markdown(f"<div class='v46-supplier-box'><span class='v46-pill'>{supplier_short_html(sup)}</span>", unsafe_allow_html=True)
                    dp_s: Dict = {}; sp_s: Dict = {}
                    if analysis_mode == "Direct Materials":
                        dp_s = render_landed_cost_builder(key_prefix=f"prop_dir__{country}__{sup}", default_spend=DEFAULT_PROPOSAL_SPEND[country][sup], default_volume=cvd, unit=negotiated_unit, reporting_currency=currency_symbol, currency_default=DEFAULT_DIRECT_CURRENCY[country], supplier_label=f"{country} | {disp}")
                        spend_ = float(dp_s["spend"])
                    else:
                        sp_s = render_service_supplier_builder(key_prefix=f"prop_svc__{country}__{sup}", country=country, scope=service_scope or DEFAULT_SERVICE_SCOPE, supplier_label=f"{country} | {disp}", default_spend=DEFAULT_PROPOSAL_SPEND[country][sup], reporting_currency=currency_symbol)
                        spend_ = float(sp_s["service_tco"])
                    c2_, c3_, c4_, c5_ = st.columns([.75, .75, .75, 1.2])
                    with c2_:
                        pmt_days = st.number_input(f"{country} | {disp} | Payment days", min_value=0, value=DEFAULT_PAYMENT_TERM[country][sup], step=1, key=f"prop_term__{country}__{sup}")
                    with c3_:
                        lead_time = st.number_input(f"{country} | {disp} | Lead time days", min_value=0, value=(DEFAULT_LEAD_TIME_DAYS[country][sup] if analysis_mode=="Direct Materials" else int(sp_s.get("transition_days", 30))), step=1, key=f"lead__{country}__{sup}")
                    with c4_:
                        safety_st = st.number_input(f"{country} | {disp} | Safety stock days", min_value=0, value=DEFAULT_SAFETY_STOCK_DAYS[country][sup] if analysis_mode=="Direct Materials" else 0, step=1, key=f"sstock__{country}__{sup}", disabled=(analysis_mode!="Direct Materials"))
                    with c5_:
                        inv_own = st.selectbox(f"{country} | {disp} | Inventory ownership", options=INVENTORY_OWNERSHIP_OPTIONS, index=INVENTORY_OWNERSHIP_OPTIONS.index(DEFAULT_INVENTORY_OWNERSHIP[country][sup] if analysis_mode=="Direct Materials" else "Supplier/trader owns until delivery"), key=f"invown__{country}__{sup}", disabled=(analysis_mode!="Direct Materials"))
                    st.markdown("</div>", unsafe_allow_html=True)
                    proposal_inputs[country][sup] = {"spend": float(spend_), "payment_days": int(pmt_days), "lead_time_days": int(lead_time), "safety_stock_days": int(safety_st), "inventory_ownership": inv_own, "analysis_mode": analysis_mode, "item_name": analysed_item_name, "negotiated_unit": negotiated_unit, "direct_profile": dp_s, "service_profile": sp_s, "service_scope": service_scope}

# ── TAB 3: Supplier Management ────────────────────────────────────────────────
with input_tabs[2]:
    render_section("Supplier Management, Performance & Due Diligence", "Governance scorecards → risk defaults → optimization feed.", "#06b6d4")
    supplier_management_inputs: Dict = {}; gov_rows = []
    for sup in SUPPLIERS:
        with st.expander(f"🛡️ {supplier_display_name(sup)}", expanded=(sup==SUPPLIERS[0])):
            st.markdown("<div class='v46-gov-card'>", unsafe_allow_html=True)
            gc = st.columns(4); gov_scores: Dict[str, float] = {}
            for idx, dim in enumerate(list(SUPPLIER_GOVERNANCE_WEIGHTS.keys())):
                with gc[idx % 4]:
                    gov_scores[dim] = st.slider(dim, 0.0, 100.0, 82.0, 1.0, key=f"gov__{sup}__{dim}")
            d1_, d2_, d3_, d4_ = st.columns(4)
            with d1_: dd_st = st.selectbox("Due diligence", options=DUE_DILIGENCE_STATUS_OPTIONS, index=0, key=f"gov__{sup}__dd")
            with d2_: qbr = st.selectbox("Governance cadence", ["Monthly","Quarterly","Semiannual","Annual","Ad hoc"], index=1, key=f"gov__{sup}__qbr")
            with d3_: ca = st.number_input("Open corrective actions", min_value=0, value=0, step=1, key=f"gov__{sup}__ca")
            with d4_: dep = st.selectbox("Business dependency", ["Low","Medium","High","Critical"], index=1, key=f"gov__{sup}__dep")
            gov_sc = weighted_governance_score(gov_scores); g_tier = governance_tier(gov_sc)
            supplier_management_inputs[sup] = {**gov_scores, "Due diligence status": dd_st, "Governance cadence": qbr, "Open corrective actions": float(ca), "Business dependency": dep, "Governance score": gov_sc, "Governance tier": g_tier}
            st.markdown(f"""<div class="v46-svc-result"><b>Governance score:</b> <span class="v46-score-badge" style="color:{service_score_color(gov_sc)};border-color:{service_score_color(gov_sc)}">{gov_sc:.1f}/100</span> &nbsp;·&nbsp; <b>Tier:</b> {escape(g_tier)} &nbsp;·&nbsp; <b>DD:</b> {escape(dd_st)}</div></div>""", unsafe_allow_html=True)
            gov_rows.append({"Supplier": supplier_display_name(sup), "Score": gov_sc, "Tier": g_tier, "Due Diligence": dd_st, "Cadence": qbr, "Open Actions": ca, "Dependency": dep, **gov_scores})
    st.markdown("<div class='v46-plain-title'>Governance summary</div>", unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(gov_rows), use_container_width=True, hide_index=True)

# ── TAB 4: Custom Points ──────────────────────────────────────────────────────
with input_tabs[3]:
    render_section("Custom Analysis Points", "Tooling, credits, productivity commitments, tax benefits, exclusivity premiums or any buyer-specific lever.", "#f59e0b")
    cf_count = st.number_input("Number of custom points", min_value=0, max_value=12, value=0, step=1, key="cf_count")
    custom_cost_adj: Dict = {c: {s: 0.0 for s in SUPPLIERS} for c in COUNTRIES}
    custom_risk_adj: Dict[str, float] = {s: 0.0 for s in SUPPLIERS}
    cf_rows = []
    for fi in range(int(cf_count)):
        with st.expander(f"➕ Custom point {fi+1}", expanded=(fi==0)):
            st.markdown("<div class='v46-gov-card'>", unsafe_allow_html=True)
            h1_, h2_, h3_, h4_ = st.columns([1.3, .9, .85, .75])
            with h1_: fn_ = st.text_input("Name", value=f"Custom point {fi+1}", key=f"cf__{fi}__name")
            with h2_: ft_ = st.selectbox("Type", options=CUSTOM_FACTOR_TYPES, index=0, key=f"cf__{fi}__type")
            with h3_: cs_ = st.selectbox("Country scope", options=CUSTOM_FACTOR_COUNTRIES, index=0, key=f"cf__{fi}__country")
            with h4_: wt_ = st.number_input("Weight", min_value=0.0, value=1.0, step=0.1, format="%.2f", key=f"cf__{fi}__weight")
            vc_ = st.columns(min(5, len(SUPPLIERS)))
            for si_, sup_ in enumerate(SUPPLIERS):
                with vc_[si_ % len(vc_)]:
                    rv_ = st.number_input(supplier_short_name(sup_), value=0.0, step=10_000.0 if "Cost" in ft_ or "Productivity" in ft_ else 0.1, format="%.2f", key=f"cf__{fi}__{sup_}__val")
                sv_ = float(rv_) * float(wt_)
                tcs_ = COUNTRIES if cs_ == "All countries" else [cs_]
                if ft_ == "Cost add-on":
                    for c in tcs_: custom_cost_adj[c][sup_] += sv_
                elif ft_ in {"Cost reduction / saving", "Productivity gain"}:
                    for c in tcs_: custom_cost_adj[c][sup_] -= sv_
                elif ft_ == "Risk increase": custom_risk_adj[sup_] += safe_divide(sv_, 100.0)
                elif ft_ == "Risk reduction": custom_risk_adj[sup_] -= safe_divide(sv_, 100.0)
                cf_rows.append({"Analysis Point": fn_, "Type": ft_, "Country": cs_, "Supplier": supplier_display_name(sup_), "Value": sv_})
            st.markdown("</div>", unsafe_allow_html=True)
    for c in COUNTRIES:
        for s in SUPPLIERS:
            adj = float(custom_cost_adj[c][s])
            if abs(adj) > 1e-9:
                proposal_inputs[c][s]["spend"] = max(float(proposal_inputs[c][s]["spend"]) + adj, 0.0)
                proposal_inputs[c][s]["custom_cost_adjustment"] = adj
            else:
                proposal_inputs[c][s]["custom_cost_adjustment"] = 0.0
    if cf_rows:
        st.markdown("<div class='v46-plain-title'>Custom analysis audit</div>", unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(cf_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("No custom points. Standard proposal, risk and TCO logic will be used.")

# ── TAB 5: Risk & Constraints ─────────────────────────────────────────────────
with input_tabs[4]:
    render_section("Supplier Risk & Strategic Constraints", "Kraljic minimums, capacity ceilings and multi-dimensional risk scores → optimization engine.", "#ef4444")
    rw_cols = st.columns(len(DEFAULT_RISK_WEIGHTS))
    risk_weights: Dict[str, float] = {}
    for idx_, dim_ in enumerate(DEFAULT_RISK_WEIGHTS):
        with rw_cols[idx_]: risk_weights[dim_] = st.number_input(f"{dim_} weight", min_value=0.0, value=DEFAULT_RISK_WEIGHTS[dim_], step=1.0, key=f"rw__{dim_}")
    risk_inputs: Dict = {s: {} for s in SUPPLIERS}
    for sup in SUPPLIERS:
        with st.expander(supplier_display_name(sup), expanded=(sup=="ChemPrime")):
            c1_, c2_, c3_, c4_ = st.columns(4)
            with c1_: st.checkbox("Approved", value=DEFAULT_APPROVED[sup], key=approved_key(sup)); st.checkbox("Kraljic min required", value=DEFAULT_KRALJIC_REQUIRED[sup], key=kraljic_key(sup))
            with c2_: st.number_input("Min share %", 0.0, 100.0, DEFAULT_MIN_SHARE[sup], 1.0, key=min_key(sup))
            with c3_: st.number_input("Max share %", 0.0, 100.0, DEFAULT_MAX_SHARE[sup], 1.0, key=max_key(sup))
            with c4_: st.caption("1 = low risk · 5 = high risk")
            gov_risk = governance_risk_defaults(supplier_management_inputs, sup)
            cust_adj = float(custom_risk_adj.get(sup, 0.0))
            rc_ = st.columns(len(DEFAULT_RISK_WEIGHTS))
            for idx_, dim_ in enumerate(DEFAULT_RISK_WEIGHTS):
                with rc_[idx_]:
                    dfr = blend_risk_default(DEFAULT_RISK[sup][dim_], gov_risk.get(dim_, DEFAULT_RISK[sup][dim_]), cust_adj)
                    risk_inputs[sup][dim_] = st.slider(dim_, 1.0, 5.0, dfr, 0.1, key=f"risk__{sup}__{dim_}")
            st.caption(f"Gov score: {supplier_management_inputs.get(sup,{}).get('Governance score',0):.1f}/100 | Custom adj: {cust_adj:+.2f}")

# ── TAB 6: Share & Optimization ───────────────────────────────────────────────
with input_tabs[5]:
    render_section("Share Projection & Cost Optimization", "Slider scenarios + automatic LP optimization respecting Kraljic constraints.", "#10b981")
    st.info("Current baseline uses each country's current payment term only. Proposals use each supplier's proposed term.")
    share_mode = st.radio("Share control", options=["Automatic", "Manual"], horizontal=True, key="share_mode")
    mins_now = get_min_shares(); maxs_now = get_max_shares(); issues_now = constraint_issues(mins_now, maxs_now)
    invalid_c = bool(issues_now)
    if invalid_c:
        st.error("Constraint setup is infeasible.")
        for iss in issues_now: st.warning(iss)
    sup_risk_preview = supplier_risk_scores(risk_inputs, risk_weights)

    st.markdown("#### ⚡ Cost Optimization")
    oc1_, oc2_ = st.columns([.28, .72])
    with oc1_:
        if st.button("Run Optimization", type="primary", use_container_width=True, key="opt_top"):
            if invalid_c:
                st.error("Fix constraints first.")
            else:
                try:
                    os_, ord_, om_ = optimize_allocations(country_inputs, proposal_inputs, sup_risk_preview, rate_method, risk_threshold, int(opt_step))
                    st.session_state["pending_optimized_shares"] = os_
                    st.session_state["optimization_rationale_df"] = ord_
                    st.session_state["optimization_message"] = om_
                    st.rerun()
                except Exception as exc: st.error(f"Optimization failed: {exc}")
    with oc2_:
        st.markdown('<div class="v46-insight"><b>Objective:</b> minimize economic all-in cost, then weighted risk. Respects Kraljic minimums, supplier max/capacity and approved flags. Sliders update automatically after run.</div>', unsafe_allow_html=True)
    if st.session_state.get("last_optimization_applied"):
        st.success(st.session_state.get("optimization_message", "Optimization applied.")); st.session_state["last_optimization_applied"] = False

    all_shares: Dict = {}
    for country in COUNTRIES:
        clamp_shares_to_bounds(country)
        with st.expander(f"{country} share projection", expanded=(country==PRIMARY_COUNTRY)):
            if share_mode=="Automatic": st.caption("Auto-rebalance: changing one supplier rebalances others proportionally.")
            else: st.caption("Manual: sliders normalized if total ≠ 100%.")
            s_cols = st.columns(min(4, max(1, len(SUPPLIERS))))
            raw_sh = {}
            for idx_, sup_ in enumerate(SUPPLIERS):
                with s_cols[idx_ % len(s_cols)]:
                    mn_ = float(mins_now[sup_]); mx_ = float(maxs_now[sup_])
                    k_ = share_key(country, sup_)
                    cv_ = float(st.session_state.get(k_, DEFAULT_SHARES[country][sup_]))
                    if mx_ < mn_ - 1e-9:
                        raw_sh[sup_] = mn_
                        st.warning(f"{supplier_short_name(sup_)}: floor {mn_:.0f}% > cap {mx_:.0f}%")
                        st.slider(supplier_short_name(sup_), 0.0, 100.0, min(mn_,100.0), 1.0, key=f"{k_}__inf", disabled=True)
                    elif mx_ <= mn_ + 1e-9:
                        raw_sh[sup_] = float(mn_); st.session_state[k_] = float(mn_)
                        st.slider(supplier_short_name(sup_), 0.0, 100.0, float(mn_), 1.0, key=f"{k_}__lock", disabled=True)
                        st.caption(f"Locked at {mn_:.0f}%")
                    else:
                        cv_ = max(mn_, min(mx_, cv_)); st.session_state[k_] = cv_
                        kwargs_ = {"on_change": rebalance_after_slider_change, "args": (country, sup_)} if share_mode=="Automatic" and not invalid_c else {}
                        raw_sh[sup_] = st.slider(supplier_short_name(sup_), mn_, mx_, cv_, 1.0, key=k_, **kwargs_)
                        if mins_now[sup_] > 0: st.caption(f"Kraljic floor: {mins_now[sup_]:.0f}%")
            if share_mode=="Manual":
                eff_ = allocate_with_bounds(raw_sh, mins_now, maxs_now, 100.0)
            else:
                tot_raw = sum(float(st.session_state.get(share_key(country, s), raw_sh.get(s,0.0))) for s in SUPPLIERS)
                eff_ = allocate_with_bounds(raw_sh, mins_now, maxs_now, 100.0) if abs(tot_raw - 100.0) > 1e-6 else {s: float(st.session_state.get(share_key(country, s), raw_sh.get(s,0.0))) for s in SUPPLIERS}
            all_shares[country] = eff_
            st.dataframe(pd.DataFrame([{"Supplier": supplier_short_name(s), "Effective Share %": eff_[s]} for s in SUPPLIERS]), use_container_width=True)

    _, _, _, total_preview = calc_scenario(all_shares, country_inputs, proposal_inputs, sup_risk_preview, rate_method)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN CALCULATION
# ─────────────────────────────────────────────────────────────────────────────

supplier_risk = supplier_risk_scores(risk_inputs, risk_weights)
final_shares: Dict = {}
for c in COUNTRIES:
    raw_ = {s: float(st.session_state.get(share_key(c, s), DEFAULT_SHARES[c][s])) for s in SUPPLIERS}
    final_shares[c] = allocate_with_bounds(raw_, get_min_shares(), get_max_shares(), 100.0)
country_df, group_df, supplier_df, total = calc_scenario(final_shares, country_inputs, proposal_inputs, supplier_risk, rate_method)


def build_supplier_focus_df(sdf: pd.DataFrame, mode: str) -> pd.DataFrame:
    if sdf.empty: return pd.DataFrame()
    agg = {"Economic Total": "sum", "Allocated Spend": "sum", "Risk Score": "mean"}
    for col in ["Performance-Adjusted Cost", "Productivity Gain", "Should-Cost Gap", "Overtime Hours / Month", "Productivity ROI %", "SLA Gap", "Total Contract Value"]:
        if col in sdf.columns: agg[col] = "mean" if "Hours" in col else "sum"
    if "Performance Score" in sdf.columns: agg["Performance Score"] = "mean"
    focus = sdf.groupby(["Supplier ID", "Supplier"], as_index=False).agg(agg)
    if mode == "Indirect / Services" and "Performance-Adjusted Cost" in focus.columns:
        focus["Executive Focus Metric"] = focus["Performance-Adjusted Cost"].fillna(focus["Economic Total"])
    else:
        focus["Executive Focus Metric"] = focus["Economic Total"]
    focus = focus.sort_values(["Executive Focus Metric", "Risk Score"], ascending=[True, True]).reset_index(drop=True)
    focus["Rank"] = range(1, len(focus) + 1)
    return focus

supplier_focus_df = build_supplier_focus_df(supplier_df, analysis_mode)
focused_supplier_count = int(st.session_state.get("focused_supplier_count", min(4, len(SUPPLIERS))))
top_focus_ids = supplier_focus_df.head(focused_supplier_count)["Supplier ID"].tolist() if not supplier_focus_df.empty else SUPPLIERS[:focused_supplier_count]
primary_row = group_df[group_df["Group"] == PRIMARY_COUNTRY].iloc[0]
secondary_row = group_df[group_df["Group"] == SECONDARY_GROUP].iloc[0]
gross_delta = total["Gross All-In Delta"]
wc_delta = total["Treasury Return Offset Delta"]
moq_benefit = total.get("MOQ WC Benefit", 0.0)
moq_drag_delta = total.get("MOQ WC Drag Delta", 0.0)
total_saving_wc = gross_delta + wc_delta - moq_benefit
final_econ = total["Economic All-In Delta"]



# ─────────────────────────────────────────────────────────────────────────────
# TAB 7: EXECUTIVE DASH VIEW
# ─────────────────────────────────────────────────────────────────────────────

def coord_unit(unit):
    if unit in LOCALITY_COORDS: return LOCALITY_COORDS[unit]
    if unit in COUNTRY_GEO_POINTS: return COUNTRY_GEO_POINTS[unit]
    base = get_country_geo(ANCHOR_COUNTRY); dl, dn = _stable_offset(unit)
    return {"lat": base["lat"]+dl, "lon": base["lon"]+dn}

with input_tabs[6]:
    render_section("Executive Dash View", "Visual cockpit — filter, map, rank and compare across markets and suppliers.", "#6366f1")

    unit_lbl = "Country" if VIEW_SCOPE == "Global View" else f"{ANCHOR_COUNTRY} locality"
    dsdf = supplier_df.copy() if not supplier_df.empty else pd.DataFrame(columns=["Country","Supplier","Allocated Spend"])
    dcdf = country_df.copy() if not country_df.empty else pd.DataFrame(columns=["Country","New Spend","Weighted Risk","Economic All-In Delta"])

    fl_cols = st.columns(5)
    sup_opts = ["All"] + sorted(dsdf["Supplier"].dropna().astype(str).unique().tolist()) if not dsdf.empty else ["All"]
    loc_opts_d = ["All"] + COUNTRIES
    with fl_cols[0]: sf_ = st.selectbox("Supplier", sup_opts, key="dash_sup_f")
    with fl_cols[1]: lf_ = st.selectbox(unit_lbl, loc_opts_d, key="dash_loc_f")
    with fl_cols[2]: metric_ = st.selectbox("Map metric", ["Spend","Saving","Risk","Suppliers"], key="dash_metric")
    with fl_cols[3]: pass
    with fl_cols[4]: pass

    fsd = dsdf.copy()
    if not fsd.empty:
        if sf_ != "All": fsd = fsd[fsd["Supplier"]==sf_]
        if lf_ != "All": fsd = fsd[fsd["Country"]==lf_]
    f_units = sorted(fsd["Country"].unique().tolist()) if not fsd.empty else COUNTRIES
    if lf_ != "All": f_units = [lf_]
    fcd = dcdf[dcdf["Country"].isin(f_units)].copy() if not dcdf.empty else pd.DataFrame()

    kpi_cols_ = st.columns(5)
    with kpi_cols_[0]: render_kpi("Current Spend", fmt_money(total["Current Spend"], currency_symbol, compact=True), "Baseline", "neutral")
    with kpi_cols_[1]: render_kpi("New Spend", fmt_money(total["New Spend"], currency_symbol, compact=True), "Proposals × shares", delta_tone(total["Spend Delta"]))
    with kpi_cols_[2]: render_kpi("Economic All-In", fmt_money(final_econ, currency_symbol, compact=True, signed=True), "Spend + finance + WC + inventory", delta_tone(final_econ))
    with kpi_cols_[3]: render_kpi("Working Capital", fmt_money(wc_delta, currency_symbol, compact=True, signed=True), "Treasury return delta", delta_tone(wc_delta))
    with kpi_cols_[4]: render_kpi("Weighted Risk", f"{total.get('Weighted Risk',0):.2f}/5", "Lower is better", risk_tone(total.get("Weighted Risk",0)))

    top_l, top_r = st.columns([1.2, 0.8], gap="large")
    with top_l:
        st.markdown("<div class='v46-chart'><h4>Cost by market</h4>", unsafe_allow_html=True)
        if PLOTLY_AVAILABLE and not fcd.empty:
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(name="Current", x=fcd["Country"], y=fcd["Current Spend"], marker_color="#334155", text=fcd["Current Spend"].map(lambda v: fmt_money(v, currency_symbol, compact=True)), textposition="outside"))
            fig_bar.add_trace(go.Bar(name="New", x=fcd["Country"], y=fcd["New Spend"], marker_color="#3b82f6", text=fcd["New Spend"].map(lambda v: fmt_money(v, currency_symbol, compact=True)), textposition="outside"))
            fig_bar.update_layout(title="Current vs New Spend by Market", barmode="group")
            st.plotly_chart(apply_chart_theme(fig_bar, 320), use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)
    with top_r:
        st.markdown("<div class='v46-chart'><h4>Geographic heat map</h4>", unsafe_allow_html=True)
        if PLOTLY_AVAILABLE and COUNTRIES:
            map_rows = []
            for u in COUNTRIES:
                loc_ = coord_unit(u)
                cr = dcdf[dcdf["Country"]==u] if not dcdf.empty else pd.DataFrame()
                val_ = float(cr["New Spend"].sum()) if metric_=="Spend" and not cr.empty else max(-float(cr["Economic All-In Delta"].sum()),0.0) if metric_=="Saving" and not cr.empty else float(cr["Weighted Risk"].mean()) if metric_=="Risk" and not cr.empty else float(dsdf[dsdf["Country"]==u]["Supplier ID"].nunique()) if not dsdf.empty else 0.0
                map_rows.append({"loc": u, "lat": float(loc_["lat"]), "lon": float(loc_["lon"]), "val": val_})
            mdf = pd.DataFrame(map_rows)
            sz_norm = mdf["val"].abs() / max(float(mdf["val"].abs().max()), 1.0)
            fig_map = go.Figure(go.Scattergeo(lat=mdf["lat"], lon=mdf["lon"], text=mdf["loc"], mode="markers+text", textposition="top center", marker=dict(size=(20+sz_norm*30).clip(16,48), color=mdf["val"], colorscale="Blues" if metric_!="Risk" else "RdYlGn_r", showscale=True, opacity=0.85, line=dict(width=1,color="rgba(255,255,255,.3)")), hovertemplate="%{text}<br>" + metric_ + ": %{marker.color:,.2f}<extra></extra>"))
            ps_ = 2.0 if VIEW_SCOPE=="Global View" else 4.0
            fig_map.update_geos(visible=True, showcountries=True, showland=True, landcolor="#1e293b", countrycolor="#334155", coastlinecolor="#475569", bgcolor="rgba(15,23,42,0)", projection_type="mercator", projection_scale=ps_, fitbounds="locations" if len(mdf)>1 else False)
            fig_map.update_layout(title=f"{metric_} heat map", height=320, margin=dict(l=8,r=8,t=44,b=8), paper_bgcolor="rgba(15,23,42,0)", plot_bgcolor="rgba(15,23,42,0)")
            st.plotly_chart(fig_map, use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)

    bot_l, bot_r = st.columns([0.72, 1.28], gap="large")
    with bot_l:
        st.markdown("<div class='v46-chart'><h4>Spend by supplier</h4>", unsafe_allow_html=True)
        if PLOTLY_AVAILABLE and not fsd.empty:
            srank = fsd.groupby("Supplier", as_index=False)["Allocated Spend"].sum().sort_values("Allocated Spend", ascending=False).head(8)
            fig_hb = go.Figure(go.Bar(x=srank["Allocated Spend"], y=srank["Supplier"], orientation="h", marker_color="#6366f1", text=srank["Allocated Spend"].map(lambda v: fmt_money(v, currency_symbol, compact=True)), textposition="auto"))
            fig_hb.update_layout(title="Allocated spend by supplier", height=350)
            st.plotly_chart(apply_chart_theme(fig_hb, 350), use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)
    with bot_r:
        st.markdown("<div class='v46-chart'><h4>Cost × Risk frontier</h4>", unsafe_allow_html=True)
        if PLOTLY_AVAILABLE:
            fr_rows = [{"Scenario": "Current", "Risk": total["Weighted Risk"], "Econ Delta": total["Economic All-In Delta"]}]
            try:
                opt_s, _, _ = optimize_allocations(country_inputs, proposal_inputs, supplier_risk, rate_method, risk_threshold, int(opt_step))
                _, _, _, opt_t = calc_scenario(opt_s, country_inputs, proposal_inputs, supplier_risk, rate_method)
                fr_rows.append({"Scenario": "Optimized", "Risk": opt_t["Weighted Risk"], "Econ Delta": opt_t["Economic All-In Delta"]})
            except: pass
            frf = pd.DataFrame(fr_rows)
            col_map = {"Current": "#64748b", "Optimized": "#10b981", "Lowest risk": "#f59e0b"}
            fig_fr = go.Figure()
            for _, rw in frf.iterrows():
                fig_fr.add_trace(go.Scatter(x=[rw["Risk"]], y=[rw["Econ Delta"]], mode="markers+text", text=[rw["Scenario"]], textposition="top center", marker=dict(size=16, color=col_map.get(rw["Scenario"], "#3b82f6")), showlegend=True, name=rw["Scenario"], hovertemplate=f"{rw['Scenario']}<br>Risk: %{{x:.2f}}/5<br>Delta: {currency_symbol} %{{y:,.0f}}<extra></extra>"))
            fig_fr.add_hline(y=0, line_dash="dash", line_color="rgba(148,163,184,.3)")
            fig_fr.update_layout(title="Cost × Risk Decision Map", xaxis_title="Weighted risk score", yaxis_title=f"Economic delta ({currency_symbol})", height=350)
            st.plotly_chart(apply_chart_theme(fig_fr, 350), use_container_width=True, config={"displayModeBar": False})
        st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# OPTIMIZATION (always-visible panel)
# ─────────────────────────────────────────────────────────────────────────────

render_section("Cost Optimization", "Run optimizer at any time — respects all constraints and updates share sliders automatically.", "#10b981")
opt_iss = constraint_issues(get_min_shares(), get_max_shares()); opt_blocked = bool(opt_iss)
for iss in opt_iss: st.error(f"Optimization blocked: {iss}")
ocm1, ocm2 = st.columns([.24, .76])
with ocm1:
    run_opt = st.button("⚡ Run Optimization", type="primary", use_container_width=True, key="opt_main", disabled=opt_blocked)
with ocm2:
    st.markdown('<div class="v46-insight"><b>Logic:</b> Minimizes economic all-in delta (spend + payment-term finance cost − treasury return + inventory carry + MOQ drag). In Services mode, proposal spend includes service TCO, productivity gains, SLA risk cost and leakage.</div>', unsafe_allow_html=True)

if run_opt:
    try:
        os_, ord_, om_ = optimize_allocations(country_inputs, proposal_inputs, supplier_risk, rate_method, risk_threshold, int(opt_step))
        st.session_state["pending_optimized_shares"] = os_
        st.session_state["optimization_rationale_df"] = ord_
        st.session_state["optimization_message"] = om_
        st.rerun()
    except Exception as exc: st.error(f"Optimization failed: {exc}")
if st.session_state.get("optimization_message"):
    st.success(st.session_state.get("optimization_message"))

st.markdown("<div style='height:32px'></div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# DECISION STACKS
# ─────────────────────────────────────────────────────────────────────────────

render_section("Decision Stacks", "Expand the stacks needed for the meeting. Everything is collapsed by default for a clean screen.", "#6366f1")

@contextmanager
def stack(title, subtitle, icon, color, tag, expanded=False):
    label = f"{icon}  {title}  ·  {tag}  —  {subtitle}"
    with st.expander(label, expanded=expanded):
        yield

# ── Top supplier focus ────────────────────────────────────────────────────────
if not supplier_focus_df.empty:
    with stack("Top Supplier Focus", f"Top {focused_supplier_count} of {len(SUPPLIERS)} suppliers by executive lens.", "🎛️", "#3b82f6", "Supplier focus"):
        fd = supplier_focus_df.head(focused_supplier_count).copy()
        show_cols = ["Rank","Supplier","Executive Focus Metric","Economic Total","Risk Score"]
        if analysis_mode=="Indirect / Services":
            for ec in ["Performance Score","Performance-Adjusted Cost","Productivity Gain","Should-Cost Gap","Productivity ROI %","SLA Gap"]:
                if ec in fd.columns: show_cols.append(ec)
        show_cols = [c for c in show_cols if c in fd.columns]
        fd = fd[show_cols]
        for mc in ["Executive Focus Metric","Economic Total","Performance-Adjusted Cost","Productivity Gain","Should-Cost Gap"]:
            if mc in fd.columns: fd[mc] = fd[mc].map(lambda x: fmt_money(x, currency_symbol, compact=True, signed=(mc=="Should-Cost Gap")))
        if "Risk Score" in fd.columns: fd["Risk Score"] = fd["Risk Score"].map(lambda x: f"{x:.2f}")
        if "Performance Score" in fd.columns: fd["Performance Score"] = fd["Performance Score"].map(lambda x: "" if pd.isna(x) else f"{x:.1f}/100")
        if "Productivity ROI %" in fd.columns: fd["Productivity ROI %"] = fd["Productivity ROI %"].map(lambda x: "" if pd.isna(x) else f"{x:.0f}%")
        if "SLA Gap" in fd.columns: fd["SLA Gap"] = fd["SLA Gap"].map(lambda x: "" if pd.isna(x) else f"{x:.1f}pp")
        st.dataframe(fd, use_container_width=True, hide_index=True)

# ── Total project saving ────────────────────────────────────────────────────
with stack("Total Project Saving", "Gross saving, working capital gain and economic all-in.", "🏁", "#10b981" if final_econ<=0 else "#ef4444", "Final result", expanded=True):
    c5 = st.columns(5)
    with c5[0]: render_kpi("Gross Total Saving / Impact", fmt_money(gross_delta, currency_symbol, compact=True, signed=True), "New total spend − current total spend", delta_tone(gross_delta))
    with c5[1]: render_kpi("Working Capital Gain", fmt_money(wc_delta, currency_symbol, compact=True, signed=True), "Current treasury return − new treasury return", delta_tone(wc_delta))
    with c5[2]: render_kpi("MOQ WC Benefit", fmt_money(moq_benefit, currency_symbol, compact=True, signed=True), "MOQ cash drag reduction", benefit_tone(moq_benefit))
    with c5[3]: render_kpi("Total Saving + WC", fmt_money(total_saving_wc, currency_symbol, compact=True, signed=True), "Gross + treasury offset + MOQ release", delta_tone(total_saving_wc))
    with c5[4]: render_kpi("Final Economic All-In", fmt_money(final_econ, currency_symbol, compact=True, signed=True), "Finance + treasury + inventory + MOQ drag", delta_tone(final_econ))
    cc = st.columns(2)
    with cc[0]: render_kpi(f"{PRIMARY_COUNTRY} contribution", fmt_money(primary_row["Economic All-In Delta"], currency_symbol, compact=True, signed=True), f"{PRIMARY_COUNTRY} economic delta", delta_tone(primary_row["Economic All-In Delta"]))
    with cc[1]: render_kpi(f"{SECONDARY_GROUP} contribution", fmt_money(secondary_row["Economic All-In Delta"], currency_symbol, compact=True, signed=True), f"{len(LATAM_COUNTRIES)} other markets", delta_tone(secondary_row["Economic All-In Delta"]))

# ── AI Copilot ────────────────────────────────────────────────────────────────
with stack("AI Executive Copilot", "Concise decision-oriented brief from the current scenario.", "🤖", "#6366f1", "AI brief"):
    ai1, ai2 = st.columns([.30, .70])
    with ai1:
        if st.button("Generate Brief", type="primary", use_container_width=True, key="gen_brief"):
            st.session_state["ai_payload"] = build_ai_payload(analysis_mode=analysis_mode, total=total, group_df=group_df, supplier_focus_df=supplier_focus_df, focused_supplier_count=focused_supplier_count, currency=currency_symbol)
            st.session_state["ai_brief"] = generate_local_brief(analysis_mode=analysis_mode, total=total, group_df=group_df, supplier_focus_df=supplier_focus_df, focused_supplier_count=focused_supplier_count, currency=currency_symbol)
        st.caption("Local deterministic brief. Connect Anthropic API key for live AI analysis.")
    with ai2:
        st.markdown('<div class="v46-insight"><b>How it works:</b> Reads the full scenario — suppliers, economics, risk, SLA, productivity — and produces an Amazon-caliber concise recommendation with negotiation levers and next actions.</div>', unsafe_allow_html=True)
    if st.session_state.get("ai_brief"):
        st.markdown(st.session_state["ai_brief"], unsafe_allow_html=True)
        with st.expander("Copy prompt for external AI", expanded=False):
            st.text_area("Prompt payload", value=st.session_state.get("ai_payload",""), height=200, key="ai_payload_ta")

# ── Cost Stack ───────────────────────────────────────────────────────────────
with stack("Total Cost Stack", "Commercial spend and gross payment-term cost comparison.", "🧾", "#3b82f6", "Cost baseline"):
    c6 = st.columns(6)
    with c6[0]: render_kpi("Current Spend", fmt_money(total["Current Spend"], currency_symbol, compact=True), "Without financial cost", "neutral")
    with c6[1]: render_kpi("New Spend", fmt_money(total["New Spend"], currency_symbol, compact=True), "Proposals × shares", "neutral")
    with c6[2]: render_kpi("Current Fin. Cost", fmt_money(total["Current Financial Cost"], currency_symbol, compact=True), "Current spend × current term rate", "neutral")
    with c6[3]: render_kpi("New Fin. Cost", fmt_money(total["New Financial Cost"], currency_symbol, compact=True), "New spend × proposed term rates", "neutral")
    with c6[4]: render_kpi("Current Total", fmt_money(total["Current Total Spend"], currency_symbol, compact=True), "Spend + financial cost", "neutral")
    with c6[5]: render_kpi("New Total", fmt_money(total["New Total Spend"], currency_symbol, compact=True), "Spend + financial cost", "neutral")

# ── Working capital carry view ────────────────────────────────────────────────
with stack("Working Capital Carry", "Treasury return and net financial effect from payment-term differences.", "🏦", "#10b981", "Cash timing"):
    wc6 = st.columns(6)
    with wc6[0]: render_kpi("Current Treasury Return", fmt_money(total["Current Capital Gain"], currency_symbol, compact=True), "Capital return over current terms", "good")
    with wc6[1]: render_kpi("New Treasury Return", fmt_money(total["New Capital Gain"], currency_symbol, compact=True), "Capital return over proposed terms", "good")
    with wc6[2]: render_kpi("Current Net Financial", fmt_money(total["Current Net Financial Effect"], currency_symbol, compact=True, signed=True), "Financial cost − treasury return", delta_tone(total["Current Net Financial Effect"]))
    with wc6[3]: render_kpi("New Net Financial", fmt_money(total["New Net Financial Effect"], currency_symbol, compact=True, signed=True), "New financial cost − treasury return", delta_tone(total["New Net Financial Effect"]))
    with wc6[4]: render_kpi("Net Financial Delta", fmt_money(total["Net Financial Delta"], currency_symbol, compact=True, signed=True), "New − current net financial effect", delta_tone(total["Net Financial Delta"]))
    with wc6[5]: render_kpi("MOQ WC Benefit", fmt_money(moq_benefit, currency_symbol, compact=True, signed=True), "Lower MOQ cash drag", benefit_tone(moq_benefit))

# ── Total decomposition ───────────────────────────────────────────────────────
with stack("Total Decomposition", "Decision-ready breakdown of spend, finance, inventory and risk.", "🧩", "#8b5cf6", "Decision view"):
    c7 = st.columns(7)
    with c7[0]: render_kpi("Spend Delta", fmt_money(total["Spend Delta"], currency_symbol, compact=True, signed=True), "New − current spend", delta_tone(total["Spend Delta"]))
    with c7[1]: render_kpi("Gross Financial Delta", fmt_money(total["Financial Delta"], currency_symbol, compact=True, signed=True), "New − current gross fin. cost", delta_tone(total["Financial Delta"]))
    with c7[2]: render_kpi("Treasury Offset", fmt_money(total["Treasury Return Offset Delta"], currency_symbol, compact=True, signed=True), "Current − new treasury return", delta_tone(total["Treasury Return Offset Delta"]))
    with c7[3]: render_kpi("Net Financial Delta", fmt_money(total["Net Financial Delta"], currency_symbol, compact=True, signed=True), "Gross fin. + treasury offset", delta_tone(total["Net Financial Delta"]))
    with c7[4]: render_kpi("MOQ WC Drag Delta", fmt_money(moq_drag_delta, currency_symbol, compact=True, signed=True), "New − current MOQ drag", delta_tone(moq_drag_delta))
    with c7[5]: render_kpi("Economic All-In", fmt_money(total["Economic All-In Delta"], currency_symbol, compact=True, signed=True), "Spend + net fin. + inventory + MOQ", delta_tone(final_econ))
    with c7[6]: render_kpi("Weighted Risk", f"{total['Weighted Risk']:.2f}/5", "Lower is better", risk_tone(total["Weighted Risk"]))

# ── Anchor market ────────────────────────────────────────────────────────────
with stack(f"{PRIMARY_COUNTRY} Result", f"Detailed P&L for anchor market {PRIMARY_COUNTRY}.", "📍", "#06b6d4", "Anchor market"):
    c7a = st.columns(7)
    with c7a[0]: render_kpi("Current Avg Term", f"{primary_row['Current Avg Payment Days']:.0f} dd", "Baseline", "neutral")
    with c7a[1]: render_kpi("New Avg Term", f"{primary_row['New Avg Payment Days']:.0f} dd", "Share-weighted", "neutral")
    with c7a[2]: render_kpi("Spend Delta", fmt_money(primary_row["Spend Delta"], currency_symbol, compact=True, signed=True), f"{PRIMARY_COUNTRY}", delta_tone(primary_row["Spend Delta"]))
    with c7a[3]: render_kpi("Gross Fin. Delta", fmt_money(primary_row["Financial Delta"], currency_symbol, compact=True, signed=True), f"{PRIMARY_COUNTRY}", delta_tone(primary_row["Financial Delta"]))
    with c7a[4]: render_kpi("Treasury Offset", fmt_money(primary_row["Treasury Return Offset Delta"], currency_symbol, compact=True, signed=True), f"{PRIMARY_COUNTRY}", delta_tone(primary_row["Treasury Return Offset Delta"]))
    with c7a[5]: render_kpi("Net Fin. Delta", fmt_money(primary_row["Net Financial Delta"], currency_symbol, compact=True, signed=True), f"{PRIMARY_COUNTRY}", delta_tone(primary_row["Net Financial Delta"]))
    with c7a[6]: render_kpi("Economic All-In", fmt_money(primary_row["Economic All-In Delta"], currency_symbol, compact=True, signed=True), f"{PRIMARY_COUNTRY}", delta_tone(primary_row["Economic All-In Delta"]))

# ── Other markets ────────────────────────────────────────────────────────────
with stack(f"{SECONDARY_GROUP} Result", f"Consolidated view for {len(LATAM_COUNTRIES)} other selected markets.", "🌎", "#ec4899", "Regional view"):
    c7b = st.columns(7)
    with c7b[0]: render_kpi("Current Avg Term", f"{secondary_row['Current Avg Payment Days']:.0f} dd", "Baseline", "neutral")
    with c7b[1]: render_kpi("New Avg Term", f"{secondary_row['New Avg Payment Days']:.0f} dd", "Share-weighted", "neutral")
    with c7b[2]: render_kpi("Spend Delta", fmt_money(secondary_row["Spend Delta"], currency_symbol, compact=True, signed=True), SECONDARY_GROUP, delta_tone(secondary_row["Spend Delta"]))
    with c7b[3]: render_kpi("Gross Fin. Delta", fmt_money(secondary_row["Financial Delta"], currency_symbol, compact=True, signed=True), SECONDARY_GROUP, delta_tone(secondary_row["Financial Delta"]))
    with c7b[4]: render_kpi("Treasury Offset", fmt_money(secondary_row["Treasury Return Offset Delta"], currency_symbol, compact=True, signed=True), SECONDARY_GROUP, delta_tone(secondary_row["Treasury Return Offset Delta"]))
    with c7b[5]: render_kpi("Net Fin. Delta", fmt_money(secondary_row["Net Financial Delta"], currency_symbol, compact=True, signed=True), SECONDARY_GROUP, delta_tone(secondary_row["Net Financial Delta"]))
    with c7b[6]: render_kpi("Economic All-In", fmt_money(secondary_row["Economic All-In Delta"], currency_symbol, compact=True, signed=True), SECONDARY_GROUP, delta_tone(secondary_row["Economic All-In Delta"]))

# ── Decision recommendation ────────────────────────────────────────────────
with stack("Decision Recommendation", "Go / no-go based on the modeled scenario.", "✅", "#22c55e", "Recommendation", expanded=True):
    cls_ = "good" if final_econ <= 0 else "bad"
    title_ = "Scenario is economically attractive — recommend approval" if final_econ <= 0 else "Scenario creates economic cost impact — renegotiate before approval"
    st.markdown(
        f"""<div class="v46-decision {cls_}">
        <div class="v46-decision-title">{'✅' if final_econ<=0 else '⚠'} {title_}</div>
        <div class="v46-decision-body">
        Economic all-in delta: <b>{fmt_money(final_econ, currency_symbol, signed=True)}</b> &nbsp;·&nbsp;
        Commercial spend delta: <b>{fmt_money(total['Spend Delta'], currency_symbol, signed=True)}</b> &nbsp;·&nbsp;
        Weighted risk: <b>{total['Weighted Risk']:.2f}/5</b>.
        {'Use Cost Optimization or adjust supplier mix, payment terms or proposal spend to improve the case.' if final_econ>0 else 'Proceed with final commercial negotiation using the top supplier focus list as the anchor for price, payment terms and productivity commitments.'}
        </div></div>""",
        unsafe_allow_html=True,
    )

# ── Charts ────────────────────────────────────────────────────────────────────
with stack("Charts", "Cost stack, economic waterfall and decision map.", "📈", "#2563eb", "Visual analytics"):
    cc1, cc2 = st.columns([1.2, 1.0], gap="large")
    with cc1:
        st.markdown("<div class='v46-chart'><h4>Total Cost Stack</h4>", unsafe_allow_html=True)
        if PLOTLY_AVAILABLE:
            labels_ = ["Current\nSpend","New\nSpend","Current\nFin. Cost","New\nFin. Cost","Current\nTotal","New\nTotal"]
            values_ = [total["Current Spend"],total["New Spend"],total["Current Financial Cost"],total["New Financial Cost"],total["Current Total Spend"],total["New Total Spend"]]
            colors_ = ["#475569","#3b82f6","#f97316","#fb923c","#0f766e","#1d4ed8"]
            fig_cs = go.Figure(go.Bar(x=labels_, y=values_, marker_color=colors_, text=[fmt_money(v,currency_symbol,compact=True) for v in values_], textposition="outside", hovertemplate="%{x}<br>" + currency_symbol + " %{y:,.2f}<extra></extra>"))
            fig_cs.update_layout(title="Total Cost Stack", yaxis_title=f"({currency_symbol})")
            st.plotly_chart(apply_chart_theme(fig_cs), use_container_width=True, config={"displayModeBar":False})
        st.markdown("</div>", unsafe_allow_html=True)
    with cc2:
        st.markdown("<div class='v46-chart'><h4>Economic Delta Waterfall</h4>", unsafe_allow_html=True)
        if PLOTLY_AVAILABLE:
            wf_names = ["Spend","Net financial","Inventory","MOQ WC","Economic all-in"]
            wf_vals = [total["Spend Delta"],total["Net Financial Delta"],total["Inventory Delta"],moq_drag_delta,final_econ]
            fig_wf = go.Figure(go.Waterfall(orientation="v", measure=["relative","relative","relative","relative","total"], x=wf_names, y=wf_vals, text=[fmt_money(v,currency_symbol,compact=True,signed=True) for v in wf_vals], textposition="outside", connector={"line":{"color":"rgba(148,163,184,.3)","width":2}}, increasing={"marker":{"color":"#ef4444"}}, decreasing={"marker":{"color":"#10b981"}}, totals={"marker":{"color":"#3b82f6"}}, hovertemplate="%{x}<br>" + currency_symbol + " %{y:,.2f}<extra></extra>"))
            fig_wf.add_hline(y=0, line_dash="dash", line_color="rgba(148,163,184,.3)")
            fig_wf.update_layout(title="Economic Delta Waterfall", yaxis_title=f"({currency_symbol})")
            st.plotly_chart(apply_chart_theme(fig_wf), use_container_width=True, config={"displayModeBar":False})
        st.markdown("</div>", unsafe_allow_html=True)

# ── Working capital economic view ──────────────────────────────────────────
if show_adv_econ:
    with stack("Working Capital Economic View", "Treasury return, capital gain and inventory separated.", "💼", "#0f766e", "Economic view"):
        ec5 = st.columns(5)
        with ec5[0]: render_kpi("Current Capital Gain", fmt_money(total["Current Capital Gain"], currency_symbol, compact=True), "Current payment terms", "good")
        with ec5[1]: render_kpi("New Capital Gain", fmt_money(total["New Capital Gain"], currency_symbol, compact=True), f"Avg {total.get('New Avg Return Days',0):.0f}dd", "good")
        with ec5[2]: render_kpi("Inventory Delta", fmt_money(total["Inventory Delta"], currency_symbol, compact=True, signed=True), "New − current inventory carry", delta_tone(total["Inventory Delta"]))
        with ec5[3]: render_kpi("Current Econ. Total", fmt_money(total["Current Economic Total"], currency_symbol, compact=True), "Gross − capital gain + inventory", "neutral")
        with ec5[4]: render_kpi("New Econ. Total", fmt_money(total["New Economic Total"], currency_symbol, compact=True), "Gross − capital gain + inventory", "neutral")
        st.markdown("<div class='v46-plain-title'>Optimization rationale</div>", unsafe_allow_html=True)
        rat_df = st.session_state.get("optimization_rationale_df")
        if isinstance(rat_df, pd.DataFrame) and not rat_df.empty:
            rd_ = rat_df.copy()
            for mc in ["Economic Delta","Gross All-In Delta","Spend Delta"]:
                if mc in rd_.columns: rd_[mc] = rd_[mc].map(lambda x: fmt_money(x, currency_symbol, signed=True))
            st.dataframe(rd_, use_container_width=True)
        else:
            st.info("Run Cost Optimization to generate the rationale table.")

# ── Detailed data ─────────────────────────────────────────────────────────────
with stack("Detailed Data", "Full audit trail for Finance, Procurement and category strategy.", "🧾", "#64748b", "Audit trail"):
    dt_names = ["Country summary","Region summary","Supplier allocation","Risk scores","Governance","Custom analysis"]
    if analysis_mode != "Direct Materials": dt_names.append("Service scorecards")
    dt_tabs = st.tabs(dt_names)
    with dt_tabs[0]:
        dc_ = country_df.copy()
        for mc in [c for c in dc_.columns if any(k in c for k in ["Spend","Cost","Gain","Total","Delta"])]:
            dc_[mc] = dc_[mc].map(lambda x: fmt_money(x, currency_symbol, signed=("Delta" in mc)))
        for mc in ["Weighted Risk","Current Effective Financial Rate","New Avg Financial Rate","Current Effective Treasury Rate","New Avg Treasury Rate"]:
            if mc in dc_: dc_[mc] = dc_[mc].map(fmt_pct if "Rate" in mc else lambda x: f"{x:.2f}")
        st.dataframe(dc_, use_container_width=True)
    with dt_tabs[1]:
        dg_ = group_df.copy()
        for mc in [c for c in dg_.columns if any(k in c for k in ["Spend","Cost","Gain","Total","Delta"])]:
            dg_[mc] = dg_[mc].map(lambda x: fmt_money(x, currency_symbol, signed=("Delta" in mc)))
        st.dataframe(dg_, use_container_width=True)
    with dt_tabs[2]:
        ds_ = supplier_df.copy()
        if top_focus_ids: ds_["Executive Focus"] = ds_["Supplier ID"].isin(top_focus_ids).map({True:"Top focus",False:"Other"})
        for mc in ["Allocated Spend","Supplier Financial Cost","Capital Gain Offset","Inventory Carrying Cost","Economic Total","Proposed Contract Value","Service TCO Before Productivity","Productivity Gain","Expected Risk Cost","Performance-Adjusted Cost","Should-Cost Target","Should-Cost Gap","Open-Cost Total","Unexplained Quote Value","Custom Cost Adjustment","Total Contract Value"]:
            if mc in ds_.columns: ds_[mc] = ds_[mc].map(lambda x: "" if pd.isna(x) else fmt_money(x, currency_symbol, signed=(mc=="Should-Cost Gap")))
        for mc in ["Share %"]:
            if mc in ds_.columns: ds_[mc] = ds_[mc].map(lambda x: f"{x:.1f}%")
        for mc in ["Risk Score"]:
            if mc in ds_.columns: ds_[mc] = ds_[mc].map(lambda x: f"{x:.2f}")
        for mc in ["Performance Score"]:
            if mc in ds_.columns: ds_[mc] = ds_[mc].map(lambda x: "" if pd.isna(x) else f"{x:.1f}/100")
        for mc in ["Productivity ROI %"]:
            if mc in ds_.columns: ds_[mc] = ds_[mc].map(lambda x: "" if pd.isna(x) else f"{x:.0f}%")
        for mc in ["SLA Gap"]:
            if mc in ds_.columns: ds_[mc] = ds_[mc].map(lambda x: "" if pd.isna(x) else f"{x:.1f}pp")
        st.dataframe(ds_, use_container_width=True)
    with dt_tabs[3]:
        st.dataframe(pd.DataFrame([{"Supplier": supplier_display_name(s), "Weighted Risk": supplier_risk[s], **risk_inputs[s]} for s in SUPPLIERS]), use_container_width=True)
    with dt_tabs[4]:
        if gov_rows: st.dataframe(pd.DataFrame(gov_rows), use_container_width=True, hide_index=True)
        else: st.info("No governance data.")
    with dt_tabs[5]:
        if cf_rows: st.dataframe(pd.DataFrame(cf_rows), use_container_width=True, hide_index=True)
        else: st.info("No custom points added.")
    if analysis_mode != "Direct Materials" and len(dt_tabs) > 6:
        with dt_tabs[6]:
            svc_cols = ["Country","Supplier","Service Scope","Pricing Model","Proposed Contract Value","Service TCO Before Productivity","Productivity Gain","Expected Risk Cost","SLA Risk Cost","SLA Attainment","SLA Gap","Performance Score","Performance Tier","Performance-Adjusted Cost","Headcount / FTEs","Price per Person / Month","Hourly Rate","Overtime Hours / Month","Overtime Cost","Should-Cost Target","Should-Cost Gap","Open-Cost Total","Open-Cost Coverage %","Unexplained Quote Value","Productivity ROI %","Payback Months","Total Contract Value","Scope Creep %","Rate Card Gap %","Share %","Allocated Spend"]
            ac_ = [c for c in svc_cols if c in supplier_df.columns]
            svdf_ = supplier_df[ac_].copy()
            for mc in ["Proposed Contract Value","Service TCO Before Productivity","Productivity Gain","Expected Risk Cost","SLA Risk Cost","Performance-Adjusted Cost","Allocated Spend","Should-Cost Target","Should-Cost Gap","Open-Cost Total","Unexplained Quote Value","Total Contract Value"]:
                if mc in svdf_.columns: svdf_[mc] = svdf_[mc].map(lambda x: "" if pd.isna(x) else fmt_money(x, currency_symbol, signed=(mc=="Should-Cost Gap")))
            for mc in ["Performance Score"]:
                if mc in svdf_.columns: svdf_[mc] = svdf_[mc].map(lambda x: "" if pd.isna(x) else f"{x:.1f}/100")
            for mc in ["Scope Creep %","Open-Cost Coverage %"]:
                if mc in svdf_.columns: svdf_[mc] = svdf_[mc].map(lambda x: "" if pd.isna(x) else f"{x*100:.1f}%")
            for mc in ["Rate Card Gap %"]:
                if mc in svdf_.columns: svdf_[mc] = svdf_[mc].map(lambda x: "" if pd.isna(x) else f"{x:.1f}%")
            for mc in ["Share %"]:
                if mc in svdf_.columns: svdf_[mc] = svdf_[mc].map(lambda x: f"{x:.1f}%")
            for mc in ["Productivity ROI %"]:
                if mc in svdf_.columns: svdf_[mc] = svdf_[mc].map(lambda x: "" if pd.isna(x) else f"{x:.0f}%")
            st.dataframe(svdf_, use_container_width=True)

# ── Download ──────────────────────────────────────────────────────────────────
with stack("Export", "Download country summary CSV.", "⬇️", "#64748b", "Export"):
    st.download_button(
        label="⬇️ Download country summary CSV",
        data=country_df.to_csv(index=False).encode("utf-8"),
        file_name="procurement_tco_v46_country_summary.csv",
        mime="text/csv",
    )

st.markdown(
    """<div class="v46-note" style="margin-top:32px;padding:12px 16px;border-radius:10px;background:rgba(15,23,42,.5);border:1px solid rgba(148,163,184,.12)">
    Gross financial cost is separated from treasury return offset. Net Financial Delta is the correct finance view after working-capital carry is considered.
    Finance / Treasury must validate all rate and term assumptions before official saving recognition.
    </div>""",
    unsafe_allow_html=True,
)
