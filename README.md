# Procurement Intelligence Platform — v47

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```

## What's New in v47

### 1. Commodity Price Index Engine (Direct Materials)
- Model base price as a formula: Σ(index × weight%) + basis − discount
- Up to 8 commodities per item (palm oil, soy, crude, ethanol, metals, polymers…)
- Market scenario: current, stress (+X%), floor (−Y%) → TCO impact auto-calculated
- Activating the formula overrides the manual base unit price entry

### 2. ESG & Certification Costs
- 16 built-in certs: RSPO, RTRS, ISCC, Rainforest Alliance, BONSUCRO, FSC, ASC, MSC, Fairtrade, Organic, Halal, Kosher, SA8000, EUDR, Carbon Offset (Scope 3), Custom
- Cost modeled per unit × annual volume → adds to landed price automatically
- Carbon offset uses Scope 3 intensity (tCO₂e/unit) × carbon price
- Organized by category: Deforestation, Carbon, Marine, Regulatory, Social, Quality

### 3. Sensitivity Analysis (Tornado Chart)
- 5 drivers: Price ±30%, Volume ±30%, FX ±30%, Financial rate ±3pp, Inventory rate ±10pp
- Real-time impact on economic all-in delta
- Tornado bar chart ranks drivers by magnitude
- "Apply worst-case stress" button sets all to maximum adverse scenario

### 4. Award Scenario Comparison
- Save up to 3 named scenarios (A / B / C) within session
- Side-by-side KPI table: economic delta, gross delta, spend delta, risk, avg term, top supplier
- Visual delta bar chart comparing all saved scenarios vs Scenario A

### 5. Kraljic Portfolio Matrix (Visual)
- Auto-positions suppliers on 2×2: Spend % (x) × Risk score (y)
- Quadrants: Strategic / Leverage / Bottleneck / Non-critical
- Color-coded quadrant backgrounds + strategy recommendation table

### 6. BATNA / ZOPA Negotiation Calculator
- Buyer BATNA: current economic TCO × max acceptable increase %
- Supplier BATNA: should-cost estimate × min margin %
- ZOPA zone visualization chart
- Negotiation lever table with annual $ value for each lever

### 7. Concentration Risk & Stress Test
- Herfindahl-Hirschman Index (HHI) per country
- Alert when any supplier exceeds configurable threshold (default 60%)
- Single-supplier failure simulation: removes supplier, reallocates volume, shows economic impact

## Architecture
Pure Python + Streamlit + Plotly. No external APIs required.
