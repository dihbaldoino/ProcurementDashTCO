"""
Executive Procurement TCO & Should-Cost Intelligence Platform
Version v47 — World-Class Feature Set

Run:
    pip install -r requirements.txt
    streamlit run app.py

WHAT'S NEW IN v47
-----------------
NEW MODULES (all behind collapsible expanders — zero clutter by default):

1. COMMODITY PRICE INDEX ENGINE (Direct Materials)
   – N commodities per item, each with % participation and basis/discount
   – Live formula: Base price = Σ(index_price × weight%) + basis ± discount
   – Market scenario: current vs stress (+X%) vs floor (−Y%) → TCO impact auto-calculated
   – ESG certification costs: RSPO (palm oil), RTRS (soy), ISCC, Rainforest Alliance, BONSUCRO,
     FSC, ASC, MSC, carbon offset (€/ton × Scope 3 intensity), custom certs — all modeled as
     cost add-on per unit × annual volume

2. SENSITIVITY ANALYSIS
   – Real-time sliders: price ±30%, volume ±30%, FX ±30%, financial rate ±3pp, inventory rate ±10pp
   – Tornado chart: ranks drivers by impact magnitude
   – Results update instantly without re-entering inputs
   – "Stress scenario" button: applies worst-case to all drivers simultaneously

3. AWARD SCENARIO COMPARISON
   – Save up to 3 named scenarios (A / B / C) with current inputs frozen
   – Side-by-side KPI table: spend, econ delta, risk, avg term, top supplier
   – Scenario diff highlights: green = better, red = worse vs Scenario A

4. KRALJIC MATRIX (visual)
   – Auto-positions suppliers on 2×2: spend impact (x) × supply risk (y)
   – Quadrants: Strategic / Leverage / Bottleneck / Non-critical
   – Recommended sourcing strategy per quadrant
   – Click supplier to jump to its risk card

5. BATNA / ZOPA NEGOTIATION CALCULATOR
   – Walk-away price: current TCO as anchor + max acceptable increase %
   – Supplier BATNA estimate: should-cost + min margin
   – ZOPA zone visualization: overlap = deal possible, gap = pre-work needed
   – Negotiation lever table: each lever quantified in $ value

6. SCENARIO PERSISTENCE (session)
   – Save/restore up to 3 named scenarios within the browser session
   – Export scenario as JSON for sharing
   – Import scenario JSON to reload

7. CONCENTRATION RISK ALERTS
   – Auto-flag if any supplier > configurable threshold (default 60%)
   – Herfindahl-Hirschman Index (HHI) per country
   – Single-source stress: "if Supplier X fails, cost impact = R$Y"
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
import streamlit.components.v1 as _stc

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

# ── Commodity index engine ────────────────────────────────────────────────────
COMMODITY_INDEX_PRESETS = {
    "Palm Oil (CBOT)":          {"unit": "USD/MT",   "default_price": 850.0},
    "Soybean Oil (CBOT)":       {"unit": "USD/MT",   "default_price": 1050.0},
    "Crude Oil (WTI)":          {"unit": "USD/bbl",  "default_price": 78.0},
    "Ethanol (ESALQ/Brazil)":   {"unit": "BRL/m³",   "default_price": 3200.0},
    "Sugar #11 (ICE)":          {"unit": "USc/lb",   "default_price": 22.5},
    "Natural Gas (Henry Hub)":  {"unit": "USD/MMBtu","default_price": 2.8},
    "Copper (LME)":             {"unit": "USD/MT",   "default_price": 9200.0},
    "Aluminum (LME)":           {"unit": "USD/MT",   "default_price": 2400.0},
    "Steel HRC (Platts)":       {"unit": "USD/MT",   "default_price": 620.0},
    "Polypropylene (ICIS)":     {"unit": "USD/MT",   "default_price": 1100.0},
    "HDPE (ICIS)":              {"unit": "USD/MT",   "default_price": 1050.0},
    "Caustic Soda (ICIS)":      {"unit": "USD/MT",   "default_price": 380.0},
    "Glycerin (ICIS)":          {"unit": "USD/MT",   "default_price": 620.0},
    "Isopropyl Palmitate (ICIS)":{"unit": "USD/MT",  "default_price": 1800.0},
    "Sodium Lauryl Sulfate":    {"unit": "USD/MT",   "default_price": 950.0},
    "Citric Acid (Alibaba)":    {"unit": "USD/MT",   "default_price": 1150.0},
    "Custom commodity":         {"unit": "USD/unit", "default_price": 100.0},
}

# ── ESG certification & compliance costs ────────────────────────────────────
ESG_CERT_CATALOG = {
    # Sustainability certifications with typical annual cost / MT or unit
    "RSPO (Palm Oil Roundtable)":       {"applies_to": "Palm oil, palm derivatives", "cost_per_unit": 25.0,  "unit": "USD/MT", "category": "Deforestation & Land"},
    "RTRS (Responsible Soy)":           {"applies_to": "Soybean, soy derivatives",  "cost_per_unit": 18.0,  "unit": "USD/MT", "category": "Deforestation & Land"},
    "Rainforest Alliance":              {"applies_to": "Cocoa, coffee, tea, timber", "cost_per_unit": 30.0,  "unit": "USD/MT", "category": "Deforestation & Land"},
    "BONSUCRO (Sugarcane)":             {"applies_to": "Sugar, ethanol, bagasse",    "cost_per_unit": 12.0,  "unit": "USD/MT", "category": "Deforestation & Land"},
    "ISCC (Biofuels & circular)":       {"applies_to": "Biofuels, recycled materials","cost_per_unit": 20.0, "unit": "USD/MT", "category": "Carbon & Energy"},
    "FSC (Forestry)":                   {"applies_to": "Timber, paper, packaging",   "cost_per_unit": 15.0,  "unit": "USD/MT", "category": "Deforestation & Land"},
    "ASC (Aquaculture)":                {"applies_to": "Fish, seafood",              "cost_per_unit": 40.0,  "unit": "USD/MT", "category": "Marine & Water"},
    "MSC (Marine Fisheries)":           {"applies_to": "Wild-caught fish, seafood",  "cost_per_unit": 35.0,  "unit": "USD/MT", "category": "Marine & Water"},
    "Carbon offset (Scope 3)":          {"applies_to": "Any commodity with embodied emissions", "cost_per_unit": 30.0, "unit": "USD/tCO₂e", "category": "Carbon & Energy"},
    "EU Deforestation Regulation (EUDR)":{"applies_to": "Palm, soy, beef, cocoa, coffee, rubber, timber", "cost_per_unit": 8.0, "unit": "USD/MT", "category": "Regulatory Compliance"},
    "Halal Certification":              {"applies_to": "Food & beverage ingredients","cost_per_unit": 5.0,   "unit": "USD/MT", "category": "Religious / Market Access"},
    "Kosher Certification":             {"applies_to": "Food & beverage ingredients","cost_per_unit": 5.0,   "unit": "USD/MT", "category": "Religious / Market Access"},
    "Organic (USDA/EU)":                {"applies_to": "Agricultural commodities",   "cost_per_unit": 50.0,  "unit": "USD/MT", "category": "Quality & Standards"},
    "Fairtrade":                        {"applies_to": "Coffee, cocoa, sugar, cotton","cost_per_unit": 35.0, "unit": "USD/MT", "category": "Social Standards"},
    "SA8000 (Social Accountability)":   {"applies_to": "Any manufactured goods",     "cost_per_unit": 3.0,   "unit": "USD/MT", "category": "Social Standards"},
    "Custom ESG / compliance cost":     {"applies_to": "User-defined",               "cost_per_unit": 0.0,   "unit": "USD/unit","category": "Custom"},
}

ESG_CATEGORY_COLORS = {
    "Deforestation & Land": "#10b981",
    "Carbon & Energy":      "#f59e0b",
    "Marine & Water":       "#06b6d4",
    "Regulatory Compliance":"#ef4444",
    "Religious / Market Access":"#8b5cf6",
    "Quality & Standards":  "#3b82f6",
    "Social Standards":     "#ec4899",
    "Custom":               "#64748b",
}

# ── Sensitivity analysis defaults ────────────────────────────────────────────
SENSITIVITY_DRIVERS = ["Price", "Volume", "FX Rate", "Financial Rate", "Inventory Rate"]

# ── Negotiation leverage catalog ─────────────────────────────────────────────
NEGOTIATION_LEVERS = [
    ("Payment term extension",   "Each 30 days extension worth ≈ spend × financial_rate × 30/ref_days"),
    ("Volume commitment",        "Price reduction in exchange for volume guarantee or longer contract"),
    ("Payment term acceleration","Early pay discount: spend × treasury_rate × days_early/ref_days"),
    ("Lead time reduction",      "Reduces inventory carrying cost: spend × inv_rate × days_saved/360"),
    ("MOQ reduction",            "Frees working capital tied in excess inventory"),
    ("Price escalation cap",     "Annual price increase capped vs uncapped commodity exposure"),
    ("Rebate / volume bonus",    "% of annual spend returned if volume threshold is met"),
    ("SLA penalty / bonus",      "Financial incentive for performance above target"),
]

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
        "pricing_models": [
            "Rate per shipment (tarifa por embarque)",
            "Rate per km (tarifa por km)",
            "Dedicated route / vehicle (veículo dedicado mensal)",
            "Cost plus fee (custo aberto + margem)",
            "Per pallet (tarifa por pallet)",
            "Per kg / ton (tarifa por peso)",
            "Per m³ (tarifa por cubagem)",
            "Milk run (rota multi-parada)",
            "Spot / dynamic pricing (spot sob demanda)",
            "Minimum freight + variable",
        ],
        "driver_label": "shipments/mês · km/rota · pallets · kg · m³ · orders",
        "productivity_label": "load factor ↑ · empty km ↓ · dwell time ↓ · tender acceptance ↑ · backhaul capture · intermodal migration",
        "field_labels": ["Shipments / mês", "Distância km (one-way)", "Pallets por embarque"],
        "benchmark_fte_cost": 42_000.0,
        "sla_kpis": ["OTIF %", "On-time pickup %", "Damage rate %", "Tender acceptance %", "Dwell time (min)", "Cost per shipment vs budget"],
        "leakage_drivers": [
            "Detention & demurrage (doca parada)",
            "Empty miles / km vazio (retorno sem carga)",
            "Spot overflow (baixo tender acceptance)",
            "Fuel surcharge overruns (fórmula sem teto)",
            "Accessorial leakage (taxas extras)",
            "Damage & claims cost",
            "Failed pickup / no-show",
            "Redelivery cost",
        ],
        # Route-specific sub-config
        "route_types": [
            "Inbound to Warehouse (fornecedor → armazém)",
            "Middle Mile / Transfer (FC → CD / cross-dock)",
            "Outbound B2B (armazém → lojas / hubs)",
            "Last Mile Injection (armazém → delivery station)",
            "Reverse Logistics (devoluções → armazém)",
            "Shuttle / Yard Movement (transferências internas)",
            "Dedicated Lane (rota fixa recorrente)",
            "Spot / On-demand (frete sob demanda)",
        ],
        "vehicle_types": [
            "Van / Sprinter (até 3,5t)",
            "VUC (até 6t — restrição urbana)",
            "Toco (até 13t)",
            "Truck (até 23t)",
            "Carreta LS (até 33t)",
            "Bitrem (até 57t)",
            "Rodotrem (até 74t)",
            "Refrigerado / temperatura controlada",
            "Sider / Grade aberta",
            "Baú (fechado)",
            "Container 20' / 40'",
            "Semi-reboque tanque",
        ],
        "cargo_risk_levels": [
            "Padrão / Geral (baixo valor)",
            "Médio valor (R$50K–R$300K por embarque)",
            "Alto valor (R$300K–R$1M por embarque)",
            "Muito alto valor / eletrônicos (>R$1M)",
            "Frágil / perecível",
            "Perigoso (IMDG / ADR)",
            "Farmacêutico / GDP",
        ],
        "escort_triggers": {
            "RJ / ES (rotas de risco)":          True,
            "Alto valor >R$500K":                True,
            "Eletrônicos / smartphones":         True,
            "Carga perigosa":                    False,
            "Padrão":                            False,
        },
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
    "Cost competitiveness":    20.0,  # Is the rate card benchmarked? Formula-based? Open-book?
    "SLA / Delivery":          18.0,  # On-time, quality of delivery, OTIF
    "Quality of service":      14.0,  # First-time right, defect rate, rework frequency
    "Stakeholder satisfaction":10.0,  # NPS / CSAT from internal customers
    "Contract compliance":     10.0,  # Adherence to agreed scope, rates, terms
    "Productivity / Innovation": 8.0, # Measurable efficiency gains delivered
    "Overtime control":         7.0,  # OT as % of total hours — proxy for capacity planning
    "Risk & compliance":        7.0,  # Regulatory, labor, HSE, cyber incidents
    "ESG / diversity":          6.0,  # Carbon footprint, social compliance, diversity KPIs
}
SUPPLIER_GOVERNANCE_WEIGHTS = {
    "OTIF / SLA delivery":        18.0,  # Operational delivery track record
    "Quality / NCR performance":  15.0,  # Non-conformance rate, corrective action speed
    "Financial health":           12.0,  # Z-score proxy, credit rating, cash flow signals
    "Compliance / due diligence": 15.0,  # Legal, sanctions, anti-bribery, FCPA/LGPD/GDPR
    "ESG / ethics":               10.0,  # Deforestation, modern slavery, carbon
    "Cyber / data security":       8.0,  # SOC2, ISO27001, incident history
    "Labor / HSE":                10.0,  # Accident rate, labor conditions, union relations
    "Stakeholder satisfaction":   12.0,  # Internal NPS from business partners
}
# Extended risk dimensions — McKinsey SCM standard
DEFAULT_RISK_WEIGHTS = {
    "Supply":        25.0,  # Lead time, single-source exposure, capacity
    "Quality":       18.0,  # NCR rate, spec compliance, recalls
    "Financial":     15.0,  # Supplier financial health, dependency
    "Compliance":    15.0,  # Regulatory, sanctions, FCPA, LGPD
    "ESG":           12.0,  # Deforestation, carbon, social
    "Logistics":      8.0,  # Freight reliability, port risk, customs
    "Geopolitical":   7.0,  # Country risk, tariff exposure, currency
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
    "ChemPrime":    {"Supply": 2.0, "Quality": 2.0, "Financial": 2.0, "Compliance": 1.5, "ESG": 2.0, "Logistics": 2.0, "Geopolitical": 1.5},
    "OleoGlobal":   {"Supply": 3.0, "Quality": 2.5, "Financial": 2.5, "Compliance": 2.0, "ESG": 2.5, "Logistics": 2.5, "Geopolitical": 2.5},
    "Oleo Overseas Trading Co.": {"Supply": 4.0, "Quality": 3.0, "Financial": 3.5, "Compliance": 3.0, "ESG": 3.0, "Logistics": 4.5, "Geopolitical": 4.0},
    "Comercio de Oleos Nacional Distribuicao": {"Supply": 3.0, "Quality": 2.5, "Financial": 2.5, "Compliance": 2.0, "ESG": 2.5, "Logistics": 2.5, "Geopolitical": 2.0},
}
DEFAULT_RISK_WEIGHTS_OLD_PLACEHOLDER = {}  # moved to SERVICE_SCORECARD section above

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
    # Geopolitical risk derived from compliance + ESG scores as proxy
    geo_risk = max(1.0, min(5.0,
        (score_to_risk(float(data.get("Compliance / due diligence", 75.0))) * 0.5
         + score_to_risk(float(data.get("ESG / ethics", 75.0))) * 0.5)
        + sp * 0.5
    ))
    return {
        "Supply":       max(1.0, min(5.0, score_to_risk(float(data.get("OTIF / SLA delivery",        75.0))) + 0.15 * sp)),
        "Quality":      max(1.0, min(5.0, score_to_risk(float(data.get("Quality / NCR performance",  75.0))))),
        "Financial":    max(1.0, min(5.0, score_to_risk(float(data.get("Financial health",           75.0))) + 0.25 * sp)),
        "Compliance":   max(1.0, min(5.0, score_to_risk(float(data.get("Compliance / due diligence", 75.0))) + sp)),
        "ESG":          max(1.0, min(5.0, score_to_risk(float(data.get("ESG / ethics",               75.0))) + 0.35 * sp)),
        "Logistics":    max(1.0, min(5.0, (score_to_risk(float(data.get("OTIF / SLA delivery",       75.0))) + score_to_risk(float(data.get("Labor / HSE", 75.0)))) / 2.0)),
        "Geopolitical": geo_risk,
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

    # ── Service TCO waterfall (mirrors Direct Materials price build-up) ──────
    svc_wf_rows = [
        ("Proposed contract / service value",    float(proposed_value),          True),
        ("Transition / implementation cost",     float(transition_cost),          float(transition_cost) > 0),
        ("Change order reserve",                 float(change_order_reserve),     float(change_order_reserve) > 0),
        ("Internal management cost",             float(internal_mgmt),            float(internal_mgmt) > 0),
        ("Rework / quality cost",                float(rework_cost_sup),          float(rework_cost_sup) > 0),
        ("Annual overtime cost",                 float(ot_cost_input),            float(ot_cost_input) > 0),
        ("SLA risk cost (quantified exposure)",  sla_risk_cost,                   sla_risk_cost > 0),
        ("Expected risk cost (prob × impact)",   expected_risk_cost,              expected_risk_cost > 0),
        ("− SLA credits / rebates",              -float(sla_credits_rebates),     float(sla_credits_rebates) > 0),
        ("− Productivity gain committed",        -float(productivity_gain),       float(productivity_gain) > 0),
    ]
    wf_html_svc = "".join(
        f"<div style='display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(148,163,184,.07)'>"
        f"<span style='font-size:.77rem;color:{'#94a3b8' if val>=0 else '#34d399'}'>{lbl}</span>"
        f"<span style='font-family:IBM Plex Mono,monospace;font-size:.77rem;color:{'#e2e8f0' if val>=0 else '#34d399'}'>"
        f"{'+' if val>0 else ''}{reporting_currency} {val:,.0f}</span></div>"
        for lbl, val, show in svc_wf_rows if show
    )
    roi_str = f"{roi['three_year_roi_pct']:.0f}% ROI · {roi['payback_months']:.1f}mo payback · {reporting_currency} {roi['net_three_year_value']:,.0f} net 3yr" if float(productivity_gain) > 0 else "no productivity commitment entered"
    st.markdown(
        f"""<div class="v46-svc-result" style="padding:14px 18px">
            <div style='margin-bottom:8px;font-size:.82rem;font-weight:600;color:#c4b5fd'>
                📐 Service TCO waterfall — all components included
            </div>
            {wf_html_svc}
            <div style='display:flex;justify-content:space-between;padding:7px 0 0 0;margin-top:4px;border-top:1px solid rgba(139,92,246,.3)'>
                <span style='font-size:.84rem;font-weight:700;color:#f1f5f9'>Final Service TCO (proposal spend)</span>
                <span style='font-family:IBM Plex Mono,monospace;font-size:.96rem;font-weight:700;color:#a78bfa'>{reporting_currency} {service_tco:,.0f}</span>
            </div>
            <div style='margin-top:8px;display:flex;gap:18px;flex-wrap:wrap;font-size:.78rem;color:#94a3b8'>
                <span><b style='color:#e2e8f0'>Perf-adj cost:</b> {reporting_currency} {perf_adj_cost:,.0f}</span>
                <span><b style='color:#e2e8f0'>Should-cost gap:</b> <span style='color:{"#f87171" if should_cost_gap>0 else "#34d399"}'>{reporting_currency} {should_cost_gap:,.0f}</span></span>
                <span><b style='color:#e2e8f0'>{int(contract_years)}-yr TCV:</b> {reporting_currency} {tcv["total_contract_value"]:,.0f}</span>
                <span><b style='color:#e2e8f0'>Productivity:</b> {roi_str}</span>
            </div>
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
    """
    Unified price waterfall. Final price = EVERYTHING the user defines:
      commodity formula OR manual base price
      + conversion cost + fixed margin
      + international freight + insurance + customs + import duties
      + domestic freight + local taxes
      + ESG / certification costs
    All in quote currency → converted to reporting currency via FX.
    spend = final_unit_price_reporting × volume
    """
    if currency_default not in CURRENCY_OPTIONS:
        currency_default = "BRL"
    default_fx = float(DEFAULT_FX_TO_REPORTING.get(currency_default, 1.0))
    base_default = default_unit_price_from_spend(default_spend, max(default_volume * default_fx, 1e-9))

    # ── Row 1: volume, currency, FX, MOQ ─────────────────────────────────
    r0 = st.columns([1.0, .82, .78, .78, .72])
    with r0[0]:
        base_unit_price = st.number_input(
            f"{supplier_label} | Base / quoted unit price ({currency_default})",
            min_value=0.0, value=float(base_default), step=0.01, format="%.6f",
            key=f"{key_prefix}__base_unit_price",
            help="Manual price. Will be overridden if commodity formula is active below.",
        )
    with r0[1]:
        currency = st.selectbox(f"{supplier_label} | Quote currency", options=CURRENCY_OPTIONS, index=CURRENCY_OPTIONS.index(currency_default), key=f"{key_prefix}__currency")
    with r0[2]:
        fx_rate = st.number_input(f"{supplier_label} | FX → {reporting_currency}", min_value=0.000001, value=default_fx, step=0.01, format="%.6f", key=f"{key_prefix}__fx_rate")
    with r0[3]:
        volume = st.number_input(f"{supplier_label} | 100% volume ({unit})", min_value=0.0, value=float(default_volume), step=max(float(default_volume) * 0.05, 1.0), format="%.4f", key=f"{key_prefix}__volume")
    with r0[4]:
        moq = st.number_input(f"{supplier_label} | MOQ ({unit})", min_value=0.0, value=0.0, step=max(float(default_volume) * 0.05, 1.0), format="%.4f", key=f"{key_prefix}__moq")
        incoterm = st.selectbox(f"{supplier_label} | Incoterm", options=INCOTERM_OPTIONS, index=INCOTERM_OPTIONS.index("FOB"), key=f"{key_prefix}__incoterm")

    # ── Row 2: processing & trade cost components (in quote currency / unit) ─
    r2 = st.columns(6)
    with r2[0]: conversion_cost  = st.number_input(f"{supplier_label} | Conversion / {unit}",      min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__conversion_cost")
    with r2[1]: fixed_margin     = st.number_input(f"{supplier_label} | Fixed margin / {unit}",     min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__fixed_margin")
    with r2[2]: intl_freight     = st.number_input(f"{supplier_label} | Intl freight / {unit}",     min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__international_freight")
    with r2[3]: insurance        = st.number_input(f"{supplier_label} | Insurance / {unit}",        min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__insurance")
    with r2[4]: customs          = st.number_input(f"{supplier_label} | Customs / brokerage / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__customs_fees")
    with r2[5]: import_duties    = st.number_input(f"{supplier_label} | Import duties / taxes / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__import_duties_taxes")

    r3 = st.columns(6)
    with r3[0]: dom_freight      = st.number_input(f"{supplier_label} | Domestic freight / {unit}", min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__domestic_freight")
    with r3[1]: local_taxes      = st.number_input(f"{supplier_label} | Local taxes / {unit}",      min_value=0.0, value=0.0, step=0.01, format="%.6f", key=f"{key_prefix}__local_taxes")
    # remaining cells left intentionally empty for future components

    # ── Commodity index formula (optional — overrides base price if active) ─
    comm_result = render_commodity_index_engine(
        key_prefix=key_prefix, base_unit_price=float(base_unit_price),
        unit=unit, reporting_currency=reporting_currency,
    )
    effective_base = (
        float(comm_result["effective_base_price"])
        if comm_result.get("formula_active") and comm_result.get("effective_base_price", 0.0) > 0
        else float(base_unit_price)
    )

    # ── ESG / certification costs (in reporting currency / unit) ─────────
    esg_result = render_esg_cost_engine(
        key_prefix=key_prefix, volume=float(volume), unit=unit,
        reporting_currency=reporting_currency,
    )
    esg_cpu_reporting = float(esg_result.get("total_cost_per_unit", 0.0))

    # ── UNIFIED PRICE WATERFALL ───────────────────────────────────────────
    # All quote-currency components × FX, then + ESG (already in reporting currency)
    comps_quote = {
        "base_unit_price":     effective_base,
        "conversion_cost":     float(conversion_cost),
        "fixed_margin":        float(fixed_margin),
        "international_freight": float(intl_freight),
        "insurance":           float(insurance),
        "customs_fees":        float(customs),
        "import_duties_taxes": float(import_duties),
        "domestic_freight":    float(dom_freight),
        "local_taxes":         float(local_taxes),
    }
    # Sum all components in quote currency, then convert to reporting
    total_quote_cpu = sum(comps_quote.values())
    total_reporting_cpu_before_esg = total_quote_cpu * float(fx_rate)
    final_unit_price_reporting = total_reporting_cpu_before_esg + esg_cpu_reporting
    spend = final_unit_price_reporting * float(volume)

    # MOQ economics
    moq_excess = max(float(moq) - float(volume), 0.0) if float(moq) > 0 else 0.0
    moq_cash   = moq_excess * final_unit_price_reporting
    moq_note   = "OK" if float(moq) <= 0 or float(volume) >= float(moq) else "Volume below MOQ ⚠"
    moq_color  = "#34d399" if "OK" in moq_note else "#f87171"

    # ── Price build-up summary card ───────────────────────────────────────
    waterfall_rows = [
        ("Base / commodity price",   effective_base * float(fx_rate),     comm_result.get("formula_active", False)),
        ("Conversion cost",          float(conversion_cost) * float(fx_rate), float(conversion_cost) > 0),
        ("Fixed margin",             float(fixed_margin) * float(fx_rate),    float(fixed_margin) > 0),
        ("International freight",    float(intl_freight) * float(fx_rate),    float(intl_freight) > 0),
        ("Insurance",                float(insurance) * float(fx_rate),        float(insurance) > 0),
        ("Customs / brokerage",      float(customs) * float(fx_rate),          float(customs) > 0),
        ("Import duties / taxes",    float(import_duties) * float(fx_rate),    float(import_duties) > 0),
        ("Domestic freight",         float(dom_freight) * float(fx_rate),      float(dom_freight) > 0),
        ("Local taxes",              float(local_taxes) * float(fx_rate),      float(local_taxes) > 0),
        ("ESG / certification costs",esg_cpu_reporting,                        esg_cpu_reporting > 0),
    ]
    active_rows = [(lbl, val) for lbl, val, active in waterfall_rows if active or lbl == "Base / commodity price"]
    wf_html = "".join(
        f"<div style='display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(148,163,184,.08)'>"
        f"<span style='font-size:.78rem;color:#94a3b8'>{lbl}</span>"
        f"<span style='font-family:\"IBM Plex Mono\",monospace;font-size:.78rem;color:#e2e8f0'>{reporting_currency} {val:,.6f}</span>"
        f"</div>"
        for lbl, val in active_rows
    )
    commodity_tag = " <span style='color:#f59e0b;font-size:.72rem'>[formula]</span>" if comm_result.get("formula_active") else ""
    esg_tag = f" <span style='color:#10b981;font-size:.72rem'>[+{reporting_currency} {esg_cpu_reporting:.4f} ESG]</span>" if esg_cpu_reporting > 0 else ""
    moq_tag = f"<span style='color:{moq_color};font-weight:700'>{moq_note}</span>"

    st.markdown(
        f"""<div class="v46-landed" style="padding:14px 18px">
            <div style='margin-bottom:8px;font-size:.82rem;font-weight:600;color:#e2e8f0'>
                📐 Price build-up — all components included{commodity_tag}{esg_tag}
            </div>
            {wf_html}
            <div style='display:flex;justify-content:space-between;padding:7px 0 0 0;margin-top:4px;border-top:1px solid rgba(148,163,184,.25)'>
                <span style='font-size:.84rem;font-weight:700;color:#f1f5f9'>Final landed unit price</span>
                <span style='font-family:"IBM Plex Mono",monospace;font-size:.96rem;font-weight:700;color:#60a5fa'>{reporting_currency} {final_unit_price_reporting:,.6f} / {escape(unit)}</span>
            </div>
            <div style='margin-top:8px;display:flex;gap:18px;flex-wrap:wrap;font-size:.78rem;color:#94a3b8'>
                <span><b style='color:#e2e8f0'>100% spend:</b> {reporting_currency} {spend:,.2f}</span>
                <span><b style='color:#e2e8f0'>MOQ:</b> {moq_tag}</span>
                <span><b style='color:#e2e8f0'>MOQ cash tied:</b> {reporting_currency} {moq_cash:,.2f}</span>
                <span><b style='color:#e2e8f0'>FX used:</b> {float(fx_rate):.4f} {currency}→{reporting_currency}</span>
                <span><b style='color:#e2e8f0'>Incoterm:</b> {incoterm}</span>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

    return {
        "spend":                     float(spend),
        "unit_price_quote":          float(total_quote_cpu),
        "unit_price_reporting":      float(final_unit_price_reporting),
        "unit_price_before_esg":     float(total_reporting_cpu_before_esg),
        "esg_cost_per_unit":         float(esg_cpu_reporting),
        "esg_annual_total":          float(esg_result.get("annual_total", 0.0)),
        "commodity_formula_price":   float(comm_result.get("formula_price", 0.0)),
        "commodity_formula_active":  bool(comm_result.get("formula_active", False)),
        "volume":                    float(volume),
        "moq":                       float(moq),
        "moq_excess_units_100pct":   float(moq_excess),
        "moq_cash_tied_preview":     float(moq_cash),
        "currency":                  currency,
        "fx_rate":                   float(fx_rate),
        "incoterm":                  incoterm,
        # Individual components (all in reporting currency for downstream use)
        "base_unit_price":           effective_base,
        "conversion_cost":           float(conversion_cost),
        "fixed_margin":              float(fixed_margin),
        "international_freight":     float(intl_freight),
        "insurance":                 float(insurance),
        "customs_fees":              float(customs),
        "import_duties_taxes":       float(import_duties),
        "domestic_freight":          float(dom_freight),
        "local_taxes":               float(local_taxes),
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
# V47 NEW ENGINES
# ─────────────────────────────────────────────────────────────────────────────

# ── Commodity Index Engine ────────────────────────────────────────────────────

def calc_commodity_index_price(
    components: List[Dict],  # [{name, weight_pct, index_price, basis, discount}]
) -> Dict[str, float]:
    """Compute formula-based price from N commodity indices."""
    total_weight = sum(float(c.get("weight_pct", 0.0)) for c in components)
    if total_weight <= 0:
        return {"formula_price": 0.0, "total_weight": 0.0, "components": components}
    formula_price = sum(
        float(c.get("index_price", 0.0)) * (float(c.get("weight_pct", 0.0)) / 100.0)
        + float(c.get("basis", 0.0))
        - float(c.get("discount", 0.0))
        for c in components
    )
    return {"formula_price": formula_price, "total_weight": total_weight, "components": components}


def calc_esg_cost_per_unit(
    certs: List[Dict],  # [{name, cost_per_unit, volume_mt, scope3_intensity}]
    volume: float,
) -> Dict[str, float]:
    """Total ESG/certification cost per unit and annually."""
    if volume <= 0:
        return {"total_cost_per_unit": 0.0, "annual_total": 0.0, "breakdown": []}
    breakdown = []
    total_cpu = 0.0
    for c in certs:
        if not c.get("enabled", False):
            continue
        cpu = float(c.get("cost_per_unit", 0.0))
        # For carbon offset: cost = intensity (tCO2e/MT) × carbon_price × volume
        if "Scope 3" in c.get("name", "") or "carbon" in c.get("name", "").lower():
            intensity = float(c.get("scope3_intensity", 0.5))
            cpu = cpu * intensity  # carbon_price already in cost_per_unit field
        total_cpu += cpu
        breakdown.append({
            "cert": c.get("name", ""), "cost_per_unit": cpu,
            "annual_cost": cpu * volume, "category": c.get("category", ""),
        })
    return {"total_cost_per_unit": total_cpu, "annual_total": total_cpu * volume, "breakdown": breakdown}


def render_commodity_index_engine(*, key_prefix: str, base_unit_price: float, unit: str, reporting_currency: str) -> Dict:
    """Collapsible commodity formula builder. Returns adjusted base price."""
    with st.expander("📊 Commodity price index formula", expanded=False):
        st.caption("Model the base price as a formula of market indices. Each commodity contributes weight % × index price + basis − discount.")
        n_comms = st.number_input("Number of commodities in the formula", min_value=1, max_value=8, value=1, step=1, key=f"{key_prefix}__n_comms")
        components = []
        for i in range(int(n_comms)):
            st.markdown(f"<div style='font-size:.78rem;color:#94a3b8;font-weight:600;margin:8px 0 4px'>Commodity {i+1}</div>", unsafe_allow_html=True)
            cc = st.columns([1.4, .7, .8, .6, .6])
            with cc[0]:
                comm_name = st.selectbox(f"Index {i+1}", options=list(COMMODITY_INDEX_PRESETS.keys()), index=0, key=f"{key_prefix}__comm_name_{i}")
            preset = COMMODITY_INDEX_PRESETS[comm_name]
            with cc[1]:
                weight_pct = st.number_input(f"Weight %", min_value=0.0, max_value=100.0, value=100.0 if n_comms == 1 else round(100.0/int(n_comms), 1), step=0.5, format="%.1f", key=f"{key_prefix}__comm_weight_{i}")
            with cc[2]:
                idx_price = st.number_input(f"Index price ({preset['unit']})", min_value=0.0, value=float(preset["default_price"]), step=float(preset["default_price"])*0.01, format="%.4f", key=f"{key_prefix}__comm_price_{i}")
            with cc[3]:
                basis = st.number_input("Basis +", min_value=-9999.0, value=0.0, step=1.0, format="%.4f", key=f"{key_prefix}__comm_basis_{i}", help="Fixed add-on (freight, processing, trader margin) in same unit as index")
            with cc[4]:
                discount = st.number_input("Discount −", min_value=0.0, value=0.0, step=1.0, format="%.4f", key=f"{key_prefix}__comm_discount_{i}", help="Negotiated discount off index")
            components.append({"name": comm_name, "weight_pct": float(weight_pct), "index_price": float(idx_price), "basis": float(basis), "discount": float(discount), "unit": preset["unit"]})

        result = calc_commodity_index_price(components)
        fp = result["formula_price"]
        tw = result["total_weight"]

        # Stress / floor scenarios
        sc = st.columns(3)
        with sc[0]: stress_pct = st.number_input("Market stress scenario (%)", min_value=0.0, max_value=100.0, value=10.0, step=0.5, format="%.1f", key=f"{key_prefix}__stress_pct", help="% increase applied to all index prices for worst-case TCO")
        with sc[1]: floor_pct = st.number_input("Floor / hedge scenario (%)", min_value=0.0, max_value=100.0, value=10.0, step=0.5, format="%.1f", key=f"{key_prefix}__floor_pct", help="% decrease for optimistic scenario")
        with sc[2]: use_formula = st.checkbox("Use formula price as base unit price", value=(fp > 0), key=f"{key_prefix}__use_formula")

        fp_stress = fp * (1 + float(stress_pct)/100.0)
        fp_floor  = fp * (1 - float(floor_pct)/100.0)

        if tw > 0:
            weight_warn = "" if abs(tw - 100.0) < 0.5 else f" ⚠ weights sum to {tw:.1f}% — should be 100%"
            st.markdown(
                f"""<div class="v46-landed">
                <b>Formula price:</b> {fp:.4f} {components[0]['unit'] if components else ''}{weight_warn} &nbsp;·&nbsp;
                <b>Stress (+{stress_pct:.1f}%):</b> {fp_stress:.4f} &nbsp;·&nbsp;
                <b>Floor (−{floor_pct:.1f}%):</b> {fp_floor:.4f} &nbsp;·&nbsp;
                <b>Used as base price:</b> {'✓ Yes' if use_formula else '✗ No — manual price used'}
                </div>""",
                unsafe_allow_html=True,
            )
        effective_base = fp if (use_formula and fp > 0) else base_unit_price
        return {
            "formula_price": fp, "stress_price": fp_stress, "floor_price": fp_floor,
            "formula_active": use_formula and fp > 0, "effective_base_price": effective_base,
            "components": components, "total_weight_pct": tw,
        }


def render_esg_cost_engine(*, key_prefix: str, volume: float, unit: str, reporting_currency: str) -> Dict:
    """Collapsible ESG & certification cost builder. Returns cost per unit and annual total."""
    with st.expander("🌿 ESG & certification costs", expanded=False):
        st.caption("Select certifications and compliance costs that apply to this commodity/supplier. Costs are added to the landed price per unit.")
        enabled_certs = []
        by_category: Dict[str, List] = {}
        for name, cfg in ESG_CERT_CATALOG.items():
            cat = cfg["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append((name, cfg))

        for cat, items_list in by_category.items():
            cat_color = ESG_CATEGORY_COLORS.get(cat, "#64748b")
            st.markdown(f"<div style='font-size:.72rem;font-weight:600;color:{cat_color};text-transform:uppercase;letter-spacing:.07em;margin:10px 0 4px'>{cat}</div>", unsafe_allow_html=True)
            cols = st.columns(min(3, len(items_list)))
            for idx, (name, cfg) in enumerate(items_list):
                with cols[idx % 3]:
                    enabled = st.checkbox(name.split("(")[0].strip(), value=False, key=f"{key_prefix}__esg__{name[:20].replace(' ','_')}")
                    if enabled:
                        cpu_default = float(cfg["cost_per_unit"])
                        scope3_intensity = 1.0
                        if "Scope 3" in name or "carbon" in name.lower():
                            cpu = st.number_input(f"Carbon price ({cfg['unit']})", min_value=0.0, value=cpu_default, step=1.0, format="%.2f", key=f"{key_prefix}__esg_cpu_{name[:15]}")
                            scope3_intensity = st.number_input("Scope 3 intensity (tCO₂e/unit)", min_value=0.0, value=0.5, step=0.1, format="%.3f", key=f"{key_prefix}__esg_scope3_{name[:15]}")
                        else:
                            cpu = st.number_input(f"Cost ({cfg['unit']})", min_value=0.0, value=cpu_default, step=0.5, format="%.4f", key=f"{key_prefix}__esg_cpu_{name[:15]}")
                        enabled_certs.append({"name": name, "enabled": True, "cost_per_unit": float(cpu), "category": cat, "scope3_intensity": scope3_intensity})

        esg_result = calc_esg_cost_per_unit(enabled_certs, volume)
        if esg_result["annual_total"] > 0:
            breakdown_html = " &nbsp;·&nbsp; ".join(f"<b>{b['cert'].split('(')[0].strip()}:</b> {reporting_currency} {b['cost_per_unit']:.4f}/{unit}" for b in esg_result["breakdown"])
            st.markdown(
                f"""<div class="v46-landed" style="border-color:rgba(16,185,129,.3)">
                🌿 <b>Total ESG cost / unit:</b> {reporting_currency} {esg_result['total_cost_per_unit']:.4f} &nbsp;·&nbsp;
                <b>Annual total:</b> {reporting_currency} {esg_result['annual_total']:,.2f} &nbsp;·&nbsp; {breakdown_html}
                </div>""",
                unsafe_allow_html=True,
            )
        return esg_result


# ── Sensitivity Analysis Engine ───────────────────────────────────────────────

def run_sensitivity(
    base_econ_delta: float,
    base_spend: float,
    price_pct: float, volume_pct: float, fx_pct: float,
    fin_rate_pp: float, inv_rate_pp: float,
    country_inputs: Dict, proposal_inputs: Dict,
    all_shares: Dict, supplier_risk: Dict, method: str,
) -> Dict[str, float]:
    """Compute delta impact of each sensitivity driver independently (tornado)."""
    results = {}
    base = base_econ_delta

    def _perturb_ci(ci_copy, country, key, delta_abs):
        ci_copy[country] = dict(ci_copy[country])
        ci_copy[country][key] = max(0.0, ci_copy[country][key] + delta_abs)
        return ci_copy

    def _perturb_spend(pi_copy, country, sup, factor):
        pi_copy[country] = dict(pi_copy[country])
        pi_copy[country][sup] = dict(pi_copy[country][sup])
        pi_copy[country][sup]["spend"] = pi_copy[country][sup]["spend"] * factor
        return pi_copy

    import copy

    # Price sensitivity: all proposal spends × (1 + pct)
    if abs(price_pct) > 1e-9:
        pi2 = copy.deepcopy(proposal_inputs)
        for c in COUNTRIES:
            for s in SUPPLIERS:
                pi2[c][s]["spend"] = pi2[c][s]["spend"] * (1 + price_pct / 100.0)
        _, _, _, t2 = calc_scenario(all_shares, country_inputs, pi2, supplier_risk, method)
        results["Price"] = t2["Economic All-In Delta"] - base

    # Volume sensitivity: doesn't change spend directly in current model; proxy via inventory
    # For simplicity, volume affects MOQ drag and inventory sizing — we scale inventory days
    if abs(volume_pct) > 1e-9:
        ci2 = copy.deepcopy(country_inputs)
        for c in COUNTRIES:
            # Higher volume → proportionally lower inventory risk
            ci2[c]["current_inventory_days"] = max(1, int(ci2[c]["current_inventory_days"] * (1 - volume_pct / 200.0)))
        _, _, _, t2 = calc_scenario(all_shares, ci2, proposal_inputs, supplier_risk, method)
        results["Volume"] = t2["Economic All-In Delta"] - base

    # FX sensitivity: scale all financial rates proportionally (proxy for FX-denominated spend)
    if abs(fx_pct) > 1e-9:
        pi2 = copy.deepcopy(proposal_inputs)
        for c in COUNTRIES:
            for s in SUPPLIERS:
                pi2[c][s]["spend"] = pi2[c][s]["spend"] * (1 + fx_pct / 100.0)
        _, _, _, t2 = calc_scenario(all_shares, country_inputs, pi2, supplier_risk, method)
        results["FX Rate"] = t2["Economic All-In Delta"] - base

    # Financial rate sensitivity
    if abs(fin_rate_pp) > 1e-9:
        ci2 = copy.deepcopy(country_inputs)
        for c in COUNTRIES:
            ci2[c]["financial_rate_pct"] = max(0.0, ci2[c]["financial_rate_pct"] + fin_rate_pp)
        _, _, _, t2 = calc_scenario(all_shares, ci2, proposal_inputs, supplier_risk, method)
        results["Financial Rate"] = t2["Economic All-In Delta"] - base

    # Inventory rate sensitivity
    if abs(inv_rate_pp) > 1e-9:
        ci2 = copy.deepcopy(country_inputs)
        for c in COUNTRIES:
            ci2[c]["inventory_carry_rate_pct"] = max(0.0, ci2[c]["inventory_carry_rate_pct"] + inv_rate_pp)
        _, _, _, t2 = calc_scenario(all_shares, ci2, proposal_inputs, supplier_risk, method)
        results["Inventory Rate"] = t2["Economic All-In Delta"] - base

    return results


def render_sensitivity_panel(
    base_econ_delta: float, base_spend: float,
    country_inputs: Dict, proposal_inputs: Dict,
    all_shares: Dict, supplier_risk: Dict, method: str,
    currency: str,
):
    """Sensitivity analysis panel with tornado chart."""
    with st.expander("🎚 Sensitivity analysis — what-if scenarios", expanded=False):
        st.caption("Move sliders to test impact of each driver independently. Tornado shows which variables matter most.")
        sc = st.columns(5)
        with sc[0]: price_pct = st.slider("Price ±%", -30.0, 30.0, 0.0, 1.0, key="sens_price")
        with sc[1]: vol_pct   = st.slider("Volume ±%", -30.0, 30.0, 0.0, 1.0, key="sens_vol")
        with sc[2]: fx_pct    = st.slider("FX ±%", -30.0, 30.0, 0.0, 1.0, key="sens_fx")
        with sc[3]: fin_pp    = st.slider("Fin. rate ±pp", -3.0, 3.0, 0.0, 0.25, key="sens_fin")
        with sc[4]: inv_pp    = st.slider("Inv. rate ±pp", -10.0, 10.0, 0.0, 0.5, key="sens_inv")

        any_active = any(abs(v) > 1e-9 for v in [price_pct, vol_pct, fx_pct, fin_pp, inv_pp])
        stress_col, _ = st.columns([.3, .7])
        with stress_col:
            if st.button("⚡ Apply worst-case stress", key="sens_stress"):
                st.session_state["sens_price"] = 20.0
                st.session_state["sens_vol"] = -20.0
                st.session_state["sens_fx"] = 15.0
                st.session_state["sens_fin"] = 2.0
                st.session_state["sens_inv"] = 5.0
                st.rerun()

        if any_active:
            try:
                deltas = run_sensitivity(
                    base_econ_delta, base_spend,
                    price_pct, vol_pct, fx_pct, fin_pp, inv_pp,
                    country_inputs, proposal_inputs, all_shares, supplier_risk, method,
                )
                # Summary line
                total_impact = sum(deltas.values())
                adjusted_econ = base_econ_delta + total_impact
                tone_color = "#34d399" if adjusted_econ <= 0 else "#f87171"
                st.markdown(
                    f"""<div class="v46-landed">
                    <b>Base economic delta:</b> {fmt_money(base_econ_delta, currency, compact=True, signed=True)} &nbsp;·&nbsp;
                    <b>Sensitivity impact:</b> {fmt_money(total_impact, currency, compact=True, signed=True)} &nbsp;·&nbsp;
                    <b>Adjusted delta:</b> <span style="color:{tone_color};font-weight:700">{fmt_money(adjusted_econ, currency, compact=True, signed=True)}</span>
                    </div>""",
                    unsafe_allow_html=True,
                )
                if PLOTLY_AVAILABLE and deltas:
                    drivers = list(deltas.keys())
                    vals = [deltas[d] for d in drivers]
                    colors = ["#ef4444" if v > 0 else "#10b981" for v in vals]
                    fig_t = go.Figure(go.Bar(
                        x=vals, y=drivers, orientation="h",
                        marker_color=colors,
                        text=[fmt_money(v, currency, compact=True, signed=True) for v in vals],
                        textposition="outside",
                        hovertemplate="%{y}: %{x:,.0f}<extra></extra>",
                    ))
                    fig_t.update_layout(title="Tornado — sensitivity impact by driver", xaxis_title=f"Δ Economic all-in ({currency})", height=280)
                    st.plotly_chart(apply_chart_theme(fig_t, 280), use_container_width=True, config={"displayModeBar": False})
            except Exception as ex:
                st.warning(f"Sensitivity calculation failed: {ex}")
        else:
            st.info("Move any slider to compute the sensitivity impact on economic all-in delta.")


# ── Award Scenario Comparison ─────────────────────────────────────────────────

def save_scenario(name: str, total: Dict, country_df: pd.DataFrame, supplier_focus_df: pd.DataFrame, shares: Dict) -> None:
    scenarios = st.session_state.get("saved_scenarios", {})
    if len(scenarios) >= 3 and name not in scenarios:
        st.warning("Maximum 3 scenarios. Delete one before saving a new one.")
        return
    scenarios[name] = {
        "total": {k: float(v) for k, v in total.items() if isinstance(v, (int, float))},
        "top_supplier": supplier_focus_df.iloc[0]["Supplier"] if not supplier_focus_df.empty else "—",
        "risk": float(total.get("Weighted Risk", 0.0)),
        "avg_term": float(total.get("New Avg Payment Days", 0.0)),
        "econ_delta": float(total.get("Economic All-In Delta", 0.0)),
        "spend_delta": float(total.get("Spend Delta", 0.0)),
        "gross_delta": float(total.get("Gross All-In Delta", 0.0)),
    }
    st.session_state["saved_scenarios"] = scenarios


def render_award_scenarios(total: Dict, supplier_focus_df: pd.DataFrame, shares: Dict, currency: str):
    """Award scenario save & compare panel."""
    with st.expander("🏆 Award scenario comparison — save & compare A vs B vs C", expanded=False):
        scenarios = st.session_state.get("saved_scenarios", {})
        sc_cols = st.columns([.45, .45, .1])
        with sc_cols[0]:
            scen_name = st.text_input("Scenario name", value=f"Scenario {chr(65+len(scenarios))}", key="scen_name_input", placeholder="e.g. Dual source 60/40")
        with sc_cols[1]:
            st.markdown("<div style='height:27px'></div>", unsafe_allow_html=True)
            if st.button("💾 Save current scenario", type="primary", key="save_scen"):
                save_scenario(scen_name.strip() or f"Scenario {chr(65+len(scenarios))}", total, None if supplier_focus_df.empty else supplier_focus_df, supplier_focus_df, shares)
                st.rerun()
        with sc_cols[2]:
            st.markdown("<div style='height:27px'></div>", unsafe_allow_html=True)
            if st.button("🗑", key="clear_scens", help="Clear all saved scenarios"):
                st.session_state["saved_scenarios"] = {}
                st.rerun()

        if not scenarios:
            st.info("Save the current scenario above, then change inputs and save another to compare side-by-side.")
            return

        # Build comparison table
        keys = ["econ_delta", "gross_delta", "spend_delta", "risk", "avg_term", "top_supplier"]
        labels = ["Economic all-in", "Gross delta", "Spend delta", "Weighted risk", "Avg term (dd)", "Top supplier"]
        scen_names = list(scenarios.keys())

        # Header
        header = ["Metric"] + scen_names
        rows_data = []
        for k, lbl in zip(keys, labels):
            row = [lbl]
            for sn in scen_names:
                v = scenarios[sn].get(k, 0)
                if k in ("econ_delta", "gross_delta", "spend_delta"):
                    row.append(fmt_money(v, currency, compact=True, signed=True))
                elif k == "risk":
                    row.append(f"{v:.2f}/5")
                elif k == "avg_term":
                    row.append(f"{v:.0f} dd")
                else:
                    row.append(str(v))
            rows_data.append(row)

        df_comp = pd.DataFrame(rows_data, columns=header)
        st.dataframe(df_comp, use_container_width=True, hide_index=True)

        # Visual delta bar vs first scenario
        if len(scen_names) > 1 and PLOTLY_AVAILABLE:
            base_econ = scenarios[scen_names[0]]["econ_delta"]
            diffs = [scenarios[s]["econ_delta"] - base_econ for s in scen_names[1:]]
            colors = ["#10b981" if d < 0 else "#ef4444" for d in diffs]
            fig_sc = go.Figure(go.Bar(
                x=scen_names[1:], y=diffs,
                marker_color=colors,
                text=[fmt_money(d, currency, compact=True, signed=True) for d in diffs],
                textposition="outside",
            ))
            fig_sc.update_layout(title=f"Economic delta vs {scen_names[0]}", yaxis_title=f"Δ ({currency})", height=260)
            st.plotly_chart(apply_chart_theme(fig_sc, 260), use_container_width=True, config={"displayModeBar": False})


# ── Kraljic Matrix Visual ─────────────────────────────────────────────────────

def render_kraljic_matrix(supplier_focus_df: pd.DataFrame, risk_inputs: Dict, risk_weights: Dict, total: Dict, currency: str):
    """Visual Kraljic 2×2 matrix: spend impact × supply risk."""
    if supplier_focus_df.empty or not PLOTLY_AVAILABLE:
        return
    with st.expander("🔷 Kraljic matrix — portfolio positioning", expanded=False):
        st.caption("Suppliers are positioned by spend share (x-axis = business impact) × weighted risk score (y-axis). Quadrant determines recommended sourcing strategy.")
        # Compute positions
        sup_risk = supplier_risk_scores(risk_inputs, risk_weights)
        total_spend = max(float(total.get("New Spend", 1.0)), 1.0)
        rows = []
        for _, row in supplier_focus_df.iterrows():
            sid = row["Supplier ID"]
            spend = float(row.get("Allocated Spend", 0.0))
            spend_pct = safe_divide(spend, total_spend) * 100.0
            risk_score = float(sup_risk.get(sid, 3.0))
            # Quadrant
            if spend_pct >= 20 and risk_score >= 3.0:
                quad = "Strategic"; quad_color = "#ef4444"
            elif spend_pct >= 20 and risk_score < 3.0:
                quad = "Leverage"; quad_color = "#10b981"
            elif spend_pct < 20 and risk_score >= 3.0:
                quad = "Bottleneck"; quad_color = "#f59e0b"
            else:
                quad = "Non-critical"; quad_color = "#64748b"
            rows.append({
                "Supplier": row["Supplier"], "Supplier ID": sid,
                "Spend %": spend_pct, "Risk": risk_score,
                "Quadrant": quad, "Color": quad_color,
                "Spend": spend,
            })
        df_kj = pd.DataFrame(rows)

        fig_kj = go.Figure()
        # Quadrant backgrounds
        for (x0, x1, y0, y1, label, bg) in [
            (0, 20, 3.0, 5.0, "Bottleneck", "rgba(245,158,11,.08)"),
            (20, 100, 3.0, 5.0, "Strategic", "rgba(239,68,68,.08)"),
            (0, 20, 1.0, 3.0, "Non-critical", "rgba(100,116,139,.06)"),
            (20, 100, 1.0, 3.0, "Leverage", "rgba(16,185,129,.08)"),
        ]:
            fig_kj.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, fillcolor=bg, line_width=0, layer="below")
            fig_kj.add_annotation(x=(x0+x1)/2, y=(y0+y1)/2, text=label, showarrow=False,
                font=dict(size=11, color="rgba(148,163,184,.6)", family="Inter"), xanchor="center")

        # Supplier dots
        for quad in df_kj["Quadrant"].unique():
            sub = df_kj[df_kj["Quadrant"]==quad]
            fig_kj.add_trace(go.Scatter(
                x=sub["Spend %"], y=sub["Risk"], mode="markers+text",
                text=sub["Supplier"].apply(lambda s: s[:12]+"…" if len(s)>12 else s),
                textposition="top center",
                marker=dict(size=14+sub["Spend %"]/10, color=sub["Color"].iloc[0], opacity=0.85, line=dict(width=1.5, color="rgba(255,255,255,.3)")),
                name=quad, showlegend=True,
                hovertemplate="<b>%{text}</b><br>Spend: %{x:.1f}%<br>Risk: %{y:.2f}/5<extra></extra>",
            ))
        fig_kj.add_vline(x=20, line_dash="dash", line_color="rgba(148,163,184,.35)", line_width=1)
        fig_kj.add_hline(y=3.0, line_dash="dash", line_color="rgba(148,163,184,.35)", line_width=1)
        fig_kj.update_layout(
            title="Kraljic Portfolio Matrix", xaxis_title="Spend share % (business impact)",
            yaxis_title="Weighted risk score (1-5)", yaxis_range=[1, 5], xaxis_range=[0, max(100, df_kj["Spend %"].max()*1.15)],
            height=420, showlegend=True,
        )
        st.plotly_chart(apply_chart_theme(fig_kj, 420), use_container_width=True, config={"displayModeBar": False})

        # Strategy table
        strategies = {
            "Strategic":    "Partnership approach — long-term contracts, joint development, executive relationship",
            "Leverage":     "Competitive bidding — multiple suppliers, volume leverage, price benchmarking",
            "Bottleneck":   "Supply assurance — safety stock, dual-source development, supplier development",
            "Non-critical": "Efficiency — catalog buying, e-procurement, demand aggregation",
        }
        rows_s = [{"Quadrant": k, "Recommended Strategy": v} for k, v in strategies.items()]
        st.dataframe(pd.DataFrame(rows_s), use_container_width=True, hide_index=True)


# ── BATNA / ZOPA Negotiation Calculator ──────────────────────────────────────

def render_batna_zopa(total: Dict, country_inputs: Dict, proposal_inputs: Dict, supplier_focus_df: pd.DataFrame, currency: str):
    """BATNA/ZOPA negotiation calculator with lever quantification."""
    with st.expander("🤝 BATNA / ZOPA negotiation calculator", expanded=False):
        st.caption("Quantify your walk-away price and the zone of possible agreement before entering negotiations.")

        # Anchor: current economic TCO
        current_econ = float(total.get("Current Economic Total", 0.0))
        new_econ = float(total.get("New Economic Total", 0.0))
        current_spend = float(total.get("Current Spend", 0.0))

        b1, b2, b3 = st.columns(3)
        with b1:
            max_acceptable_increase_pct = st.number_input(
                "Max acceptable cost increase vs current (%)", min_value=0.0, max_value=50.0,
                value=5.0, step=0.5, format="%.1f", key="batna_max_increase",
                help="If proposals cost more than current + this %, you walk away or re-tender.",
            )
        with b2:
            supplier_min_margin_pct = st.number_input(
                "Supplier estimated min. margin %", min_value=0.0, max_value=60.0,
                value=12.0, step=0.5, format="%.1f", key="batna_sup_margin",
                help="Typical margin for this category. Defines how far supplier can move.",
            )
        with b3:
            should_cost_est = st.number_input(
                f"Should-cost estimate ({currency})", min_value=0.0,
                value=float(current_spend * 0.90), step=float(current_spend * 0.01),
                format="%.2f", key="batna_should_cost",
                help="Your clean-sheet estimate of what the product/service should cost.",
            )

        # Calculations
        buyer_batna = current_econ * (1 + max_acceptable_increase_pct / 100.0)
        supplier_batna = should_cost_est * (1 + supplier_min_margin_pct / 100.0)
        zopa_low = min(buyer_batna, supplier_batna)
        zopa_high = max(buyer_batna, supplier_batna)
        deal_possible = buyer_batna >= supplier_batna
        midpoint = (buyer_batna + supplier_batna) / 2.0

        color_deal = "#34d399" if deal_possible else "#f87171"
        zopa_label = "✅ ZOPA exists — deal is theoretically possible" if deal_possible else "⚠ No ZOPA — buyer limit < supplier minimum (re-scope or re-spec needed)"

        st.markdown(
            f"""<div class="v46-svc-result" style="border-color:{color_deal}30">
            <b>Buyer BATNA (walk-away):</b> {fmt_money(buyer_batna, currency, compact=True)} &nbsp;·&nbsp;
            <b>Supplier BATNA estimate:</b> {fmt_money(supplier_batna, currency, compact=True)} &nbsp;·&nbsp;
            <b>Midpoint / fair deal:</b> {fmt_money(midpoint, currency, compact=True)} &nbsp;·&nbsp;
            <b style="color:{color_deal}">{zopa_label}</b>
            </div>""",
            unsafe_allow_html=True,
        )

        # Visualize ZOPA
        if PLOTLY_AVAILABLE:
            fig_z = go.Figure()
            fig_z.add_trace(go.Scatter(
                x=[supplier_batna, buyer_batna], y=[0.5, 0.5], mode="lines",
                line=dict(color=color_deal, width=14), opacity=0.35, showlegend=False,
            ))
            for x, lbl, col in [
                (supplier_batna, "Supplier min", "#f59e0b"),
                (midpoint, "Midpoint", "#60a5fa"),
                (buyer_batna, "Buyer walk-away", "#ef4444"),
                (new_econ, "Current proposal", "#94a3b8"),
            ]:
                fig_z.add_vline(x=x, line_dash="dot", line_color=col, line_width=1.5,
                                annotation_text=lbl, annotation_font_color=col, annotation_position="top")
            fig_z.update_layout(
                title="ZOPA zone visualization", xaxis_title=f"Economic total ({currency})",
                yaxis_visible=False, height=200, margin=dict(l=30,r=30,t=50,b=30),
            )
            st.plotly_chart(apply_chart_theme(fig_z, 200), use_container_width=True, config={"displayModeBar": False})

        # Negotiation lever table
        st.markdown("<div class='v46-plain-title'>💡 Negotiation lever quantification</div>", unsafe_allow_html=True)
        st.caption("Each lever quantified in annual $ value based on the current scenario inputs.")
        lever_rows = []
        avg_fin_rate = float(total.get("New Avg Financial Rate", 0.0))
        avg_treasury_rate = float(total.get("New Avg Treasury Rate", 0.0))
        avg_inv_rate_pct = sum(float(country_inputs[c].get("inventory_carry_rate_pct", 0.0)) for c in COUNTRIES) / max(len(COUNTRIES), 1)
        new_spend = float(total.get("New Spend", 0.0))
        avg_ref_days = sum(float(country_inputs[c].get("financial_reference_days", 60)) for c in COUNTRIES) / max(len(COUNTRIES), 1)

        levers = [
            ("Payment term +30 days",    new_spend * avg_fin_rate * (30 / max(avg_ref_days, 1))),
            ("Payment term +60 days",    new_spend * avg_fin_rate * (60 / max(avg_ref_days, 1))),
            ("Price reduction 1%",       new_spend * 0.01),
            ("Price reduction 3%",       new_spend * 0.03),
            ("Lead time -30 days",       new_spend * (avg_inv_rate_pct / 100.0) * (30 / 360.0)),
            ("Volume rebate 1% (annual)",new_spend * 0.01),
            ("MOQ reduction 50%",        new_spend * (avg_inv_rate_pct / 100.0) * 0.25),
        ]
        for lbl, val in levers:
            lever_rows.append({"Lever": lbl, "Annual value": fmt_money(val, currency, compact=True), "Direction": "Buyer benefit"})
        st.dataframe(pd.DataFrame(lever_rows), use_container_width=True, hide_index=True)


# ── Concentration Risk ────────────────────────────────────────────────────────

def render_concentration_risk(supplier_df: pd.DataFrame, total: Dict, country_inputs: Dict, proposal_inputs: Dict, supplier_risk: Dict, method: str, currency: str, threshold_pct: float = 60.0):
    """HHI + concentration alerts + single-source stress test."""
    if supplier_df.empty:
        return
    with st.expander("⚠ Concentration risk & supply chain stress test", expanded=False):
        # HHI per country
        hhi_rows = []
        alerts = []
        for c in COUNTRIES:
            c_rows = supplier_df[supplier_df["Country"] == c]
            if c_rows.empty:
                continue
            total_spend_c = c_rows["Allocated Spend"].sum()
            if total_spend_c <= 0:
                continue
            shares_sq = sum((row["Allocated Spend"] / total_spend_c * 100) ** 2 for _, row in c_rows.iterrows())
            hhi = shares_sq
            top_row = c_rows.nlargest(1, "Allocated Spend").iloc[0]
            top_share = safe_divide(top_row["Allocated Spend"], total_spend_c) * 100
            hhi_label = "Low" if hhi < 1500 else ("Moderate" if hhi < 2500 else "High concentration")
            hhi_rows.append({"Country": c, "HHI": f"{hhi:.0f}", "Concentration": hhi_label, "Top supplier": top_row["Supplier"], "Top share %": f"{top_share:.1f}%"})
            if top_share > threshold_pct:
                alerts.append(f"⚠ {c}: {top_row['Supplier']} holds {top_share:.1f}% — above {threshold_pct:.0f}% threshold")

        if alerts:
            for a in alerts:
                st.warning(a)
        st.dataframe(pd.DataFrame(hhi_rows), use_container_width=True, hide_index=True)

        # Single-source stress test
        st.markdown("<div class='v46-plain-title'>🔴 Single-source failure stress test</div>", unsafe_allow_html=True)
        st.caption("Simulates the economic impact if the selected supplier is removed and volume reallocated proportionally among remaining approved suppliers.")
        if SUPPLIERS:
            stressed_sup = st.selectbox("Supplier to remove", options=SUPPLIERS, format_func=lambda s: supplier_display_name(s), key="stress_sup")
            try:
                import copy
                # Reallocate: remove stressed supplier, proportional reallocation
                mins_s = get_min_shares(); maxs_s = get_max_shares()
                stress_shares = {}
                for c in COUNTRIES:
                    original = {s: float(st.session_state.get(share_key(c, s), DEFAULT_SHARES[c][s])) for s in SUPPLIERS}
                    removed_share = original.get(stressed_sup, 0.0)
                    others = {s: v for s, v in original.items() if s != stressed_sup}
                    others_total = sum(others.values()) or 1.0
                    # Distribute removed share proportionally
                    reallocated = {s: v + (v / others_total) * removed_share for s, v in others.items()}
                    reallocated[stressed_sup] = 0.0
                    stress_shares[c] = reallocated
                # Override spend to use next-best average price (proxy: 10% premium)
                pi_stress = copy.deepcopy(proposal_inputs)
                for c in COUNTRIES:
                    if stressed_sup in pi_stress[c]:
                        pi_stress[c][stressed_sup]["spend"] = pi_stress[c][stressed_sup]["spend"] * 1.10  # 10% emergency premium
                _, _, _, stress_total = calc_scenario(stress_shares, country_inputs, pi_stress, supplier_risk, method)
                base_total_val = float(total.get("New Economic Total", 0.0))
                stress_total_val = float(stress_total.get("New Economic Total", 0.0))
                stress_delta = stress_total_val - base_total_val
                col_stress = "#f87171" if stress_delta > 0 else "#34d399"
                st.markdown(
                    f"""<div class="v46-svc-result" style="border-color:#ef444430">
                    <b>Current economic total:</b> {fmt_money(base_total_val, currency, compact=True)} &nbsp;·&nbsp;
                    <b>After {supplier_display_name(stressed_sup)} failure:</b> {fmt_money(stress_total_val, currency, compact=True)} &nbsp;·&nbsp;
                    <b style="color:{col_stress}">Impact: {fmt_money(stress_delta, currency, compact=True, signed=True)}</b> &nbsp;·&nbsp;
                    Risk level: {"🔴 Critical" if stress_delta > base_total_val * 0.05 else "🟡 Moderate" if stress_delta > 0 else "🟢 Manageable"}
                    </div>""",
                    unsafe_allow_html=True,
                )
            except Exception as ex:
                st.warning(f"Stress test calculation failed: {ex}")


# ─────────────────────────────────────────────────────────────────────────────
# LOGISTICS ROUTE TCO ENGINE
# ─────────────────────────────────────────────────────────────────────────────

# ── Brazilian road risk zones (for escort/security cost) ─────────────────────
ROAD_RISK_ZONES = {
    "Alto Risco — RJ / Grande Rio":           {"escort_required": True,  "gris_min_pct": 0.40, "insurance_multiplier": 1.8, "risk_score": 4.5},
    "Alto Risco — ES (Serra / Vitória)":      {"escort_required": True,  "gris_min_pct": 0.35, "insurance_multiplier": 1.6, "risk_score": 4.2},
    "Médio Risco — SP Interior / rodovias":   {"escort_required": False, "gris_min_pct": 0.20, "insurance_multiplier": 1.2, "risk_score": 2.8},
    "Médio Risco — MG / BR-381":              {"escort_required": False, "gris_min_pct": 0.25, "insurance_multiplier": 1.3, "risk_score": 3.0},
    "Médio Risco — NE (BA / PE / CE)":        {"escort_required": False, "gris_min_pct": 0.25, "insurance_multiplier": 1.3, "risk_score": 3.2},
    "Médio Risco — Norte / AM / PA":          {"escort_required": False, "gris_min_pct": 0.30, "insurance_multiplier": 1.4, "risk_score": 3.5},
    "Baixo Risco — SP Capital / SPTV":        {"escort_required": False, "gris_min_pct": 0.15, "insurance_multiplier": 1.1, "risk_score": 2.2},
    "Baixo Risco — Sul / PR / SC / RS":       {"escort_required": False, "gris_min_pct": 0.12, "insurance_multiplier": 1.0, "risk_score": 1.8},
    "Baixo Risco — GO / DF / agro corridors": {"escort_required": False, "gris_min_pct": 0.12, "insurance_multiplier": 1.0, "risk_score": 1.9},
    "Internacional / cross-border":           {"escort_required": False, "gris_min_pct": 0.30, "insurance_multiplier": 1.5, "risk_score": 3.0},
}

# ── Brazilian state toll references (R$/100km average) ───────────────────────
TOLL_BENCHMARK_PER_100KM = {
    "SP — Autoban / CCR":    18.50, "SP — Ecopistas / Ecovias": 16.80,
    "PR — Ecorodovias":      14.20, "RS — DAER":                 8.50,
    "SC — SC Rodovias":       9.00, "MG — Autopistas":          12.00,
    "RJ — CCR RJO":          22.00, "ES — rodovias estaduais":  10.00,
    "GO / DF — BR federais":  7.50, "NE — rodovias federais":    6.00,
    "Norte / CO (AM/PA/MT)":  4.00, "Internacional":            15.00,
    "Personalizado":           0.0,
}

# ── Emission factors kg CO2e per km by vehicle type ─────────────────────────
EMISSION_FACTORS_KG_CO2E_KM = {
    "Van / Sprinter (até 3,5t)":        0.21,
    "VUC (até 6t — restrição urbana)":  0.28,
    "Toco (até 13t)":                   0.55,
    "Truck (até 23t)":                  0.75,
    "Carreta LS (até 33t)":             0.92,
    "Bitrem (até 57t)":                 1.15,
    "Rodotrem (até 74t)":               1.30,
    "Refrigerado / temperatura controlada": 1.05,
    "Container 20' / 40'":              0.95,
}

# ── Route optimizer: Brazilian main logistics hubs (lat/lon) ─────────────────
BR_LOGISTICS_HUBS = {
    # Grandes centros
    "São Paulo - SP (capital)":        (-23.5505, -46.6333),
    "Guarulhos - SP (Aeroporto GRU)":  (-23.4543, -46.5337),
    "Campinas - SP":                   (-22.9068, -47.0626),
    "São José dos Campos - SP":        (-23.1791, -45.8869),
    "Sorocaba - SP":                   (-23.5015, -47.4580),
    "Ribeirão Preto - SP":             (-21.1767, -47.8208),
    "Rio de Janeiro - RJ":             (-22.9068, -43.1729),
    "Duque de Caxias - RJ":            (-22.7856, -43.3117),
    "Belo Horizonte - MG":             (-19.9167, -43.9345),
    "Contagem - MG":                   (-19.9314, -44.0535),
    "Curitiba - PR":                   (-25.4284, -49.2733),
    "Porto Alegre - RS":               (-30.0346, -51.2177),
    "Novo Hamburgo - RS":              (-29.6783, -51.1333),
    "Florianópolis - SC":              (-27.5954, -48.5480),
    "Joinville - SC":                  (-26.3045, -48.8487),
    "Salvador - BA":                   (-12.9777, -38.5016),
    "Recife - PE":                     (-8.0476,  -34.8770),
    "Fortaleza - CE":                  (-3.7172,  -38.5431),
    "Manaus - AM":                     (-3.1190,  -60.0217),
    "Belém - PA":                      (-1.4558,  -48.4902),
    "Brasília - DF":                   (-15.7942, -47.8825),
    "Goiânia - GO":                    (-16.6869, -49.2648),
    "Uberlândia - MG":                 (-18.9186, -48.2772),
    "Vitória - ES":                    (-20.3155, -40.3128),
    "Porto Velho - RO":                (-8.7612,  -63.9004),
    "Palmas - TO":                     (-10.2491, -48.3243),
    # Hubs logísticos / CD importantes
    "Extrema - MG (hub logístico)":    (-22.8562, -46.3183),
    "Cajamar - SP (CD)":               (-23.3560, -46.8773),
    "Embu das Artes - SP":             (-23.6533, -46.8510),
    "Cariacica - ES (hub)":            (-20.2636, -40.4167),
    "Esteio - RS (hub)":               (-29.8605, -51.1807),
    "Maracanaú - CE (hub)":            (-3.8769,  -38.6268),
    # Internacional
    "Buenos Aires - AR":               (-34.6037, -58.3816),
    "Montevidéu - UY":                 (-34.9011, -56.1645),
    "Assunção - PY":                   (-25.2867, -57.6470),
    "Santiago - CL":                   (-33.4489, -70.6693),
    "Bogotá - CO":                     (4.7110,   -74.0721),
    "Lima - PE":                       (-12.0464, -77.0428),
    "Cidade do México - MX":           (19.4326,  -99.1332),
    "Miami - USA":                     (25.7617,  -80.1918),
    "Personalizado (lat/lon manual)":  (0.0,       0.0),
}

# ── Security cost model ───────────────────────────────────────────────────────
ESCORT_COST_PER_KM = {
    "Motocicleta (1 moto)":      3.50,
    "Carro de escolta (1 veículo)": 8.00,
    "Escolta armada dupla":      16.00,
    "Escolta armada + moto":     18.00,
}

CARGO_RISK_AD_VALOREM = {
    "Padrão / Geral (baixo valor)":         0.10,
    "Médio valor (R$50K–R$300K por embarque)": 0.20,
    "Alto valor (R$300K–R$1M por embarque)":   0.35,
    "Muito alto valor / eletrônicos (>R$1M)":  0.60,
    "Frágil / perecível":                   0.25,
    "Perigoso (IMDG / ADR)":                0.30,
    "Farmacêutico / GDP":                   0.28,
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def road_distance_factor(route_type: str) -> float:
    """Multiply straight-line distance by this factor to estimate road km."""
    return {"Inbound to Warehouse (fornecedor → armazém)": 1.30,
            "Middle Mile / Transfer (FC → CD / cross-dock)": 1.20,
            "Outbound B2B (armazém → lojas / hubs)": 1.35,
            "Last Mile Injection (armazém → delivery station)": 1.40,
            "Reverse Logistics (devoluções → armazém)": 1.30,
            "Shuttle / Yard Movement (transferências internas)": 1.10,
            "Dedicated Lane (rota fixa recorrente)": 1.25,
            "Spot / On-demand (frete sob demanda)": 1.35,
            }.get(route_type, 1.30)


def calc_route_tco(params: Dict) -> Dict:
    """
    Full Route TCO calculation.
    Returns every cost component + unit economics + risk-adjusted total.
    """
    # ── Unpack ────────────────────────────────────────────────────────────
    dist_one_way        = float(params.get("distance_km", 0.0))
    empty_pct           = float(params.get("empty_km_pct", 20.0)) / 100.0
    round_trip          = bool(params.get("round_trip", True))
    shipments_month     = float(params.get("shipments_month", 0.0))
    pallets_per_ship    = float(params.get("pallets_per_shipment", 0.0))
    kg_per_ship         = float(params.get("kg_per_shipment", 0.0))
    m3_per_ship         = float(params.get("m3_per_shipment", 0.0))
    orders_per_ship     = float(params.get("orders_per_shipment", 1.0))
    vehicle_kg_cap      = float(params.get("vehicle_kg_capacity", 23_000.0))
    vehicle_pallet_cap  = float(params.get("vehicle_pallet_capacity", 26.0))
    vehicle_m3_cap      = float(params.get("vehicle_m3_capacity", 90.0))
    # Fixed costs / month
    vehicle_fixed_month = float(params.get("vehicle_fixed_monthly", 0.0))
    driver_monthly      = float(params.get("driver_monthly_cost", 0.0))
    driver_benefits_pct = float(params.get("driver_benefits_pct", 70.0)) / 100.0
    helper_monthly      = float(params.get("helper_monthly_cost", 0.0))
    tracking_monthly    = float(params.get("tracking_monthly", 0.0))
    overhead_pct        = float(params.get("carrier_overhead_pct", 12.0)) / 100.0
    margin_pct          = float(params.get("carrier_margin_pct", 10.0)) / 100.0
    # Variable costs / km
    fuel_consump_kml    = float(params.get("fuel_consumption_kml", 3.5))
    diesel_price        = float(params.get("diesel_price_per_l", 6.50))
    maintenance_km      = float(params.get("maintenance_cost_per_km", 0.18))
    tire_km             = float(params.get("tire_cost_per_km", 0.08))
    toll_per_100km      = float(params.get("toll_per_100km", 10.0))
    # Cargo / insurance
    cargo_value_per_ship = float(params.get("cargo_value_per_shipment", 0.0))
    ad_valorem_pct      = float(params.get("ad_valorem_pct", 0.20)) / 100.0
    gris_pct            = float(params.get("gris_pct", 0.20)) / 100.0
    # Accessorials
    detention_rate_hr   = float(params.get("detention_rate_per_hour", 0.0))
    avg_dwell_hrs       = float(params.get("avg_dwell_hours", 1.5))
    free_dwell_hrs      = float(params.get("free_dwell_hours", 2.0))
    redelivery_pct      = float(params.get("redelivery_rate_pct", 2.0)) / 100.0
    redelivery_cost     = float(params.get("redelivery_cost_per_event", 0.0))
    failed_pickup_pct   = float(params.get("failed_pickup_pct", 1.0)) / 100.0
    failed_pickup_cost  = float(params.get("failed_pickup_cost", 0.0))
    extra_stop_cost     = float(params.get("extra_stop_cost", 0.0))
    weekend_night_pct   = float(params.get("weekend_night_pct", 10.0)) / 100.0
    weekend_surcharge   = float(params.get("weekend_night_surcharge_pct", 25.0)) / 100.0
    lumper_per_ship     = float(params.get("lumper_cost_per_shipment", 0.0))
    # Security / escort
    escort_required     = bool(params.get("escort_required", False))
    escort_cost_km      = float(params.get("escort_cost_per_km", 8.0))
    escort_trips_pct    = float(params.get("escort_pct_of_trips", 100.0)) / 100.0
    # Warehouse interface
    dock_cost_per_hr    = float(params.get("dock_cost_per_hour", 0.0))
    loading_hrs         = float(params.get("loading_hours_per_trip", 1.0))
    unloading_hrs       = float(params.get("unloading_hours_per_trip", 1.0))
    warehouse_labor     = float(params.get("warehouse_labor_per_shipment", 0.0))
    # Risk
    otif_pct            = float(params.get("otif_pct", 95.0)) / 100.0
    tender_acc_pct      = float(params.get("tender_acceptance_pct", 90.0)) / 100.0
    backup_rate_premium = float(params.get("backup_rate_premium_pct", 22.0)) / 100.0
    damage_rate_pct     = float(params.get("damage_rate_pct", 0.3)) / 100.0
    no_show_pct         = float(params.get("no_show_pct", 1.5)) / 100.0
    spot_premium        = float(params.get("spot_emergency_premium_pct", 35.0)) / 100.0
    # Inventory / lead time
    lead_time_days      = float(params.get("transit_time_days", 1.0))
    lead_time_sigma     = float(params.get("lead_time_sigma_days", 0.3))
    daily_demand_value  = float(params.get("daily_demand_value", 0.0))
    inv_carry_rate      = float(params.get("inventory_carry_rate_pct", 20.0)) / 100.0
    z_score             = 1.65  # 95% service level
    # ESG
    emission_factor     = float(params.get("emission_factor_kgco2e_km", 0.75))
    carbon_price_ton    = float(params.get("carbon_price_per_ton", 30.0))
    # Ramp-up
    ramp_up_months      = int(params.get("ramp_up_months", 0))
    ramp_up_volume_pct  = float(params.get("ramp_up_avg_volume_pct", 50.0)) / 100.0

    # ── Distance model ────────────────────────────────────────────────────
    dist_loaded = dist_one_way * (2.0 if round_trip else 1.0)
    dist_empty  = dist_loaded * empty_pct
    dist_total  = dist_loaded + dist_empty
    annual_shipments = shipments_month * 12.0

    # ── Load factors ──────────────────────────────────────────────────────
    lf_weight  = safe_divide(kg_per_ship, vehicle_kg_cap) if vehicle_kg_cap > 0 else 0.0
    lf_pallet  = safe_divide(pallets_per_ship, vehicle_pallet_cap) if vehicle_pallet_cap > 0 else 0.0
    lf_volume  = safe_divide(m3_per_ship, vehicle_m3_cap) if vehicle_m3_cap > 0 else 0.0
    load_factor = max(lf_weight, lf_pallet, lf_volume)

    # ── Trip variable cost ────────────────────────────────────────────────
    fuel_per_trip  = safe_divide(dist_total, fuel_consump_kml) * diesel_price
    toll_per_trip  = dist_total * toll_per_100km / 100.0
    maint_per_trip = dist_total * maintenance_km
    tire_per_trip  = dist_total * tire_km

    # ── Cargo insurance per shipment ──────────────────────────────────────
    ad_valorem_per_ship = cargo_value_per_ship * ad_valorem_pct
    gris_per_ship       = cargo_value_per_ship * gris_pct

    # ── Accessorials per shipment ─────────────────────────────────────────
    detention_cost = max(0.0, avg_dwell_hrs - free_dwell_hrs) * detention_rate_hr
    redelivery_per_ship = redelivery_pct * redelivery_cost
    failed_per_ship     = failed_pickup_pct * failed_pickup_cost
    weekend_cost        = weekend_night_pct * weekend_surcharge  # fraction of base rate
    accessorial_total   = detention_cost + redelivery_per_ship + failed_per_ship + extra_stop_cost + lumper_per_ship
    accessorial_pct_of_base = safe_divide(accessorial_total, fuel_per_trip + toll_per_trip + maint_per_trip + tire_per_trip)

    # ── Security / escort per shipment ────────────────────────────────────
    escort_per_trip = dist_loaded * escort_cost_km * escort_trips_pct if escort_required else 0.0

    # ── Warehouse interface per shipment ──────────────────────────────────
    dock_cost   = (loading_hrs + unloading_hrs) * dock_cost_per_hr
    dwell_cost  = dock_cost_per_hr * min(avg_dwell_hrs, free_dwell_hrs) + detention_cost
    wh_total    = dock_cost + warehouse_labor

    # ── Variable trip cost ─────────────────────────────────────────────────
    trip_variable = fuel_per_trip + toll_per_trip + maint_per_trip + tire_per_trip + ad_valorem_per_ship + gris_per_ship + escort_per_trip + accessorial_total + wh_total

    # ── Fixed cost allocation per shipment ────────────────────────────────
    monthly_fixed_total = (
        vehicle_fixed_month
        + driver_monthly * (1 + driver_benefits_pct)
        + helper_monthly
        + tracking_monthly
    ) * (1 + overhead_pct)
    fixed_per_ship = safe_divide(monthly_fixed_total, max(shipments_month, 1.0))

    # ── Should-cost per shipment (before margin) ───────────────────────────
    should_cost_per_ship = (trip_variable + fixed_per_ship)
    trip_cost_with_margin = should_cost_per_ship * (1 + margin_pct)

    # ── Risk costs ────────────────────────────────────────────────────────
    sla_gap = max(0.0, 0.98 - otif_pct)
    spot_overflow_cost = (1.0 - tender_acc_pct) * trip_cost_with_margin * backup_rate_premium
    no_show_cost       = no_show_pct * trip_cost_with_margin * spot_premium
    damage_cost        = damage_rate_pct * cargo_value_per_ship
    risk_total_per_ship = spot_overflow_cost + no_show_cost + damage_cost
    risk_annual        = risk_total_per_ship * annual_shipments

    # ── Blended rate (primary × acc% + backup × (1-acc%)) ────────────────
    blended_rate = trip_cost_with_margin * tender_acc_pct + trip_cost_with_margin * (1 + backup_rate_premium) * (1 - tender_acc_pct)

    # ── Inventory / working capital impact ────────────────────────────────
    pipeline_inv = daily_demand_value * lead_time_days
    safety_stock_days = z_score * lead_time_sigma
    safety_stock_value = daily_demand_value * safety_stock_days
    inv_carry_cost_annual = (pipeline_inv + safety_stock_value) * inv_carry_rate

    # ── ESG cost ─────────────────────────────────────────────────────────
    co2e_per_trip_kg = dist_total * emission_factor
    co2e_annual_ton  = co2e_per_trip_kg * annual_shipments / 1000.0
    carbon_cost_annual = co2e_annual_ton * carbon_price_ton

    # ── Annual route TCO ─────────────────────────────────────────────────
    annual_base_tco   = blended_rate * annual_shipments + monthly_fixed_total * 12.0
    risk_adj_tco      = annual_base_tco + risk_annual + inv_carry_cost_annual + carbon_cost_annual

    # ── Ramp-up adjustment ────────────────────────────────────────────────
    if ramp_up_months > 0:
        steady_months = max(0, 12 - ramp_up_months)
        ramp_annual = (risk_adj_tco / 12.0) * (ramp_up_months * ramp_up_volume_pct + steady_months)
    else:
        ramp_annual = risk_adj_tco

    # ── Unit economics ────────────────────────────────────────────────────
    ann_ship = max(annual_shipments, 1.0)
    ann_pal  = max(pallets_per_ship * annual_shipments, 1.0)
    ann_kg   = max(kg_per_ship * annual_shipments, 1.0)
    ann_m3   = max(m3_per_ship * annual_shipments, 1.0)
    ann_ord  = max(orders_per_ship * annual_shipments, 1.0)

    # ── Dedicated vs Spot breakeven ───────────────────────────────────────
    # At what monthly volume does dedicated become cheaper than spot?
    spot_rate_per_ship = trip_variable * (1 + margin_pct) * (1 + spot_premium)
    if spot_rate_per_ship > trip_cost_with_margin * 1e-9:
        breakeven_monthly = safe_divide(monthly_fixed_total, spot_rate_per_ship - (trip_variable * (1 + margin_pct)))
    else:
        breakeven_monthly = float("inf")

    return {
        # Distance
        "distance_loaded_km": dist_loaded, "distance_empty_km": dist_empty, "distance_total_km": dist_total,
        # Load factors
        "load_factor_weight": lf_weight, "load_factor_pallet": lf_pallet, "load_factor_volume": lf_volume, "load_factor_effective": load_factor,
        # Trip variable cost
        "fuel_per_trip": fuel_per_trip, "toll_per_trip": toll_per_trip, "maint_per_trip": maint_per_trip,
        "tire_per_trip": tire_per_trip, "ad_valorem_per_ship": ad_valorem_per_ship, "gris_per_ship": gris_per_ship,
        "escort_per_trip": escort_per_trip, "accessorial_total_per_trip": accessorial_total,
        "wh_interface_per_trip": wh_total, "detention_per_trip": detention_cost,
        "trip_variable_cost": trip_variable,
        # Fixed
        "monthly_fixed_total": monthly_fixed_total, "fixed_per_shipment": fixed_per_ship,
        # Should-cost
        "should_cost_per_shipment": should_cost_per_ship, "trip_cost_with_margin": trip_cost_with_margin,
        "blended_rate_per_shipment": blended_rate,
        # Risk
        "spot_overflow_cost_per_ship": spot_overflow_cost, "no_show_cost_per_ship": no_show_cost,
        "damage_cost_per_ship": damage_cost, "risk_cost_per_shipment": risk_total_per_ship,
        "risk_annual": risk_annual,
        # Inventory
        "pipeline_inventory_value": pipeline_inv, "safety_stock_value": safety_stock_value,
        "safety_stock_days": safety_stock_days, "inv_carry_cost_annual": inv_carry_cost_annual,
        # ESG
        "co2e_per_trip_kg": co2e_per_trip_kg, "co2e_annual_ton": co2e_annual_ton, "carbon_cost_annual": carbon_cost_annual,
        # Annual TCO
        "annual_base_tco": annual_base_tco, "risk_adj_tco": risk_adj_tco, "ramp_adjusted_tco": ramp_annual,
        # Accessorials
        "accessorial_leakage_pct": accessorial_pct_of_base,
        # Unit economics
        "cost_per_shipment": risk_adj_tco / ann_ship,
        "cost_per_pallet":   risk_adj_tco / ann_pal if ann_pal > 1 else 0.0,
        "cost_per_kg":       risk_adj_tco / ann_kg   if ann_kg > 1 else 0.0,
        "cost_per_m3":       risk_adj_tco / ann_m3   if ann_m3 > 1 else 0.0,
        "cost_per_order":    risk_adj_tco / ann_ord,
        # Breakeven
        "dedicated_vs_spot_breakeven_monthly": breakeven_monthly,
        "spot_rate_per_shipment": spot_rate_per_ship,
        "dedicated_better": shipments_month >= breakeven_monthly if breakeven_monthly != float("inf") else False,
    }


def render_logistics_route_tco(*, key_prefix: str, country: str, supplier_label: str, reporting_currency: str, is_baseline: bool = False) -> Dict:
    """
    Full Logistics Route TCO input UI.
    Returns a dict compatible with service_profile used by the TCO engine.
    """
    cfg = SERVICE_SCOPE_CONFIG["Logistics / Transport Services"]

    # ── Block 1: Route & Demand Setup ───────────────────────────────────
    render_breaker("Route & Demand Setup", "Origem, destino, tipo de rota, distância, volume, veículo", "🗺️", "#10b981", "Route profile")
    r1 = st.columns([1.2, .9, .9, .8])
    with r1[0]:
        route_type = st.selectbox(f"{supplier_label} | Tipo de rota", options=cfg["route_types"], key=f"{key_prefix}__route_type")
    with r1[1]:
        vehicle_type = st.selectbox(f"{supplier_label} | Tipo de veículo", options=cfg["vehicle_types"], key=f"{key_prefix}__vehicle_type")
    with r1[2]:
        cargo_risk = st.selectbox(f"{supplier_label} | Perfil de carga / risco", options=cfg["cargo_risk_levels"], key=f"{key_prefix}__cargo_risk")
    with r1[3]:
        road_zone = st.selectbox(f"{supplier_label} | Zona de risco da rota", options=list(ROAD_RISK_ZONES.keys()), key=f"{key_prefix}__road_zone")

    zone_info = ROAD_RISK_ZONES[road_zone]
    auto_escort = zone_info["escort_required"] or ("alto valor" in cargo_risk.lower()) or ("eletrônico" in cargo_risk.lower())
    gris_default = zone_info["gris_min_pct"]
    ad_val_default = CARGO_RISK_AD_VALOREM.get(cargo_risk, 0.20)
    ins_mult = zone_info["insurance_multiplier"]

    r2 = st.columns(6)
    with r2[0]: dist_km = st.number_input(f"{supplier_label} | Distância one-way (km)", min_value=0.0, value=300.0, step=10.0, key=f"{key_prefix}__distance_km")
    with r2[1]: round_trip = st.checkbox(f"Round-trip?", value=True, key=f"{key_prefix}__round_trip")
    with r2[2]: empty_pct = st.number_input(f"Empty km %", min_value=0.0, max_value=100.0, value=20.0, step=1.0, key=f"{key_prefix}__empty_pct", help="% da distância rodada sem carga (retorno vazio)")
    with r2[3]: shipments_month = st.number_input(f"Shipments / mês", min_value=0.0, value=40.0, step=1.0, key=f"{key_prefix}__shipments_month")
    with r2[4]: transit_time = st.number_input(f"Transit time (dias)", min_value=0.0, value=1.0, step=0.25, key=f"{key_prefix}__transit_time")
    with r2[5]: transit_sigma = st.number_input(f"Lead time σ (dias)", min_value=0.0, value=0.3, step=0.1, key=f"{key_prefix}__transit_sigma", help="Desvio padrão do lead time — determina safety stock necessário")

    r3 = st.columns(6)
    with r3[0]: pallets = st.number_input(f"Pallets / embarque", min_value=0.0, value=0.0, step=1.0, key=f"{key_prefix}__pallets")
    with r3[1]: kg_ship = st.number_input(f"Kg / embarque", min_value=0.0, value=0.0, step=100.0, key=f"{key_prefix}__kg_ship")
    with r3[2]: m3_ship = st.number_input(f"m³ / embarque", min_value=0.0, value=0.0, step=1.0, key=f"{key_prefix}__m3_ship")
    with r3[3]: orders = st.number_input(f"Orders / embarque", min_value=0.0, value=1.0, step=1.0, key=f"{key_prefix}__orders_ship")
    with r3[4]: cargo_value = st.number_input(f"Valor da carga / embarque ({reporting_currency})", min_value=0.0, value=0.0, step=10_000.0, key=f"{key_prefix}__cargo_value", help="Valor mercadoria — base para ad valorem, GRIS e seguro")
    with r3[5]: daily_demand_val = st.number_input(f"Valor demanda diária ({reporting_currency})", min_value=0.0, value=0.0, step=5_000.0, key=f"{key_prefix}__daily_demand_val", help="Para cálculo de pipeline inventory e safety stock")

    veh_cfg = {
        "Van / Sprinter (até 3,5t)":       (3_500, 8, 12),
        "VUC (até 6t — restrição urbana)": (6_000, 10, 18),
        "Toco (até 13t)":                  (13_000, 16, 45),
        "Truck (até 23t)":                 (23_000, 22, 70),
        "Carreta LS (até 33t)":            (27_000, 26, 90),
        "Bitrem (até 57t)":                (50_000, 42, 140),
        "Rodotrem (até 74t)":              (65_000, 52, 170),
    }.get(vehicle_type, (23_000, 26, 90))
    veh_kg_def, veh_pal_def, veh_m3_def = veh_cfg

    # ── Block 2: Carrier Pricing & Open Cost ─────────────────────────────
    with st.expander("💰 Carrier pricing, open cost & should-cost model", expanded=not is_baseline):
        st.caption("Rate model + vehicle fixed + fuel + driver + maintenance. Ferramenta calcula should-cost e gap vs cotação.")
        pr1 = st.columns([1.2, .9, .9, .9])
        with pr1[0]: pricing_model = st.selectbox(f"{supplier_label} | Pricing model", options=cfg["pricing_models"], key=f"{key_prefix}__pricing_model")
        with pr1[1]: contracted_rate = st.number_input(f"Rate cotado / embarque ({reporting_currency})", min_value=0.0, value=0.0, step=100.0, key=f"{key_prefix}__contracted_rate")
        with pr1[2]: fuel_surcharge_pct = st.number_input(f"Fuel surcharge %", min_value=0.0, value=8.0, step=0.5, key=f"{key_prefix}__fuel_surcharge_pct", help="% sobre o frete base para cobertura de diesel")
        with pr1[3]: contract_years = st.number_input(f"Contract years", min_value=1, max_value=5, value=2, step=1, key=f"{key_prefix}__contract_years")

        st.markdown("<div style='font-size:.78rem;font-weight:600;color:#94a3b8;margin:10px 0 4px'>Open-cost model (should-cost)</div>", unsafe_allow_html=True)
        oc1 = st.columns(5)
        with oc1[0]: veh_fixed = st.number_input(f"Custo fixo veículo/mês", min_value=0.0, value=0.0, step=500.0, key=f"{key_prefix}__vehicle_fixed")
        with oc1[1]: driver_cost = st.number_input(f"Salário motorista/mês", min_value=0.0, value=0.0, step=100.0, key=f"{key_prefix}__driver_cost")
        with oc1[2]: driver_benefits = st.number_input(f"Encargos/benefícios %", min_value=0.0, value=70.0, step=1.0, key=f"{key_prefix}__driver_benefits")
        with oc1[3]: helper_cost = st.number_input(f"Ajudante/mês", min_value=0.0, value=0.0, step=100.0, key=f"{key_prefix}__helper_cost")
        with oc1[4]: tracking_cost = st.number_input(f"Rastreamento/mês", min_value=0.0, value=200.0, step=50.0, key=f"{key_prefix}__tracking_cost")

        oc2 = st.columns(6)
        fuel_def = {"Van / Sprinter (até 3,5t)": 10.0, "VUC (até 6t — restrição urbana)": 7.0, "Toco (até 13t)": 5.0, "Truck (até 23t)": 4.0, "Carreta LS (até 33t)": 3.5, "Bitrem (até 57t)": 2.8, "Rodotrem (até 74t)": 2.5}.get(vehicle_type, 3.5)
        with oc2[0]: fuel_consump = st.number_input(f"Consumo km/l", min_value=0.5, value=fuel_def, step=0.1, key=f"{key_prefix}__fuel_consump")
        with oc2[1]: diesel_price = st.number_input(f"Preço diesel (R$/l)", min_value=0.0, value=6.50, step=0.05, key=f"{key_prefix}__diesel_price")
        with oc2[2]: maint_km = st.number_input(f"Manutenção (R$/km)", min_value=0.0, value=0.18, step=0.01, key=f"{key_prefix}__maint_km")
        with oc2[3]: tire_km = st.number_input(f"Pneus (R$/km)", min_value=0.0, value=0.08, step=0.01, key=f"{key_prefix}__tire_km")
        with oc2[4]: overhead_pct = st.number_input(f"Overhead %", min_value=0.0, value=12.0, step=1.0, key=f"{key_prefix}__overhead_pct")
        with oc2[5]: margin_pct = st.number_input(f"Margem transportadora %", min_value=0.0, value=10.0, step=1.0, key=f"{key_prefix}__margin_pct")

        toll_zone_default = TOLL_BENCHMARK_PER_100KM.get(list(TOLL_BENCHMARK_PER_100KM.keys())[0], 10.0)
        tc1 = st.columns(4)
        with tc1[0]: toll_region = st.selectbox(f"Região de pedágio", options=list(TOLL_BENCHMARK_PER_100KM.keys()), key=f"{key_prefix}__toll_region")
        with tc1[1]: toll_per_100 = st.number_input(f"Pedágio R$/100km", min_value=0.0, value=TOLL_BENCHMARK_PER_100KM[toll_region], step=0.5, key=f"{key_prefix}__toll_per_100km")
        with tc1[2]: veh_kg_cap = st.number_input(f"Capacidade kg", min_value=100.0, value=float(veh_kg_def), step=100.0, key=f"{key_prefix}__veh_kg_cap")
        with tc1[3]: veh_pal_cap = st.number_input(f"Capacidade pallets", min_value=1.0, value=float(veh_pal_def), step=1.0, key=f"{key_prefix}__veh_pal_cap")

    # ── Block 3: Cargo insurance, GRIS & security ─────────────────────────
    with st.expander("🔒 Seguro de carga, GRIS & escolta (Ad Valorem model)", expanded=False):
        st.caption(f"Zona: {road_zone} · Risk score: {zone_info['risk_score']}/5 · Escort auto-flag: {'✅ Sim' if auto_escort else '—'}. Ad valorem varia por valor e tipo da carga.")
        s1 = st.columns(5)
        with s1[0]: ad_valorem = st.number_input(f"Ad valorem % (seguro carga)", min_value=0.0, value=ad_val_default * ins_mult, step=0.01, format="%.3f", key=f"{key_prefix}__ad_valorem", help="% do valor da mercadoria por embarque")
        with s1[1]: gris = st.number_input(f"GRIS %", min_value=0.0, value=gris_default, step=0.01, format="%.3f", key=f"{key_prefix}__gris", help="Gerenciamento de Risco — % sobre valor declarado")
        with s1[2]: escort_req = st.checkbox(f"Escolta obrigatória?", value=auto_escort, key=f"{key_prefix}__escort_req")
        with s1[3]: escort_type = st.selectbox(f"Tipo de escolta", options=list(ESCORT_COST_PER_KM.keys()), key=f"{key_prefix}__escort_type", disabled=not escort_req)
        with s1[4]: escort_pct_trips = st.number_input(f"% viagens com escolta", min_value=0.0, max_value=100.0, value=100.0 if auto_escort else 0.0, step=5.0, key=f"{key_prefix}__escort_pct_trips")
        escort_cost_km_val = ESCORT_COST_PER_KM[escort_type] if escort_req else 0.0
        if escort_req and cargo_value > 0:
            escort_annual = dist_km * (2 if round_trip else 1) * escort_cost_km_val * (escort_pct_trips/100) * shipments_month * 12
            st.markdown(f"<div class='v46-landed'>🔒 <b>Escolta:</b> {reporting_currency} {escort_cost_km_val:.2f}/km · <b>Custo anual estimado:</b> {reporting_currency} {escort_annual:,.0f}</div>", unsafe_allow_html=True)

    # ── Block 4: Accessorials & warehouse interface ───────────────────────
    with st.expander("🏭 Accessorials, doca & warehouse interface", expanded=False):
        st.caption("Detention, demurrage, reentrega, parada extra, lumper, doca. Accessorial leakage > 8% = red flag.")
        a1 = st.columns(5)
        with a1[0]: detention_rate = st.number_input(f"Detention R$/hora", min_value=0.0, value=0.0, step=25.0, key=f"{key_prefix}__detention_rate")
        with a1[1]: free_dwell = st.number_input(f"Free dwell time (hrs)", min_value=0.0, value=2.0, step=0.25, key=f"{key_prefix}__free_dwell")
        with a1[2]: avg_dwell = st.number_input(f"Avg dwell time (hrs)", min_value=0.0, value=1.5, step=0.25, key=f"{key_prefix}__avg_dwell")
        with a1[3]: redelivery_pct_inp = st.number_input(f"Redelivery rate %", min_value=0.0, value=2.0, step=0.1, key=f"{key_prefix}__redelivery_pct")
        with a1[4]: redelivery_cost_inp = st.number_input(f"Custo reentrega", min_value=0.0, value=0.0, step=50.0, key=f"{key_prefix}__redelivery_cost")
        a2 = st.columns(5)
        with a2[0]: failed_pct = st.number_input(f"Failed pickup %", min_value=0.0, value=1.0, step=0.1, key=f"{key_prefix}__failed_pct")
        with a2[1]: failed_cost = st.number_input(f"Failed pickup cost", min_value=0.0, value=0.0, step=50.0, key=f"{key_prefix}__failed_cost")
        with a2[2]: extra_stop = st.number_input(f"Extra stop cost", min_value=0.0, value=0.0, step=50.0, key=f"{key_prefix}__extra_stop")
        with a2[3]: lumper = st.number_input(f"Lumper / embarque", min_value=0.0, value=0.0, step=20.0, key=f"{key_prefix}__lumper")
        with a2[4]: wh_labor = st.number_input(f"WH labor / embarque", min_value=0.0, value=0.0, step=20.0, key=f"{key_prefix}__wh_labor")
        a3 = st.columns(4)
        with a3[0]: dock_cost_hr = st.number_input(f"Doca R$/hora", min_value=0.0, value=0.0, step=25.0, key=f"{key_prefix}__dock_cost_hr")
        with a3[1]: loading_hrs = st.number_input(f"Tempo carga (hrs)", min_value=0.0, value=1.0, step=0.25, key=f"{key_prefix}__loading_hrs")
        with a3[2]: unloading_hrs = st.number_input(f"Tempo descarga (hrs)", min_value=0.0, value=1.0, step=0.25, key=f"{key_prefix}__unloading_hrs")
        with a3[3]: wn_pct = st.number_input(f"Weekend/noite % viagens", min_value=0.0, value=10.0, step=1.0, key=f"{key_prefix}__wn_pct")

    # ── Block 5: SLA, risk & ramp-up ──────────────────────────────────────
    with st.expander("📊 SLA, risk & ramp-up curve", expanded=False):
        sr1 = st.columns(5)
        with sr1[0]: otif = st.number_input(f"OTIF % esperado", min_value=0.0, max_value=100.0, value=95.0, step=0.1, key=f"{key_prefix}__otif")
        with sr1[1]: tender_acc = st.number_input(f"Tender acceptance %", min_value=0.0, max_value=100.0, value=90.0, step=1.0, key=f"{key_prefix}__tender_acc", help="% das viagens aceitas pela transportadora primária. Restante vai para backup/spot.")
        with sr1[2]: backup_prem = st.number_input(f"Backup premium %", min_value=0.0, value=22.0, step=1.0, key=f"{key_prefix}__backup_prem", help="Quanto a mais custa a transportadora backup vs primária")
        with sr1[3]: damage_rate = st.number_input(f"Damage rate %", min_value=0.0, value=0.3, step=0.05, key=f"{key_prefix}__damage_rate")
        with sr1[4]: no_show = st.number_input(f"No-show %", min_value=0.0, value=1.5, step=0.1, key=f"{key_prefix}__no_show")
        sr2 = st.columns(4)
        with sr2[0]: ramp_months = st.number_input(f"Ramp-up months (0=N/A)", min_value=0, max_value=11, value=0, step=1, key=f"{key_prefix}__ramp_months")
        with sr2[1]: ramp_vol_pct = st.number_input(f"Ramp-up avg volume %", min_value=0.0, max_value=100.0, value=50.0, step=5.0, key=f"{key_prefix}__ramp_vol_pct")
        with sr2[2]: inv_carry = st.number_input(f"Inventory carry rate %", min_value=0.0, value=20.0, step=0.5, key=f"{key_prefix}__inv_carry")
        with sr2[3]: carbon_price = st.number_input(f"Carbon price (USD/tCO₂e)", min_value=0.0, value=30.0, step=1.0, key=f"{key_prefix}__carbon_price")

    # ── Compute ───────────────────────────────────────────────────────────
    emission_factor_val = EMISSION_FACTORS_KG_CO2E_KM.get(vehicle_type, 0.75)
    tco_params = {
        "distance_km": float(dist_km), "empty_km_pct": float(empty_pct),
        "round_trip": bool(round_trip), "shipments_month": float(shipments_month),
        "pallets_per_shipment": float(pallets), "kg_per_shipment": float(kg_ship),
        "m3_per_shipment": float(m3_ship), "orders_per_shipment": float(orders),
        "vehicle_kg_capacity": float(veh_kg_cap), "vehicle_pallet_capacity": float(veh_pal_cap),
        "vehicle_m3_capacity": float(veh_m3_def),
        "vehicle_fixed_monthly": float(veh_fixed), "driver_monthly_cost": float(driver_cost),
        "driver_benefits_pct": float(driver_benefits), "helper_monthly_cost": float(helper_cost),
        "tracking_monthly": float(tracking_cost), "carrier_overhead_pct": float(overhead_pct),
        "carrier_margin_pct": float(margin_pct),
        "fuel_consumption_kml": float(fuel_consump), "diesel_price_per_l": float(diesel_price),
        "maintenance_cost_per_km": float(maint_km), "tire_cost_per_km": float(tire_km),
        "toll_per_100km": float(toll_per_100),
        "cargo_value_per_shipment": float(cargo_value), "ad_valorem_pct": float(ad_valorem),
        "gris_pct": float(gris),
        "escort_required": bool(escort_req if "escort_req" in dir() else auto_escort),
        "escort_cost_per_km": float(escort_cost_km_val),
        "escort_pct_of_trips": float(escort_pct_trips),
        "detention_rate_per_hour": float(detention_rate), "avg_dwell_hours": float(avg_dwell),
        "free_dwell_hours": float(free_dwell), "redelivery_rate_pct": float(redelivery_pct_inp),
        "redelivery_cost_per_event": float(redelivery_cost_inp), "failed_pickup_pct": float(failed_pct),
        "failed_pickup_cost": float(failed_cost), "extra_stop_cost": float(extra_stop),
        "lumper_cost_per_shipment": float(lumper), "warehouse_labor_per_shipment": float(wh_labor),
        "dock_cost_per_hour": float(dock_cost_hr), "loading_hours_per_trip": float(loading_hrs),
        "unloading_hours_per_trip": float(unloading_hrs), "weekend_night_pct": float(wn_pct),
        "otif_pct": float(otif), "tender_acceptance_pct": float(tender_acc),
        "backup_rate_premium_pct": float(backup_prem), "damage_rate_pct": float(damage_rate),
        "no_show_pct": float(no_show), "spot_emergency_premium_pct": 35.0,
        "transit_time_days": float(transit_time), "lead_time_sigma_days": float(transit_sigma),
        "daily_demand_value": float(daily_demand_val), "inventory_carry_rate_pct": float(inv_carry),
        "emission_factor_kgco2e_km": float(emission_factor_val), "carbon_price_per_ton": float(carbon_price),
        "ramp_up_months": int(ramp_months), "ramp_up_avg_volume_pct": float(ramp_vol_pct),
    }
    r = calc_route_tco(tco_params)

    # ── TCO result waterfall ───────────────────────────────────────────────
    wf_rows = [
        ("Trip variable cost / embarque",          r["trip_variable_cost"],          True),
        ("  ↳ Combustível",                        r["fuel_per_trip"],               r["fuel_per_trip"]>0),
        ("  ↳ Pedágios",                           r["toll_per_trip"],               r["toll_per_trip"]>0),
        ("  ↳ Manutenção + pneus",                 r["maint_per_trip"]+r["tire_per_trip"], (r["maint_per_trip"]+r["tire_per_trip"])>0),
        ("  ↳ Ad valorem + GRIS",                  r["ad_valorem_per_ship"]+r["gris_per_ship"], (r["ad_valorem_per_ship"]+r["gris_per_ship"])>0),
        ("  ↳ Escolta / segurança",                r["escort_per_trip"],             r["escort_per_trip"]>0),
        ("  ↳ Accessorials",                       r["accessorial_total_per_trip"],  r["accessorial_total_per_trip"]>0),
        ("  ↳ Warehouse interface",                r["wh_interface_per_trip"],       r["wh_interface_per_trip"]>0),
        ("Fixed cost alocado / embarque",          r["fixed_per_shipment"],          r["fixed_per_shipment"]>0),
        ("Margem transportadora",                  r["trip_cost_with_margin"]-r["should_cost_per_shipment"], r["trip_cost_with_margin"]>r["should_cost_per_shipment"]),
        ("Risk cost / embarque (spot overflow + no-show + damage)", r["risk_cost_per_shipment"], r["risk_cost_per_shipment"]>0),
    ]
    def _wf_row_color(label): return "#64748b" if "↳" in label else "#94a3b8"
    wf_html = "".join(
        f"<div style='display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(148,163,184,.07)'>"
        f"<span style='font-size:.77rem;color:{_wf_row_color(lbl)}'>{lbl}</span>"
        f"<span style='font-family:IBM Plex Mono,monospace;font-size:.77rem;color:#e2e8f0'>{reporting_currency} {val:,.2f}</span></div>"
        for lbl, val, show in wf_rows if show
    )
    lf_color = "#34d399" if r["load_factor_effective"] >= 0.75 else "#f59e0b" if r["load_factor_effective"] >= 0.50 else "#f87171"
    acc_color = "#f87171" if r["accessorial_leakage_pct"] > 0.08 else "#fbbf24" if r["accessorial_leakage_pct"] > 0.04 else "#34d399"
    breakeven_txt = f"{r['dedicated_vs_spot_breakeven_monthly']:.0f} ship/mês" if r['dedicated_vs_spot_breakeven_monthly'] < 9999 else "N/A"
    ded_rec = "✅ Dedicado é melhor" if r["dedicated_better"] else "⚠ Spot/flex pode ser melhor"

    st.markdown(f"""<div class="v46-svc-result" style="padding:14px 18px">
        <div style='margin-bottom:8px;font-size:.82rem;font-weight:600;color:#6ee7b7'>🚚 Route TCO waterfall</div>
        {wf_html}
        <div style='display:flex;justify-content:space-between;padding:7px 0 0 0;margin-top:4px;border-top:1px solid rgba(16,185,129,.3)'>
            <span style='font-size:.84rem;font-weight:700;color:#f1f5f9'>Risk-adjusted Annual Route TCO</span>
            <span style='font-family:IBM Plex Mono,monospace;font-size:.96rem;font-weight:700;color:#34d399'>{reporting_currency} {r['risk_adj_tco']:,.0f}</span>
        </div>
        <div style='margin-top:10px;display:grid;grid-template-columns:repeat(4,1fr);gap:8px;font-size:.75rem;'>
            <div style='background:rgba(15,23,42,.5);padding:8px 10px;border-radius:8px'>
                <div style='color:#64748b;margin-bottom:2px'>Cost / shipment</div>
                <div style='color:#e2e8f0;font-family:IBM Plex Mono,monospace;font-weight:600'>{reporting_currency} {r['cost_per_shipment']:,.2f}</div>
            </div>
            <div style='background:rgba(15,23,42,.5);padding:8px 10px;border-radius:8px'>
                <div style='color:#64748b;margin-bottom:2px'>Cost / order</div>
                <div style='color:#e2e8f0;font-family:IBM Plex Mono,monospace;font-weight:600'>{reporting_currency} {r['cost_per_order']:,.2f}</div>
            </div>
            <div style='background:rgba(15,23,42,.5);padding:8px 10px;border-radius:8px'>
                <div style='color:#64748b;margin-bottom:2px'>Cost / pallet</div>
                <div style='color:#e2e8f0;font-family:IBM Plex Mono,monospace;font-weight:600'>{reporting_currency} {r['cost_per_pallet']:,.2f}</div>
            </div>
            <div style='background:rgba(15,23,42,.5);padding:8px 10px;border-radius:8px'>
                <div style='color:#64748b;margin-bottom:2px'>Cost / kg</div>
                <div style='color:#e2e8f0;font-family:IBM Plex Mono,monospace;font-weight:600'>{reporting_currency} {r['cost_per_kg']:,.4f}</div>
            </div>
            <div style='background:rgba(15,23,42,.5);padding:8px 10px;border-radius:8px'>
                <div style='color:#64748b;margin-bottom:2px'>Load factor</div>
                <div style='color:{lf_color};font-family:IBM Plex Mono,monospace;font-weight:600'>{r['load_factor_effective']*100:.1f}%</div>
            </div>
            <div style='background:rgba(15,23,42,.5);padding:8px 10px;border-radius:8px'>
                <div style='color:#64748b;margin-bottom:2px'>Empty km %</div>
                <div style='color:#fbbf24;font-family:IBM Plex Mono,monospace;font-weight:600'>{empty_pct:.1f}%</div>
            </div>
            <div style='background:rgba(15,23,42,.5);padding:8px 10px;border-radius:8px'>
                <div style='color:#64748b;margin-bottom:2px'>Accessorial leakage</div>
                <div style='color:{acc_color};font-family:IBM Plex Mono,monospace;font-weight:600'>{r['accessorial_leakage_pct']*100:.1f}%</div>
            </div>
            <div style='background:rgba(15,23,42,.5);padding:8px 10px;border-radius:8px'>
                <div style='color:#64748b;margin-bottom:2px'>CO₂e / viagem</div>
                <div style='color:#34d399;font-family:IBM Plex Mono,monospace;font-weight:600'>{r['co2e_per_trip_kg']:.1f} kg</div>
            </div>
        </div>
        <div style='margin-top:10px;font-size:.78rem;color:#94a3b8'>
            <b style='color:#e2e8f0'>Dedicado vs Spot breakeven:</b> {breakeven_txt} · {ded_rec} &nbsp;·&nbsp;
            <b style='color:#e2e8f0'>Safety stock:</b> {r['safety_stock_days']:.1f} dias · {reporting_currency} {r['safety_stock_value']:,.0f} &nbsp;·&nbsp;
            <b style='color:#e2e8f0'>CO₂e anual:</b> {r['co2e_annual_ton']:.1f} tCO₂e · {reporting_currency} {r['carbon_cost_annual']:,.0f} carbon cost
        </div>
    </div>""", unsafe_allow_html=True)

    # Should-cost vs contracted
    if float(contracted_rate) > 0:
        sc_gap = float(contracted_rate) * (1 + fuel_surcharge_pct/100) - r["trip_cost_with_margin"]
        sc_color = "#f87171" if sc_gap > 0 else "#34d399"
        st.markdown(f"<div class='v46-landed'><b>Cotação total (c/ FSC):</b> {reporting_currency} {float(contracted_rate)*(1+fuel_surcharge_pct/100):,.2f} &nbsp;·&nbsp; <b>Should-cost:</b> {reporting_currency} {r['trip_cost_with_margin']:,.2f} &nbsp;·&nbsp; <b style='color:{sc_color}'>Gap: {reporting_currency} {sc_gap:,.2f} ({'acima' if sc_gap>0 else 'abaixo'} do should-cost)</b></div>", unsafe_allow_html=True)

    return {
        "scope": "Logistics / Transport Services", "pricing_model": pricing_model if "pricing_model" in dir() else "Rate per shipment",
        "proposed_contract_value": float(contracted_rate) * float(shipments_month) * 12.0,
        "service_tco": r["risk_adj_tco"], "service_tco_before_productivity": r["annual_base_tco"],
        "performance_score": float(otif) * float(tender_acc) / 100.0,
        "performance_tier": "Good" if otif >= 95 else "Watchlist",
        "performance_adjusted_cost": r["risk_adj_tco"],
        "productivity_gain": 0.0, "expected_risk_cost": r["risk_annual"],
        "sla_risk_cost": 0.0, "sla_attainment": float(otif), "sla_target": 98.0,
        "sla_gap": max(0.0, 98.0 - float(otif)),
        "headcount": 0.0, "total_contract_value": r["ramp_adjusted_tco"] * int(contract_years if "contract_years" in dir() else 2),
        "route_tco_result": r, "route_tco_params": tco_params,
        "route_type": route_type, "vehicle_type": vehicle_type, "cargo_risk": cargo_risk,
        "road_zone": road_zone, "escort_required": bool(auto_escort),
    }


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE OPTIMIZER — Multi-criteria best route engine
# ─────────────────────────────────────────────────────────────────────────────

def calc_route_score(route_data: Dict, weights: Dict) -> float:
    """
    Multi-criteria route score. Lower is better.
    Normalized 0-1 per criterion, then weighted sum.
    """
    return (
        weights.get("distance", 0.25) * route_data.get("norm_distance", 1.0)
        + weights.get("cost",     0.35) * route_data.get("norm_cost",     1.0)
        + weights.get("time",     0.15) * route_data.get("norm_time",     1.0)
        + weights.get("risk",     0.15) * route_data.get("norm_risk",     1.0)
        + weights.get("esg",      0.10) * route_data.get("norm_esg",      1.0)
    )


def render_route_optimizer(reporting_currency: str):
    """
    Amazon-grade Route Optimizer — multi-criteria, multi-stop, full cost model.
    Covers: Middle Mile, Last Mile, Inbound, Outbound, Reverse, Milk Run.
    No external API required — Haversine × road factor + full open-cost model.
    """

    # ── VEHICLE MASTER (Amazon fleet reference) ─────────────────────────
    VEHICLE_MASTER = {
        "Van / Sprinter ≤3.5t":  {"kg":3_500, "pal":8,  "m3":12,  "avg_spd_urban":35, "avg_spd_highway":90, "fuel_kml":10.0, "maint_km":0.12, "tire_km":0.04, "requires_helper":False, "hos_drive_h":10, "hos_window_h":14, "monthly_fixed":4_500,  "driver_monthly":3_200, "em_factor":0.21},
        "VUC ≤6t (urban)":       {"kg":6_000, "pal":10, "m3":18,  "avg_spd_urban":30, "avg_spd_highway":80, "fuel_kml":7.0,  "maint_km":0.15, "tire_km":0.05, "requires_helper":False,"hos_drive_h":10, "hos_window_h":14, "monthly_fixed":6_000,  "driver_monthly":3_800, "em_factor":0.28},
        "Toco ≤13t":             {"kg":13_000,"pal":16, "m3":45,  "avg_spd_urban":35, "avg_spd_highway":80, "fuel_kml":5.0,  "maint_km":0.18, "tire_km":0.07, "requires_helper":False,"hos_drive_h":11, "hos_window_h":14, "monthly_fixed":9_000,  "driver_monthly":4_500, "em_factor":0.55},
        "Truck ≤23t":            {"kg":23_000,"pal":22, "m3":70,  "avg_spd_urban":35, "avg_spd_highway":80, "fuel_kml":4.0,  "maint_km":0.20, "tire_km":0.09, "requires_helper":False,"hos_drive_h":11, "hos_window_h":14, "monthly_fixed":12_000, "driver_monthly":5_200, "em_factor":0.75},
        "Carreta ≤33t":          {"kg":27_000,"pal":26, "m3":90,  "avg_spd_urban":30, "avg_spd_highway":75, "fuel_kml":3.5,  "maint_km":0.22, "tire_km":0.10, "requires_helper":False,"hos_drive_h":11, "hos_window_h":14, "monthly_fixed":16_000, "driver_monthly":6_000, "em_factor":0.92},
        "Bitrem ≤57t":           {"kg":50_000,"pal":42, "m3":140, "avg_spd_urban":25, "avg_spd_highway":70, "fuel_kml":2.8,  "maint_km":0.28, "tire_km":0.13, "requires_helper":False,"hos_drive_h":11, "hos_window_h":14, "monthly_fixed":22_000, "driver_monthly":7_000, "em_factor":1.15},
        "Refrigerado ≤23t":      {"kg":18_000,"pal":20, "m3":65,  "avg_spd_urban":35, "avg_spd_highway":78, "fuel_kml":3.2,  "maint_km":0.25, "tire_km":0.09, "requires_helper":False,"hos_drive_h":11, "hos_window_h":14, "monthly_fixed":18_000, "driver_monthly":5_800, "em_factor":1.05},
        "Van Last Mile ≤1.5t":   {"kg":1_500, "pal":4,  "m3":8,   "avg_spd_urban":28, "avg_spd_highway":80, "fuel_kml":11.0, "maint_km":0.10, "tire_km":0.03, "requires_helper":True, "hos_drive_h":10, "hos_window_h":14, "monthly_fixed":3_500,  "driver_monthly":2_800, "em_factor":0.18},
        "Moto / Bike (last mile)":{"kg":30,   "pal":0,  "m3":0.2, "avg_spd_urban":25, "avg_spd_highway":60, "fuel_kml":25.0, "maint_km":0.04, "tire_km":0.01, "requires_helper":False,"hos_drive_h":10, "hos_window_h":14, "monthly_fixed":800,   "driver_monthly":2_200, "em_factor":0.05},
    }

    # ── ROUTE TYPE PROFILES ─────────────────────────────────────────────
    ROUTE_TYPE_PROFILES = {
        "Inbound to FC/Warehouse":      {"rdf":1.28, "avg_stops":1,  "urban_pct":0.10, "default_empty_pct":25, "typical_vehicle":"Carreta ≤33t",    "icon":"📦"},
        "Middle Mile FC→Sort Center":   {"rdf":1.22, "avg_stops":1,  "urban_pct":0.05, "default_empty_pct":20, "typical_vehicle":"Carreta ≤33t",    "icon":"🔁"},
        "Middle Mile FC→DS (injection)":{"rdf":1.25, "avg_stops":2,  "urban_pct":0.15, "default_empty_pct":30, "typical_vehicle":"Truck ≤23t",      "icon":"🏭"},
        "Outbound B2B":                 {"rdf":1.30, "avg_stops":3,  "urban_pct":0.20, "default_empty_pct":25, "typical_vehicle":"Truck ≤23t",      "icon":"🏪"},
        "Last Mile Delivery":           {"rdf":1.45, "avg_stops":20, "urban_pct":0.85, "default_empty_pct":50, "typical_vehicle":"Van Last Mile ≤1.5t","icon":"🏠"},
        "Reverse Logistics":            {"rdf":1.32, "avg_stops":5,  "urban_pct":0.30, "default_empty_pct":15, "typical_vehicle":"Toco ≤13t",       "icon":"↩️"},
        "Milk Run (multi-supplier)":    {"rdf":1.35, "avg_stops":5,  "urban_pct":0.20, "default_empty_pct":10, "typical_vehicle":"Truck ≤23t",      "icon":"🥛"},
        "Dedicated Lane (fixed route)": {"rdf":1.25, "avg_stops":1,  "urban_pct":0.10, "default_empty_pct":20, "typical_vehicle":"Carreta ≤33t",    "icon":"🛣️"},
        "Cross-border":                 {"rdf":1.40, "avg_stops":2,  "urban_pct":0.05, "default_empty_pct":30, "typical_vehicle":"Carreta ≤33t",    "icon":"🌎"},
        "Spot / On-demand":             {"rdf":1.30, "avg_stops":1,  "urban_pct":0.15, "default_empty_pct":35, "typical_vehicle":"Truck ≤23t",      "icon":"⚡"},
    }

    render_section(
        "Route Optimizer — Amazon Logistics Standard",
        "Middle Mile · Last Mile · Inbound · Milk Run · Multi-stop cost comparison. Rota mais curta ≠ rota mais barata.",
        "#10b981",
    )

    # ── Context card ─────────────────────────────────────────────────────
    st.markdown("""<div class="v46-insight">
    <b>Como funciona:</b> Configure o perfil de carga, veículo, waypoints e zona de risco.
    A ferramenta calcula para <i>cada combinação de rota</i>: distância real de estrada (Haversine × road factor),
    custo aberto (combustível + pedágio + motorista + ajudante + manutenção + seguro de carga + escolta +
    acessórios + overhead + margem), tempo de trânsito (velocidade urbana/rodovia + paradas + HoS),
    risco de rota, e CO₂e. O score composto rankeia tudo.
    <b>Uma rota pelo interior de SP pode ser 40km mais longa mas R$800 mais barata que a rota pelo RJ com escolta obrigatória.</b>
    </div>""", unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════════════════
    # SECTION 1 — Cargo & Operation Profile
    # ════════════════════════════════════════════════════════════════════
    with st.expander("📦 1 · Perfil da operação, carga e veículo", expanded=True):
        p1 = st.columns([1.3, 1.0, 1.0])
        with p1[0]: route_type_opt = st.selectbox("Tipo de rota / operação", options=list(ROUTE_TYPE_PROFILES.keys()), key="opt__route_type")
        rtp = ROUTE_TYPE_PROFILES[route_type_opt]
        with p1[1]: vehicle_opt = st.selectbox("Tipo de veículo", options=list(VEHICLE_MASTER.keys()), index=list(VEHICLE_MASTER.keys()).index(rtp["typical_vehicle"]) if rtp["typical_vehicle"] in VEHICLE_MASTER else 0, key="opt__vehicle_type")
        veh = VEHICLE_MASTER[vehicle_opt]
        with p1[2]: cargo_risk_opt = st.selectbox("Perfil / risco da carga", options=list(CARGO_RISK_AD_VALOREM.keys()), key="opt__cargo_risk")

        p2 = st.columns(6)
        with p2[0]: cargo_value_opt = st.number_input(f"Valor da carga / embarque ({reporting_currency})", min_value=0.0, value=50_000.0, step=10_000.0, key="opt__cargo_value", help="Base para ad valorem, GRIS e seguro. Eletrônicos = alto valor = escolta automática.")
        with p2[1]: kg_opt = st.number_input("Kg / embarque", min_value=0.0, value=float(veh["kg"]*0.8), step=500.0, key="opt__kg")
        with p2[2]: pal_opt = st.number_input("Pallets / embarque", min_value=0.0, value=float(veh["pal"]*0.8), step=1.0, key="opt__pallets")
        with p2[3]: orders_opt = st.number_input("Orders / embarque", min_value=1.0, value=1.0, step=1.0, key="opt__orders")
        with p2[4]: shipments_opt = st.number_input("Embarques / mês", min_value=1.0, value=40.0, step=5.0, key="opt__shipments_month")
        with p2[5]: empty_pct_opt = st.number_input("Empty km % (retorno vazio)", min_value=0.0, max_value=100.0, value=float(rtp["default_empty_pct"]), step=5.0, key="opt__empty_pct", help="Percentual da distância rodado sem carga. 0% = backhaul 100% aproveitado.")

        # Load factor alert
        lf_kg  = safe_divide(float(kg_opt),  float(veh["kg"])) * 100
        lf_pal = safe_divide(float(pal_opt), float(veh["pal"])) * 100 if veh["pal"] > 0 else 0
        lf_eff = max(lf_kg, lf_pal)
        lf_color = "#34d399" if lf_eff >= 75 else "#f59e0b" if lf_eff >= 50 else "#f87171"
        st.markdown(
            f"<div class='v46-note'>🚛 <b>{vehicle_opt}</b> · Capacidade: {veh['kg']:,}kg / {veh['pal']} pal · "
            f"<b style='color:{lf_color}'>Load factor: {lf_eff:.1f}%</b> · "
            f"HoS drive: {veh['hos_drive_h']}h/janela {veh['hos_window_h']}h · "
            f"Ajudante: {'<b style=\"color:#fbbf24\">Necessário ⚠</b>' if veh['requires_helper'] else 'Não necessário'}</div>",
            unsafe_allow_html=True,
        )

    # ════════════════════════════════════════════════════════════════════
    # SECTION 2 — Open Cost Model
    # ════════════════════════════════════════════════════════════════════
    with st.expander("💰 2 · Modelo de custo aberto (should-cost por trecho)", expanded=True):
        st.caption("Todos os custos por km e por viagem. A ferramenta calcula o should-cost real — não depende só da cotação da transportadora.")
        oc1 = st.columns(5)
        with oc1[0]: diesel_opt = st.number_input("Diesel (R$/l)", min_value=1.0, value=6.50, step=0.05, key="opt__diesel")
        with oc1[1]: fuel_con_opt = st.number_input("Consumo (km/l)", min_value=0.1, value=float(veh["fuel_kml"]), step=0.1, key="opt__fuel_consump", help="Carregado. Vazio consome ~15% menos — calculado automaticamente.")
        with oc1[2]: maint_km_opt = st.number_input("Manutenção (R$/km)", min_value=0.0, value=float(veh["maint_km"]), step=0.01, key="opt__maint_km")
        with oc1[3]: tire_km_opt  = st.number_input("Pneus (R$/km)", min_value=0.0, value=float(veh["tire_km"]),  step=0.01, key="opt__tire_km")
        with oc1[4]: overhead_opt = st.number_input("Overhead %", min_value=0.0, value=12.0, step=1.0, key="opt__overhead")

        oc2 = st.columns(5)
        with oc2[0]: driver_monthly_opt   = st.number_input("Salário motorista (R$/mês)", min_value=0.0, value=float(veh["driver_monthly"]), step=200.0, key="opt__driver_monthly")
        with oc2[1]: driver_benefits_opt  = st.number_input("Encargos/benefícios %", min_value=0.0, value=70.0, step=1.0, key="opt__driver_benefits")
        with oc2[2]:
            needs_helper_default = bool(veh["requires_helper"])
            has_helper = st.checkbox("Ajudante necessário?", value=needs_helper_default, key="opt__has_helper",
                                     help="Automático para Last Mile e cargas de varejo. Moto = sem ajudante.")
        with oc2[3]: helper_monthly_opt   = st.number_input("Salário ajudante (R$/mês)", min_value=0.0, value=2_500.0 if has_helper else 0.0, step=200.0, key="opt__helper_monthly", disabled=not has_helper)
        with oc2[4]: margin_opt           = st.number_input("Margem transportadora %", min_value=0.0, value=10.0, step=1.0, key="opt__margin")

        oc3 = st.columns(5)
        with oc3[0]: tracking_opt         = st.number_input("Rastreamento (R$/mês)", min_value=0.0, value=250.0, step=50.0, key="opt__tracking")
        with oc3[1]: vehicle_fixed_opt    = st.number_input("Custo fixo veículo (R$/mês)", min_value=0.0, value=float(veh["monthly_fixed"]), step=500.0, key="opt__veh_fixed")
        with oc3[2]: loading_time_h       = st.number_input("Tempo carga+descarga (h/parada)", min_value=0.0, value=1.5, step=0.25, key="opt__load_time")
        with oc3[3]: detention_h_opt      = st.number_input("Dwell time médio (h/parada)", min_value=0.0, value=0.5, step=0.25, key="opt__dwell_time")
        with oc3[4]: detention_rate_opt   = st.number_input("Detention (R$/h extra)", min_value=0.0, value=120.0, step=20.0, key="opt__detention_rate")

    # ════════════════════════════════════════════════════════════════════
    # SECTION 3 — Cargo Insurance & Security
    # ════════════════════════════════════════════════════════════════════
    with st.expander("🔒 3 · Seguro de carga, GRIS, escolta & acessórios", expanded=False):
        auto_escort = (ROAD_RISK_ZONES.get("Baixo Risco — Sul / PR / SC / RS", {}).get("escort_required", False)
                      or "eletrônico" in cargo_risk_opt.lower() or "alto valor" in cargo_risk_opt.lower()
                      or "muito alto" in cargo_risk_opt.lower())
        ad_val_default = CARGO_RISK_AD_VALOREM.get(cargo_risk_opt, 0.20)
        s1 = st.columns(5)
        with s1[0]: ad_valorem_opt  = st.number_input("Ad valorem %", min_value=0.0, value=ad_val_default, step=0.01, format="%.3f", key="opt__ad_valorem", help="% sobre o valor declarado da carga por embarque")
        with s1[1]: gris_opt        = st.number_input("GRIS % (mín. por zona)", min_value=0.0, value=0.20, step=0.01, format="%.3f", key="opt__gris")
        with s1[2]: escort_req_opt  = st.checkbox("Escolta obrigatória?", value=auto_escort, key="opt__escort_req")
        with s1[3]: escort_type_opt = st.selectbox("Tipo de escolta", options=list(ESCORT_COST_PER_KM.keys()), key="opt__escort_type", disabled=not escort_req_opt)
        with s1[4]: escort_trips_pct_opt = st.number_input("% viagens com escolta", min_value=0.0, max_value=100.0, value=100.0 if auto_escort else 0.0, step=5.0, key="opt__escort_pct_trips")

        s2 = st.columns(4)
        with s2[0]: tender_acc_opt  = st.number_input("Tender acceptance %", min_value=0.0, max_value=100.0, value=90.0, step=1.0, key="opt__tender_acc")
        with s2[1]: backup_prem_opt = st.number_input("Backup premium %", min_value=0.0, value=22.0, step=1.0, key="opt__backup_prem")
        with s2[2]: damage_rate_opt = st.number_input("Damage rate %", min_value=0.0, value=0.3, step=0.05, key="opt__damage_rate")
        with s2[3]: carbon_opt      = st.number_input("Carbon price (USD/tCO₂e)", min_value=0.0, value=30.0, step=1.0, key="opt__carbon")
        escort_km_cost_opt = ESCORT_COST_PER_KM.get(escort_type_opt, 0.0) if escort_req_opt else 0.0

    # ════════════════════════════════════════════════════════════════════
    # SECTION 4 — Decision Weights
    # ════════════════════════════════════════════════════════════════════
    with st.expander("⚖ 4 · Pesos de decisão — o que mais importa para esta operação?", expanded=True):
        st.caption("Adapte para o contexto: Middle Mile prioriza custo. Last Mile eletrônicos prioriza risco+segurança. Perecíveis priorizam tempo.")
        # Presets
        preset_col, _, _ = st.columns([1, 1, 2])
        with preset_col:
            preset = st.selectbox("Preset de pesos", options=[
                "Customizado",
                "Middle Mile — custo primeiro",
                "Last Mile Eletrônicos — risco primeiro",
                "Perecíveis — tempo primeiro",
                "ESG / sustentabilidade primeiro",
                "Balanceado (Amazon default)",
            ], key="opt__weight_preset")
        PRESETS = {
            "Middle Mile — custo primeiro":          (15, 45, 15, 15, 10),
            "Last Mile Eletrônicos — risco primeiro":(10, 20, 20, 40, 10),
            "Perecíveis — tempo primeiro":           (10, 20, 45, 15, 10),
            "ESG / sustentabilidade primeiro":       (10, 25, 15, 20, 30),
            "Balanceado (Amazon default)":           (20, 35, 20, 15, 10),
        }
        defaults = PRESETS.get(preset, (20, 35, 20, 15, 10))
        ow = st.columns(5)
        with ow[0]: w_dist = st.slider("📏 Distância", 0, 100, defaults[0], 5, key="opt__w_dist")
        with ow[1]: w_cost = st.slider("💰 Custo total", 0, 100, defaults[1], 5, key="opt__w_cost")
        with ow[2]: w_time = st.slider("⏱ Transit time", 0, 100, defaults[2], 5, key="opt__w_time")
        with ow[3]: w_risk = st.slider("🔒 Risco/segurança", 0, 100, defaults[3], 5, key="opt__w_risk")
        with ow[4]: w_esg  = st.slider("🌿 ESG / CO₂", 0, 100, defaults[4], 5, key="opt__w_esg")
        total_w = w_dist + w_cost + w_time + w_risk + w_esg
        wc_color = "#34d399" if abs(total_w - 100) < 1 else "#f87171"
        st.markdown(f"<span style='font-size:.78rem;color:{wc_color}'>Total: <b>{total_w}%</b> {'✓' if abs(total_w-100)<1 else '— ajuste para 100%'}</span>", unsafe_allow_html=True)

    # ════════════════════════════════════════════════════════════════════
    # SECTION 5 — Route Points
    # ════════════════════════════════════════════════════════════════════
    with st.expander(f"📍 5 · Pontos da rota — {rtp['icon']} {route_type_opt}", expanded=True):
        hub_names = list(BR_LOGISTICS_HUBS.keys())

        st.markdown("<div style='font-size:.82rem;font-weight:600;color:#e2e8f0;margin:6px 0 4px'>🟢 Origem</div>", unsafe_allow_html=True)
        oc_ = st.columns([1.8, .6, .6, 1.0])
        with oc_[0]: origin_name = st.selectbox("Origem", options=hub_names, index=0, key="opt__origin", label_visibility="collapsed")
        olatlon = BR_LOGISTICS_HUBS[origin_name]
        with oc_[1]: origin_lat = st.number_input("Lat", value=float(olatlon[0]), format="%.4f", key="opt__origin_lat", label_visibility="collapsed")
        with oc_[2]: origin_lon = st.number_input("Lon", value=float(olatlon[1]), format="%.4f", key="opt__origin_lon", label_visibility="collapsed")
        with oc_[3]: origin_zone = st.selectbox("Zona de risco", options=list(ROAD_RISK_ZONES.keys()), key="opt__origin_zone", label_visibility="collapsed")

        st.markdown("<div style='font-size:.82rem;font-weight:600;color:#e2e8f0;margin:8px 0 4px'>🔴 Destino</div>", unsafe_allow_html=True)
        dc_ = st.columns([1.8, .6, .6, 1.0])
        with dc_[0]: dest_name = st.selectbox("Destino", options=hub_names, index=min(4, len(hub_names)-1), key="opt__dest", label_visibility="collapsed")
        dlatlon = BR_LOGISTICS_HUBS[dest_name]
        with dc_[1]: dest_lat = st.number_input("Lat", value=float(dlatlon[0]), format="%.4f", key="opt__dest_lat", label_visibility="collapsed")
        with dc_[2]: dest_lon = st.number_input("Lon", value=float(dlatlon[1]), format="%.4f", key="opt__dest_lon", label_visibility="collapsed")
        with dc_[3]: dest_zone = st.selectbox("Zona de risco", options=list(ROAD_RISK_ZONES.keys()), key="opt__dest_zone", label_visibility="collapsed")

        n_wps = int(st.number_input("Waypoints intermediários (paradas, CDs, clientes, fornecedores)", min_value=0, max_value=8, value=0, step=1, key="opt__n_waypoints"))
        waypoints = []
        if n_wps > 0:
            st.markdown("<div style='font-size:.82rem;font-weight:600;color:#e2e8f0;margin:8px 0 4px'>🔵 Waypoints</div>", unsafe_allow_html=True)
            for wi in range(n_wps):
                wc__ = st.columns([1.8, .6, .6, 1.0, .8])
                with wc__[0]: wp_name = st.selectbox(f"Parada {wi+1}", options=hub_names, key=f"opt__wp_name_{wi}", label_visibility="collapsed")
                wp_ll = BR_LOGISTICS_HUBS[wp_name]
                with wc__[1]: wp_lat = st.number_input("Lat", value=float(wp_ll[0]), format="%.4f", key=f"opt__wp_lat_{wi}", label_visibility="collapsed")
                with wc__[2]: wp_lon = st.number_input("Lon", value=float(wp_ll[1]), format="%.4f", key=f"opt__wp_lon_{wi}", label_visibility="collapsed")
                with wc__[3]: wp_zone = st.selectbox("Zona risco", options=list(ROAD_RISK_ZONES.keys()), key=f"opt__wp_zone_{wi}", label_visibility="collapsed")
                with wc__[4]: wp_dwell = st.number_input("Dwell h", min_value=0.0, value=1.0, step=0.5, key=f"opt__wp_dwell_{wi}", label_visibility="collapsed")
                waypoints.append({"name": wp_name, "lat": float(wp_lat), "lon": float(wp_lon), "zone": wp_zone, "dwell_h": float(wp_dwell)})

    # ════════════════════════════════════════════════════════════════════
    # COMPUTE ENGINE
    # ════════════════════════════════════════════════════════════════════
    if st.button("🚀 Calcular & ranquear todas as rotas", type="primary", key="opt__run", use_container_width=False):
        from itertools import permutations as iperms

        emission_factor_v = float(EMISSION_FACTORS_KG_CO2E_KM.get(vehicle_opt, veh.get("em_factor", 0.75)))
        rdf = float(rtp["rdf"])
        urban_pct = float(rtp["urban_pct"])
        avg_stops_base = int(rtp["avg_stops"])
        ad_val = float(ad_valorem_opt)
        gris_v = float(gris_opt)
        has_helper_v = bool(has_helper)
        escort_cost_km = float(escort_km_cost_opt)
        escort_trips_frac = float(escort_trips_pct_opt) / 100.0

        # Monthly fixed cost (fully allocated)
        helper_adj = (float(helper_monthly_opt) * (1 + float(driver_benefits_opt)/100)) if has_helper_v else 0.0
        monthly_fixed = (
            float(vehicle_fixed_opt)
            + float(driver_monthly_opt) * (1 + float(driver_benefits_opt)/100)
            + helper_adj
            + float(tracking_opt)
        ) * (1 + float(overhead_opt)/100)
        fixed_per_ship = safe_divide(monthly_fixed, max(float(shipments_opt), 1.0))

        def compute_segment_km(p1_lat, p1_lon, p2_lat, p2_lon) -> float:
            gc = haversine_km(p1_lat, p1_lon, p2_lat, p2_lon)
            return gc * rdf

        def get_zone_info(zone_name: str) -> Dict:
            return ROAD_RISK_ZONES.get(zone_name, {"escort_required": False, "gris_min_pct": 0.20, "insurance_multiplier": 1.0, "risk_score": 2.5})

        def compute_route_full(ordered_wps: List[Dict]) -> Dict:
            """Full cost + time model for one route permutation."""
            # Build the full point sequence
            all_points = (
                [{"lat": float(origin_lat), "lon": float(origin_lon), "name": origin_name, "zone": origin_zone, "dwell_h": 0.5}]
                + ordered_wps
                + [{"lat": float(dest_lat),   "lon": float(dest_lon),   "name": dest_name,   "zone": dest_zone,   "dwell_h": 0.0}]
            )
            n_segments = len(all_points) - 1
            n_stops = len(ordered_wps) + 1  # waypoints + destination

            # ── Per-segment distance & cost ──────────────────────────────
            seg_km_loaded = []
            seg_risk      = []
            seg_escort    = []
            seg_toll      = []
            seg_fuel_load = []
            seg_fuel_empt = []

            for i in range(n_segments):
                p1, p2 = all_points[i], all_points[i+1]
                km = compute_segment_km(p1["lat"], p1["lon"], p2["lat"], p2["lon"])
                seg_km_loaded.append(km)
                zi = get_zone_info(p1["zone"])
                seg_risk.append(float(zi["risk_score"]))

                # Escort: if required by zone OR cargo forces it
                seg_esc_required = zi["escort_required"] or bool(escort_req_opt)
                seg_escort.append(km * escort_cost_km * escort_trips_frac if seg_esc_required else 0.0)

                # Toll: use zone-specific benchmark
                toll_rate = next(
                    (v for k, v in TOLL_BENCHMARK_PER_100KM.items()
                     if any(st_code in k for st_code in ["SP", "PR", "RJ", "MG", "RS", "SC", "ES", "GO", "NE", "Norte"])
                     and any(st_code in (origin_name + " " + dest_name) for st_code in [k.split("—")[0].strip()[:3]])),
                    10.0,
                )
                seg_toll.append(km * toll_rate / 100.0)

                # Fuel: loaded km (forward) + empty km % return
                seg_fuel_load.append(km / max(float(fuel_con_opt), 0.1) * float(diesel_opt))
                empty_km = km * float(empty_pct_opt) / 100.0
                seg_fuel_empt.append(empty_km / max(float(fuel_con_opt) * 1.15, 0.1) * float(diesel_opt))  # empty = 15% better fuel

            # ── Totals ───────────────────────────────────────────────────
            total_km_loaded = sum(seg_km_loaded)
            total_km_empty  = total_km_loaded * float(empty_pct_opt) / 100.0
            total_km        = total_km_loaded + total_km_empty
            max_risk_score  = max(seg_risk) if seg_risk else 2.5
            avg_risk_score  = sum(seg_risk) / len(seg_risk) if seg_risk else 2.5
            route_risk      = 0.6 * max_risk_score + 0.4 * avg_risk_score  # worst segment weighted

            fuel_total = sum(seg_fuel_load) + sum(seg_fuel_empt)
            toll_total = sum(seg_toll)
            escort_total = sum(seg_escort)
            maint_total = total_km * float(maint_km_opt)
            tire_total  = total_km * float(tire_km_opt)
            cargo_ins   = float(cargo_value_opt) * (ad_val + gris_v)
            accessorial = n_stops * max(0.0, float(detention_h_opt) - 0.5) * float(detention_rate_opt)

            trip_variable = fuel_total + toll_total + escort_total + maint_total + tire_total + cargo_ins + accessorial
            should_cost   = trip_variable + fixed_per_ship
            trip_cost_wm  = should_cost * (1 + float(margin_opt) / 100.0)

            # Blended rate (tender acceptance)
            ta  = float(tender_acc_opt) / 100.0
            bp  = float(backup_prem_opt) / 100.0
            blended = trip_cost_wm * ta + trip_cost_wm * (1 + bp) * (1 - ta)

            # Risk cost per trip
            damage_cost = float(cargo_value_opt) * float(damage_rate_opt) / 100.0
            spot_ovf    = (1 - ta) * trip_cost_wm * bp
            risk_cost   = damage_cost + spot_ovf

            annual_tco = (blended + risk_cost) * float(shipments_opt) * 12.0

            # ── Transit time model ─────────────────────────────────────
            # Weighted speed: urban_pct × urban_speed + highway_pct × highway_speed
            avg_spd = (urban_pct * float(veh["avg_spd_urban"])
                       + (1 - urban_pct) * float(veh["avg_spd_highway"]))
            drive_h = total_km_loaded / max(avg_spd, 1.0)

            # HoS check: does route require driver rest/relay?
            hos_drive  = float(veh["hos_drive_h"])
            hos_window = float(veh["hos_window_h"])
            stop_time_h = n_stops * (float(loading_time_h) + float(detention_h_opt))
            total_work_h = drive_h + stop_time_h
            # Required drivers / rest breaks
            rest_breaks = max(0, int(drive_h / hos_drive))
            rest_cost_extra = rest_breaks * 100.0  # per diem / hotel estimate

            transit_h = drive_h + stop_time_h + rest_breaks * 10.0  # 10h rest per break
            transit_days = transit_h / 24.0

            # ── ESG ──────────────────────────────────────────────────
            co2e_trip_kg    = total_km * emission_factor_v
            co2e_annual_ton = co2e_trip_kg * float(shipments_opt) * 12.0 / 1000.0
            carbon_cost_ann = co2e_annual_ton * float(carbon_opt)

            # ── Load factor ───────────────────────────────────────────
            lf_kg_route  = safe_divide(float(kg_opt),  float(veh["kg"]))
            lf_pal_route = safe_divide(float(pal_opt), max(float(veh["pal"]), 1))
            lf_route     = max(lf_kg_route, lf_pal_route)

            # ── Cost breakdown per label ─────────────────────────────
            waypoint_names = " → ".join(w["name"].split("-")[0].strip()[:14] for w in ordered_wps) if ordered_wps else "Direto"
            label = (f"{origin_name.split('-')[0].strip()[:12]} → "
                     + (f"{waypoint_names} → " if ordered_wps else "")
                     + f"{dest_name.split('-')[0].strip()[:12]}")

            return {
                "label": label,
                "waypoints": waypoint_names,
                "n_stops": n_stops,
                "distance_road_km": total_km_loaded,
                "distance_total_km": total_km,
                "fuel_per_trip": fuel_total,
                "toll_per_trip": toll_total,
                "escort_per_trip": escort_total,
                "maint_tire_per_trip": maint_total + tire_total,
                "cargo_insurance_per_trip": cargo_ins,
                "accessorial_per_trip": accessorial,
                "trip_variable": trip_variable,
                "fixed_per_shipment": fixed_per_ship,
                "should_cost_per_trip": should_cost,
                "trip_cost_with_margin": trip_cost_wm,
                "blended_rate": blended,
                "risk_cost_per_trip": risk_cost,
                "damage_cost": damage_cost,
                "rest_cost_extra": rest_cost_extra,
                "annual_tco": annual_tco,
                "transit_days": transit_days,
                "drive_hours": drive_h,
                "rest_breaks_required": rest_breaks,
                "load_factor": lf_route,
                "risk_score": route_risk,
                "max_segment_risk": max_risk_score,
                "escort_required": escort_req_opt or any(
                    get_zone_info(w["zone"]).get("escort_required", False) for w in ordered_wps
                ),
                "co2e_per_trip_kg": co2e_trip_kg,
                "co2e_annual_ton": co2e_annual_ton,
                "carbon_cost_annual": carbon_cost_ann,
                "has_helper": has_helper_v,
                "helper_cost_annual": (float(helper_monthly_opt) * (1 + float(driver_benefits_opt)/100) * 12) if has_helper_v else 0.0,
                # unit economics
                "cost_per_order": safe_divide(annual_tco, float(orders_opt) * float(shipments_opt) * 12),
                "cost_per_kg":    safe_divide(annual_tco, max(float(kg_opt),1) * float(shipments_opt) * 12),
                "cost_per_pallet":safe_divide(annual_tco, max(float(pal_opt),1) * float(shipments_opt) * 12),
            }

        # Build all alternatives
        alternatives = []
        wp_pts = waypoints  # list of dicts with lat, lon, name, zone, dwell_h

        # 1. Direct
        alt = compute_route_full([])
        alternatives.append(alt)

        # 2. Permutations of waypoints (cap at 5040 = 7!)
        if wp_pts:
            max_perms = {0:1, 1:1, 2:2, 3:6, 4:24, 5:120, 6:720, 7:5040, 8:40320}.get(len(wp_pts), 120)
            cap = min(max_perms, 5040)
            perms = list(iperms(wp_pts))[:cap]
            for perm in perms:
                alt = compute_route_full(list(perm))
                alternatives.append(alt)

        # Normalize & score
        def _norm(vals):
            mn, mx = min(vals), max(vals)
            return [(v - mn) / (mx - mn) if mx > mn else 0.5 for v in vals]

        dists  = [a["distance_road_km"] for a in alternatives]
        costs  = [a["annual_tco"]        for a in alternatives]
        times  = [a["transit_days"]      for a in alternatives]
        risks  = [a["risk_score"]        for a in alternatives]
        esgs   = [a["co2e_per_trip_kg"]  for a in alternatives]

        nd = _norm(dists); nc = _norm(costs); nt = _norm(times); nr = _norm(risks); ne = _norm(esgs)
        tw_safe = max(total_w, 1)
        for i, alt in enumerate(alternatives):
            alt["norm_distance"] = nd[i]; alt["norm_cost"] = nc[i]; alt["norm_time"] = nt[i]
            alt["norm_risk"] = nr[i]; alt["norm_esg"] = ne[i]
            alt["composite_score"] = (
                w_dist/tw_safe * nd[i] + w_cost/tw_safe * nc[i] +
                w_time/tw_safe * nt[i] + w_risk/tw_safe * nr[i] + w_esg/tw_safe * ne[i]
            )

        alternatives.sort(key=lambda x: x["composite_score"])
        st.session_state["route_optimizer_results"] = alternatives
        st.rerun()

    # ── RESULTS ───────────────────────────────────────────────────────────
    results = st.session_state.get("route_optimizer_results", [])
    if not results:
        st.markdown("<div class='v46-note'>Configure os parâmetros acima e clique em <b>Calcular & ranquear todas as rotas</b>.</div>", unsafe_allow_html=True)
        return

    best = results[0]

    # ── Best route hero card ──────────────────────────────────────────────
    esc_tag = " · <b style='color:#f87171'>🔒 Escolta obrigatória</b>" if best.get("escort_required") else ""
    helper_tag = " · <b style='color:#fbbf24'>👤 Ajudante incluso</b>" if best.get("has_helper") else ""
    rest_tag = f" · <b style='color:#f59e0b'>⏸ {best['rest_breaks_required']} parada(s) HoS</b>" if best.get("rest_breaks_required", 0) > 0 else ""
    st.markdown(f"""<div class="v46-decision good" style="margin-top:8px">
        <div class="v46-decision-title">🏆 Melhor rota: {escape(best['label'])}</div>
        <div class="v46-decision-body" style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px">
            <div><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Score composto</div><div style='font-family:IBM Plex Mono;font-size:1.1rem;color:#34d399;font-weight:700'>{best['composite_score']:.3f}</div></div>
            <div><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Annual TCO</div><div style='font-family:IBM Plex Mono;font-size:1.1rem;color:#60a5fa;font-weight:700'>{reporting_currency} {best['annual_tco']:,.0f}</div></div>
            <div><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Distância estrada</div><div style='font-family:IBM Plex Mono;font-size:1.1rem;color:#e2e8f0;font-weight:600'>{best['distance_road_km']:,.0f} km</div></div>
            <div><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Transit time</div><div style='font-family:IBM Plex Mono;font-size:1.1rem;color:#e2e8f0;font-weight:600'>{best['transit_days']:.2f} dias</div></div>
            <div><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Risk score</div><div style='font-family:IBM Plex Mono;font-size:1.1rem;color:#fbbf24;font-weight:600'>{best['risk_score']:.1f}/5</div></div>
            <div><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>CO₂e / viagem</div><div style='font-family:IBM Plex Mono;font-size:1.1rem;color:#34d399;font-weight:600'>{best['co2e_per_trip_kg']:.1f} kg</div></div>
            <div><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Load factor</div><div style='font-family:IBM Plex Mono;font-size:1.1rem;color:#60a5fa;font-weight:600'>{best['load_factor']*100:.1f}%</div></div>
            <div><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Cost / order</div><div style='font-family:IBM Plex Mono;font-size:1.1rem;color:#e2e8f0;font-weight:600'>{reporting_currency} {best['cost_per_order']:,.2f}</div></div>
        </div>
        <div style='margin-top:10px;font-size:.8rem;color:#94a3b8'>{esc_tag}{helper_tag}{rest_tag}</div>
    </div>""", unsafe_allow_html=True)

    # ── Cost waterfall for best route ─────────────────────────────────────
    wf_items = [
        ("Combustível (carg.+vazio)",    best["fuel_per_trip"]),
        ("Pedágios",                     best["toll_per_trip"]),
        ("Manutenção + pneus",           best["maint_tire_per_trip"]),
        ("Seguro de carga (ad val+GRIS)",best["cargo_insurance_per_trip"]),
        ("Escolta / segurança",          best["escort_per_trip"]),
        ("Accessorials / detention",     best["accessorial_per_trip"]),
        ("Custo fixo alocado / viagem",  best["fixed_per_shipment"]),
        ("Margem transportadora",        best["trip_cost_with_margin"] - best["should_cost_per_trip"]),
        ("Risco (overflow + damage)",    best["risk_cost_per_trip"]),
    ]
    wf_html_r = "".join(
        f"<div style='display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(148,163,184,.07)'>"
        f"<span style='font-size:.77rem;color:#94a3b8'>{lbl}</span>"
        f"<span style='font-family:IBM Plex Mono,monospace;font-size:.77rem;color:#e2e8f0'>{reporting_currency} {val:,.2f}</span></div>"
        for lbl, val in wf_items if abs(val) > 0.001
    )
    st.markdown(f"""<div class="v46-svc-result" style="padding:14px 18px;margin:10px 0">
        <div style='font-size:.82rem;font-weight:600;color:#6ee7b7;margin-bottom:8px'>📐 Composição de custo — melhor rota</div>
        {wf_html_r}
        <div style='display:flex;justify-content:space-between;padding:7px 0 0 0;margin-top:4px;border-top:1px solid rgba(16,185,129,.3)'>
            <span style='font-size:.84rem;font-weight:700;color:#f1f5f9'>Total / viagem (blended + risco)</span>
            <span style='font-family:IBM Plex Mono,monospace;font-size:.96rem;font-weight:700;color:#34d399'>{reporting_currency} {best["blended_rate"] + best["risk_cost_per_trip"]:,.2f}</span>
        </div>
    </div>""", unsafe_allow_html=True)

    # ── Full ranking table ────────────────────────────────────────────────
    st.markdown("<div class='v46-plain-title'>Ranking completo de rotas</div>", unsafe_allow_html=True)
    table_rows = []
    for i, alt in enumerate(results[:15]):
        table_rows.append({
            "Rank":         i + 1,
            "Rota":         alt["label"],
            "Paradas":      alt["n_stops"],
            "Dist. km":     f"{alt['distance_road_km']:,.0f}",
            "Annual TCO":   fmt_money(alt["annual_tco"], reporting_currency, compact=True),
            "Custo/viagem": fmt_money(alt["blended_rate"] + alt["risk_cost_per_trip"], reporting_currency),
            "Custo/order":  fmt_money(alt["cost_per_order"], reporting_currency),
            "Transit (d)":  f"{alt['transit_days']:.2f}",
            "HoS breaks":   str(alt.get("rest_breaks_required", 0)),
            "Load %":       f"{alt['load_factor']*100:.1f}%",
            "Risk":         f"{alt['risk_score']:.1f}/5",
            "Escolta":      "✅" if alt.get("escort_required") else "—",
            "Ajudante":     "✅" if alt.get("has_helper") else "—",
            "CO₂e (kg)":    f"{alt['co2e_per_trip_kg']:.1f}",
            "Score":        f"{alt['composite_score']:.3f}",
        })
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    # ── Chart: top 5 routes cost breakdown ───────────────────────────────
    if PLOTLY_AVAILABLE and len(results) > 1:
        top5 = results[:min(5, len(results))]
        labels_t5 = [f"#{i+1} {a['label'][:25]}" for i, a in enumerate(top5)]
        cost_components = {
            "Combustível":  [a["fuel_per_trip"] for a in top5],
            "Pedágios":     [a["toll_per_trip"]  for a in top5],
            "Escolta":      [a["escort_per_trip"] for a in top5],
            "Seguro carga": [a["cargo_insurance_per_trip"] for a in top5],
            "Custo fixo":   [a["fixed_per_shipment"] for a in top5],
            "Risco":        [a["risk_cost_per_trip"] for a in top5],
        }
        colors_comp = ["#3b82f6","#f59e0b","#ef4444","#8b5cf6","#64748b","#f87171"]
        fig_stack = go.Figure()
        for (comp_name, vals), color in zip(cost_components.items(), colors_comp):
            if any(v > 0.1 for v in vals):
                fig_stack.add_trace(go.Bar(name=comp_name, x=labels_t5, y=vals, marker_color=color))
        fig_stack.update_layout(
            barmode="stack", title="Composição de custo por viagem — top 5 rotas",
            yaxis_title=f"{reporting_currency} / viagem", height=340,
        )
        fig_c1, fig_c2 = st.columns(2)
        with fig_c1:
            st.markdown("<div class='v46-chart'>", unsafe_allow_html=True)
            st.plotly_chart(apply_chart_theme(fig_stack, 340), use_container_width=True, config={"displayModeBar": False})
            st.markdown("</div>", unsafe_allow_html=True)

        # Scatter: cost vs risk
        with fig_c2:
            st.markdown("<div class='v46-chart'>", unsafe_allow_html=True)
            labels_all = [f"#{i+1}" for i in range(len(results))]
            costs_all  = [a["annual_tco"] for a in results]
            risks_all  = [a["risk_score"] for a in results]
            scores_all = [a["composite_score"] for a in results]
            fig_sc = go.Figure(go.Scatter(
                x=risks_all, y=costs_all,
                mode="markers+text", text=labels_all, textposition="top center",
                marker=dict(
                    size=[16 if i == 0 else 10 for i in range(len(results))],
                    color=scores_all, colorscale="RdYlGn_r", showscale=True,
                    colorbar=dict(title="Score", thickness=12, len=0.8),
                    line=dict(width=1, color="rgba(255,255,255,.2)"),
                ),
                hovertemplate="<b>%{text}</b><br>Risk: %{x:.1f}<br>TCO: %{y:,.0f}<extra></extra>",
            ))
            fig_sc.update_layout(
                title="Custo × Risco — todas as rotas",
                xaxis_title="Risk score (1–5)", yaxis_title=f"Annual TCO ({reporting_currency})",
                height=340,
            )
            st.plotly_chart(apply_chart_theme(fig_sc, 340), use_container_width=True, config={"displayModeBar": False})
            st.markdown("</div>", unsafe_allow_html=True)

    # ── Mapa dinâmico — Leaflet + OSRM (rota real nas rodovias) ────────────
    st.markdown("<div class='v46-chart' style='padding:0;overflow:hidden'>", unsafe_allow_html=True)

    # Build the full ordered point sequence for the best route
    best_route_points = (
        [{"lat": float(origin_lat), "lon": float(origin_lon), "name": origin_name, "type": "origin"}]
        + [{"lat": float(w["lat"]), "lon": float(w["lon"]), "name": w["name"], "type": "waypoint"} for w in (waypoints if waypoints else [])]
        + [{"lat": float(dest_lat), "lon": float(dest_lon), "name": dest_name, "type": "destination"}]
    )
    # All route points for top-3 alternatives (we pass direct O→D for each)
    top3_routes = []
    for ri, alt in enumerate(results[:3]):
        if ri == 0:
            # Best route: use full waypoint sequence
            pts = best_route_points
        else:
            # Other routes: direct O→D (we don't have their waypoint permutation)
            pts = [
                {"lat": float(origin_lat), "lon": float(origin_lon), "name": origin_name, "type": "origin"},
                {"lat": float(dest_lat), "lon": float(dest_lon), "name": dest_name, "type": "destination"},
            ]
        top3_routes.append({
            "label": alt["label"],
            "score": alt["composite_score"],
            "tco": alt["annual_tco"],
            "risk": alt["risk_score"],
            "points": pts,
        })

    import json as _json
    routes_json = _json.dumps(top3_routes)
    currency_js = reporting_currency.replace("'", "\'")

    map_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  body{{margin:0;padding:0;background:#0a1628;font-family:-apple-system,sans-serif}}
  #map{{width:100%;height:520px;border-radius:0 0 18px 18px}}
  #legend{{position:absolute;top:12px;left:50%;transform:translateX(-50%);z-index:999;
    background:rgba(10,22,40,.92);border:1px solid rgba(148,163,184,.2);
    border-radius:12px;padding:10px 16px;display:flex;gap:16px;align-items:center;
    backdrop-filter:blur(8px);white-space:nowrap}}
  .leg-item{{display:flex;align-items:center;gap:6px;font-size:12px;color:#94a3b8}}
  .leg-dot{{width:12px;height:4px;border-radius:2px}}
  #status{{position:absolute;bottom:12px;left:12px;z-index:999;
    background:rgba(10,22,40,.9);border:1px solid rgba(16,185,129,.3);
    border-radius:8px;padding:6px 12px;font-size:11px;color:#6ee7b7;
    font-family:monospace}}
  #info-panel{{position:absolute;top:12px;right:12px;z-index:999;
    background:rgba(10,22,40,.92);border:1px solid rgba(148,163,184,.2);
    border-radius:12px;padding:12px 14px;min-width:200px;
    backdrop-filter:blur(8px)}}
  .info-row{{display:flex;justify-content:space-between;gap:16px;
    font-size:11px;padding:3px 0;border-bottom:1px solid rgba(148,163,184,.08)}}
  .info-row:last-child{{border:none}}
  .info-label{{color:#64748b}}
  .info-val{{color:#e2e8f0;font-family:monospace;font-weight:600}}
  .info-title{{font-size:12px;font-weight:600;color:#f1f5f9;margin-bottom:8px}}
  .loading{{display:flex;align-items:center;gap:8px;color:#60a5fa;font-size:12px}}
  .spinner{{width:14px;height:14px;border:2px solid rgba(99,102,241,.3);
    border-top-color:#6366f1;border-radius:50%;animation:spin .6s linear infinite}}
  @keyframes spin{{to{{transform:rotate(360deg)}}}}
</style>
</head>
<body>
<div id="legend">
  <div class="leg-item"><div class="leg-dot" style="background:#10b981;width:20px;height:4px"></div>#1 Best route (OSRM)</div>
  <div class="leg-item"><div class="leg-dot" style="background:#3b82f6;width:14px;height:2px"></div>#2 Alternative</div>
  <div class="leg-item"><div class="leg-dot" style="background:#f59e0b;width:14px;height:2px"></div>#3 Alternative</div>
</div>
<div id="map"></div>
<div id="status">Carregando rota via OSRM...</div>
<div id="info-panel">
  <div class="info-title">🏆 Melhor rota</div>
  <div id="info-content"><div class="loading"><div class="spinner"></div>Calculando...</div></div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const ROUTES = {routes_json};
const CURRENCY = '{currency_js}';
const COLORS = ['#10b981','#3b82f6','#f59e0b'];
const WEIGHTS = [5, 2.5, 2];

const map = L.map('map', {{
  center: [-15, -52],
  zoom: 4,
  zoomControl: true,
  attributionControl: false,
}});

L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  maxZoom: 18,
  subdomains: 'abcd',
}}).addTo(map);

L.control.attribution({{prefix: '© OpenStreetMap · CartoDB · OSRM'}}).addTo(map);

const markerIcon = (color, label) => L.divIcon({{
  html: `<div style="background:${{color}};width:12px;height:12px;border-radius:50%;
    border:2px solid white;box-shadow:0 0 6px ${{color}}88;
    display:flex;align-items:center;justify-content:center;font-size:7px;color:white;font-weight:700">${{label}}</div>`,
  iconSize:[12,12], iconAnchor:[6,6], className:''
}});

const waypointIcon = L.divIcon({{
  html: `<div style="background:#60a5fa;width:10px;height:10px;border-radius:3px;
    border:2px solid white;box-shadow:0 0 4px #60a5fa88"></div>`,
  iconSize:[10,10], iconAnchor:[5,5], className:''
}});

async function fetchOSRMRoute(points) {{
  const coords = points.map(p => `${{p.lon}},${{p.lat}}`).join(';');
  const url = `https://router.project-osrm.org/route/v1/driving/${{coords}}?overview=full&geometries=geojson&steps=false`;
  try {{
    const resp = await fetch(url, {{signal: AbortSignal.timeout(8000)}});
    if (!resp.ok) return null;
    const data = await resp.json();
    if (data.code !== 'Ok' || !data.routes?.length) return null;
    return {{
      coords: data.routes[0].geometry.coordinates.map(c => [c[1], c[0]]),
      distance: (data.routes[0].distance / 1000).toFixed(1),
      duration: (data.routes[0].duration / 3600).toFixed(1),
    }};
  }} catch(e) {{
    return null;
  }}
}}

function fallbackLine(points, color, weight, opacity) {{
  const latlngs = points.map(p => [p.lat, p.lon]);
  return L.polyline(latlngs, {{color, weight, opacity, dashArray: '6 4'}});
}}

function updateInfoPanel(route, osrmData) {{
  const tco = (route.tco / 1e6).toFixed(2);
  const dist = osrmData ? osrmData.distance : 'N/A';
  const dur  = osrmData ? osrmData.duration : 'N/A';
  document.getElementById('info-content').innerHTML = `
    <div class="info-row"><span class="info-label">Rota</span><span class="info-val" style="font-size:10px;max-width:130px;text-align:right">${{route.label.slice(0,30)}}</span></div>
    <div class="info-row"><span class="info-label">Annual TCO</span><span class="info-val">${{CURRENCY}} ${{tco}}M</span></div>
    <div class="info-row"><span class="info-label">Score</span><span class="info-val">${{route.score.toFixed(3)}}</span></div>
    <div class="info-row"><span class="info-label">Risk</span><span class="info-val">${{route.risk.toFixed(1)}}/5</span></div>
    ${{osrmData ? `
    <div class="info-row"><span class="info-label">Dist. real (OSRM)</span><span class="info-val">${{dist}} km</span></div>
    <div class="info-row"><span class="info-label">Drive time</span><span class="info-val">${{dur}} h</span></div>
    ` : '<div class="info-row"><span class="info-label">Rota</span><span class="info-val" style="color:#fbbf24">linha reta (offline)</span></div>'}}
  `;
}}

const allBounds = [];
const layerGroups = [];

async function drawAllRoutes() {{
  const statusEl = document.getElementById('status');
  
  for (let ri = 0; ri < ROUTES.length; ri++) {{
    const route = ROUTES[ri];
    const color = COLORS[ri];
    const weight = WEIGHTS[ri];
    const pts = route.points;
    
    if (ri === 0) {{
      statusEl.textContent = `Buscando rota real via OSRM (#${{ri+1}})...`;
    }}
    
    const group = L.layerGroup().addTo(map);
    layerGroups.push(group);
    
    const osrmData = ri <= 1 ? await fetchOSRMRoute(pts) : null;
    
    if (osrmData) {{
      const polyline = L.polyline(osrmData.coords, {{
        color,
        weight,
        opacity: ri === 0 ? 0.95 : 0.55,
        smoothFactor: 1,
      }}).addTo(group);
      
      if (ri === 0) {{
        polyline.bindTooltip(
          `<b>#1 Melhor rota</b><br>${{CURRENCY}} ${{(route.tco/1e6).toFixed(2)}}M/ano<br>Dist. OSRM: ${{osrmData.distance}} km<br>Tempo: ${{osrmData.duration}} h<br>Score: ${{route.score.toFixed(3)}}`,
          {{sticky: true, className: 'route-tooltip'}}
        );
        updateInfoPanel(route, osrmData);
        osrmData.coords.forEach(c => allBounds.push(c));
      }}
    }} else {{
      fallbackLine(pts, color, weight, ri === 0 ? 0.85 : 0.45).addTo(group);
      if (ri === 0) {{
        updateInfoPanel(route, null);
        pts.forEach(p => allBounds.push([p.lat, p.lon]));
      }}
    }}
    
    // Markers for origin / waypoints / destination
    pts.forEach((pt, pi) => {{
      let icon, title;
      if (pt.type === 'origin') {{
        icon = markerIcon('#10b981', 'O');
        title = `🟢 Origem: ${{pt.name.split(' - ')[0]}}`;
      }} else if (pt.type === 'destination') {{
        icon = markerIcon('#ef4444', 'D');
        title = `🔴 Destino: ${{pt.name.split(' - ')[0]}}`;
      }} else {{
        icon = waypointIcon;
        title = `🔵 Waypoint: ${{pt.name.split(' - ')[0]}}`;
      }}
      if (ri === 0 || pt.type !== 'waypoint') {{
        L.marker([pt.lat, pt.lon], {{icon}})
          .bindPopup(`<b>${{title}}</b><br>Lat: ${{pt.lat.toFixed(4)}} · Lon: ${{pt.lon.toFixed(4)}}`)
          .addTo(ri === 0 ? group : group);
      }}
    }});
    
    if (ri === 0) statusEl.textContent = `✓ Rota #1 traçada via OSRM (rodovias reais)`;
  }}
  
  if (allBounds.length > 1) {{
    try {{ map.fitBounds(allBounds, {{padding: [40, 40]}}); }} catch(e) {{}}
  }}
  
  statusEl.textContent = `✓ ${{ROUTES.length}} rotas calculadas — melhor: ${{ROUTES[0].label.slice(0,25)}}`;
}}

drawAllRoutes().catch(e => {{
  document.getElementById('status').textContent = '⚠ OSRM timeout — usando linhas diretas';
}});
</script>
</body>
</html>"""

    _stc.html(map_html, height=540, scrolling=False)
    st.markdown("</div>", unsafe_allow_html=True)
    st.caption("Mapa: OpenStreetMap + CartoDB · Roteamento: OSRM (router.project-osrm.org) · Rota #1 traçada nas rodovias reais. Se OSRM timeout (>8s), exibe linha direta como fallback.")

    # ── Executive insight ─────────────────────────────────────────────────
    if len(results) > 1:
        shortest = min(results, key=lambda x: x["distance_road_km"])
        cheapest = min(results, key=lambda x: x["annual_tco"])
        safest   = min(results, key=lambda x: x["risk_score"])
        greenest = min(results, key=lambda x: x["co2e_per_trip_kg"])
        fastest  = min(results, key=lambda x: x["transit_days"])

        cost_diff_shortest_vs_best = shortest["annual_tco"] - best["annual_tco"]
        is_best_also_shortest = shortest["label"] == best["label"]
        is_best_also_cheapest = cheapest["label"] == best["label"]

        insight_lines = []
        if not is_best_also_shortest:
            insight_lines.append(
                f"A rota mais curta (<b>{shortest['label'][:30]}</b>, {shortest['distance_road_km']:,.0f}km) "
                f"{'custa <b style=\"color:#f87171\">' + reporting_currency + f' {cost_diff_shortest_vs_best:,.0f} a mais</b>' if cost_diff_shortest_vs_best > 0 else 'custa menos'} "
                f"que a rota recomendada — "
                + ("escolta obrigatória e maior risco eliminam a vantagem de distância." if shortest.get("escort_required") and not best.get("escort_required") else "o modelo de custo completo favorece outra sequência.")
            )
        if not is_best_also_cheapest:
            insight_lines.append(f"A rota de menor custo absoluto é <b>{cheapest['label'][:30]}</b> ({reporting_currency} {cheapest['annual_tco']:,.0f}/ano) mas score de risco é {cheapest['risk_score']:.1f}/5.")
        if best.get("rest_breaks_required", 0) > 0:
            insight_lines.append(f"⏸ A rota recomendada exige <b>{best['rest_breaks_required']} parada(s) de descanso</b> por HoS — considere relay driver ou ponto intermediário para otimizar tempo.")
        if best.get("has_helper"):
            insight_lines.append(f"👤 Ajudante necessário para este veículo/tipo de carga — custo anual de ajudante: <b>{reporting_currency} {best.get('helper_cost_annual',0):,.0f}</b>. Avaliar automação de carga/descarga.")
        insight_lines.append(f"🌿 Rota mais verde: <b>{greenest['label'][:28]}</b> ({greenest['co2e_per_trip_kg']:.1f} kg CO₂e/viagem).")

        st.markdown(
            "<div class='v46-insight'><b>💡 Executive insight:</b><ul style='margin:8px 0 0 0;padding-left:18px'>"
            + "".join(f"<li style='margin-bottom:6px;color:#94a3b8'>{line}</li>" for line in insight_lines)
            + "</ul></div>",
            unsafe_allow_html=True,
        )






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
    concentration_threshold = st.slider("Concentration alert threshold %", min_value=30.0, max_value=90.0, value=60.0, step=5.0, key="concentration_threshold", help="Alert when a single supplier exceeds this share")

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
    "7 · Executive Dash", "🗺️ Route Optimizer",
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
                if (service_scope or DEFAULT_SERVICE_SCOPE) == "Logistics / Transport Services":
                    sp_ = render_logistics_route_tco(key_prefix=f"cur_svc__{country}", country=country, supplier_label=f"{country} baseline", reporting_currency=currency_symbol, is_baseline=True)
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
                        if (service_scope or DEFAULT_SERVICE_SCOPE) == "Logistics / Transport Services":
                            sp_s = render_logistics_route_tco(key_prefix=f"prop_svc__{country}__{sup}", country=country, supplier_label=f"{country} | {disp}", reporting_currency=currency_symbol, is_baseline=False)
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
    render_section(
        "Supplier Risk & Strategic Constraints",
        "7-axis risk scoring (Supply · Quality · Financial · Compliance · ESG · Logistics · Geopolitical) · Spider charts · Governance blend · LP optimization feed",
        "#ef4444",
    )

    with st.expander("⚙ Risk dimension weights", expanded=False):
        st.caption("Weights define relative importance of each axis. McKinsey SCM standard defaults. Total should = 100.")
        rw_cols = st.columns(len(DEFAULT_RISK_WEIGHTS))
        risk_weights: Dict[str, float] = {}
        for idx_, dim_ in enumerate(DEFAULT_RISK_WEIGHTS):
            with rw_cols[idx_]:
                risk_weights[dim_] = st.number_input(
                    dim_, min_value=0.0, max_value=100.0,
                    value=DEFAULT_RISK_WEIGHTS[dim_], step=1.0, key=f"rw__{dim_}",
                    help={"Supply":"Lead time, single-source, capacity","Quality":"NCR rate, spec compliance, recalls","Financial":"Financial health, dependency, concentration","Compliance":"Sanctions, FCPA, LGPD, anti-bribery","ESG":"Deforestation, carbon, modern slavery","Logistics":"Freight reliability, port risk, customs","Geopolitical":"Country risk, tariff, currency instability"}.get(dim_,""),
                )
        total_w_d = sum(risk_weights.values())
        wc = "#34d399" if abs(total_w_d-100)<0.5 else "#f87171"
        st.markdown(f"<span style='font-size:.78rem;color:{wc}'>Weights total: <b>{total_w_d:.1f}%</b> {'✓' if abs(total_w_d-100)<0.5 else '— adjust to reach 100%'}</span>", unsafe_allow_html=True)
    if "risk_weights" not in dir():
        risk_weights = dict(DEFAULT_RISK_WEIGHTS)

    risk_inputs: Dict = {s: {} for s in SUPPLIERS}
    for sup in SUPPLIERS:
        gov_risk = governance_risk_defaults(supplier_management_inputs, sup)
        cust_adj = float(custom_risk_adj.get(sup, 0.0))
        gov_sc = supplier_management_inputs.get(sup, {}).get("Governance score", 75.0)
        with st.expander(f"{supplier_display_name(sup)}", expanded=(sup == SUPPLIERS[0])):
            cst = st.columns([1, 1, 1, 1, 2])
            with cst[0]: st.checkbox("Approved", value=DEFAULT_APPROVED[sup], key=approved_key(sup))
            with cst[1]: st.checkbox("Kraljic min", value=DEFAULT_KRALJIC_REQUIRED[sup], key=kraljic_key(sup))
            with cst[2]: st.number_input("Min share %", 0.0, 100.0, DEFAULT_MIN_SHARE[sup], 1.0, key=min_key(sup))
            with cst[3]: st.number_input("Max share %", 0.0, 100.0, DEFAULT_MAX_SHARE[sup], 1.0, key=max_key(sup))
            with cst[4]:
                g_tier = supplier_management_inputs.get(sup,{}).get("Governance tier","—")
                st.markdown(f"<div style='font-size:.78rem;color:#94a3b8;padding-top:8px'>Gov: <b style='color:{service_score_color(gov_sc)}'>{gov_sc:.0f}/100</b> · {g_tier} · Custom adj: <b>{cust_adj:+.2f}</b> · <i>1=low risk, 5=high risk</i></div>", unsafe_allow_html=True)

            dims_list = list(DEFAULT_RISK_WEIGHTS.keys())
            half = (len(dims_list)+1)//2
            for row_dims in [dims_list[:half], dims_list[half:]]:
                rcols = st.columns(len(row_dims))
                for ci, dim_ in enumerate(row_dims):
                    with rcols[ci]:
                        dfr = blend_risk_default(DEFAULT_RISK.get(sup,{}).get(dim_,3.0), gov_risk.get(dim_,3.0), cust_adj)
                        risk_inputs[sup][dim_] = st.slider(dim_, 1.0, 5.0, dfr, 0.1, key=f"risk__{sup}__{dim_}")

            if PLOTLY_AVAILABLE:
                vals_s = [risk_inputs[sup][d] for d in dims_list]
                ws_score = sum(risk_inputs[sup][d]*risk_weights.get(d,0) for d in dims_list)/max(sum(risk_weights.values()),1)
                rt_col = {"good":"#34d399","amber":"#fbbf24","bad":"#f87171"}.get(risk_tone(ws_score),"#60a5fa")
                fig_sp = go.Figure(go.Scatterpolar(
                    r=vals_s+[vals_s[0]], theta=dims_list+[dims_list[0]],
                    fill="toself", fillcolor="rgba(239,68,68,.12)",
                    line=dict(color="#ef4444",width=2),
                ))
                fig_sp.update_layout(
                    polar=dict(radialaxis=dict(visible=True,range=[1,5],tickfont=dict(size=9),gridcolor="rgba(148,163,184,.12)"),angularaxis=dict(tickfont=dict(size=10,color="#94a3b8")),bgcolor="rgba(15,23,42,.4)"),
                    showlegend=False, height=250, margin=dict(l=55,r=55,t=25,b=25), paper_bgcolor="rgba(0,0,0,0)",
                )
                lc, rc_chart = st.columns([.55,.45])
                with lc:
                    st.plotly_chart(apply_chart_theme(fig_sp,250), use_container_width=True, config={"displayModeBar":False})
                with rc_chart:
                    def _risk_color(v): return "#f87171" if v>=3.5 else "#fbbf24" if v>=2.5 else "#34d399"
                    dim_rows = "".join(
                        f"<div style='display:flex;justify-content:space-between;font-size:.74rem;padding:2px 0'>"
                        f"<span style='color:#94a3b8'>{d}</span>"
                        f"<span style='color:{_risk_color(risk_inputs[sup][d])};font-family:IBM Plex Mono,monospace'>{risk_inputs[sup][d]:.1f}</span>"
                        f"</div>"
                        for d in dims_list
                    )
                    st.markdown(f"""<div class="v46-gov-card" style="margin-top:8px">
                    <div style='font-size:.68rem;color:#64748b;text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px'>Risk Breakdown</div>
                    <div style='font-size:1.5rem;font-weight:700;color:{rt_col};font-family:"IBM Plex Mono",monospace'>{ws_score:.2f}<span style='font-size:.85rem;color:#64748b'>/5</span></div>
                    <div style='font-size:.72rem;color:#64748b;margin-bottom:10px'>Weighted risk score</div>
                    {dim_rows}</div>""", unsafe_allow_html=True)

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
            try:
                # Lower Risk: allocate proportional to inverse risk score (safest suppliers get highest share)
                lr_prefs = {s: max(0.0, 6.0 - supplier_risk[s]) for s in SUPPLIERS}
                lr_shares = {c: allocate_with_bounds(lr_prefs, get_min_shares(), get_max_shares(), 100.0) for c in COUNTRIES}
                _, _, _, lr_total = calc_scenario(lr_shares, country_inputs, proposal_inputs, supplier_risk, rate_method)
                fr_rows.append({"Scenario": "Lower Risk", "Risk": lr_total["Weighted Risk"], "Econ Delta": lr_total["Economic All-In Delta"]})
            except: pass
            frf = pd.DataFrame(fr_rows)
            col_map = {"Current": "#64748b", "Optimized": "#10b981", "Lower Risk": "#f59e0b"}
            size_map = {"Current": 18, "Optimized": 18, "Lower Risk": 18}
            symbol_map = {"Current": "circle", "Optimized": "diamond", "Lower Risk": "square"}
            fig_fr = go.Figure()
            for _, rw in frf.iterrows():
                scen = rw["Scenario"]
                fig_fr.add_trace(go.Scatter(
                    x=[rw["Risk"]], y=[rw["Econ Delta"]],
                    mode="markers+text",
                    text=[scen],
                    textposition="top center",
                    marker=dict(
                        size=size_map.get(scen, 16),
                        color=col_map.get(scen, "#3b82f6"),
                        symbol=symbol_map.get(scen, "circle"),
                        line=dict(width=2, color="rgba(255,255,255,.25)"),
                    ),
                    showlegend=True,
                    name=scen,
                    hovertemplate=f"<b>{scen}</b><br>Risk: %{{x:.2f}}/5<br>Econ delta: {currency_symbol} %{{y:,.0f}}<extra></extra>",
                ))
            fig_fr.add_hline(y=0, line_dash="dash", line_color="rgba(148,163,184,.3)", annotation_text="Break-even", annotation_font_color="#64748b", annotation_position="right")
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

    # ── v47 New Modules ────────────────────────────────────────────────────────

    with stack("Sensitivity Analysis", "What-if: how price, volume, FX and rates shift the economic outcome.", "🎚", "#f59e0b", "What-if"):
        render_sensitivity_panel(
            base_econ_delta=final_econ,
            base_spend=float(total.get("Current Spend", 0.0)),
            country_inputs=country_inputs,
            proposal_inputs=proposal_inputs,
            all_shares=final_shares,
            supplier_risk=supplier_risk,
            method=rate_method,
            currency=currency_symbol,
        )

    with stack("Award Scenario Comparison", "Save and compare up to 3 sourcing scenarios side-by-side.", "🏆", "#06b6d4", "Scenarios"):
        render_award_scenarios(total, supplier_focus_df, final_shares, currency_symbol)

    with stack("Kraljic Portfolio Matrix", "Position suppliers by spend impact × supply risk — defines sourcing strategy per quadrant.", "🔷", "#8b5cf6", "Portfolio"):
        render_kraljic_matrix(supplier_focus_df, risk_inputs, risk_weights, total, currency_symbol)

    with stack("BATNA / ZOPA Negotiation", "Walk-away price, ZOPA zone and lever quantification before entering negotiations.", "🤝", "#ec4899", "Negotiation"):
        render_batna_zopa(total, country_inputs, proposal_inputs, supplier_focus_df, currency_symbol)

    with stack("Concentration Risk & Stress Test", "HHI index, single-supplier dependency alerts and failure simulation.", "⚠", "#ef4444", "Risk"):
        render_concentration_risk(
            supplier_df, total, country_inputs, proposal_inputs,
            supplier_risk, rate_method, currency_symbol,
            threshold_pct=float(st.session_state.get("concentration_threshold", 60.0)),
        )

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


# ── Tab 8: Route Optimizer ───────────────────────────────────────────────────
with input_tabs[7]:
    render_route_optimizer(currency_symbol)

st.markdown(
    """<div class="v46-note" style="margin-top:32px;padding:12px 16px;border-radius:10px;background:rgba(15,23,42,.5);border:1px solid rgba(148,163,184,.12)">
    Gross financial cost is separated from treasury return offset. Net Financial Delta is the correct finance view after working-capital carry is considered.
    Finance / Treasury must validate all rate and term assumptions before official saving recognition.
    </div>""",
    unsafe_allow_html=True,
)
