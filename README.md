# Procurement Intelligence Platform — v46

## What's New in v46

### Visual Redesign (Enterprise Premium)
- **Dark theme** inspired by Bloomberg Terminal + modern SaaS (Vercel, Linear, Stripe)
- **Typography**: Syne (display/headings) + DM Sans (body) + DM Mono (numbers/code)
- **KPI cards** with gradient accent bars, hover lift, count-up animation
- **Glass morphism** panels with backdrop blur and subtle borders
- **Premium sidebar** with dark gradient and styled inputs
- **Animated hero banner** with radial glow effects
- **Styled expanders** with colored left borders and hover states
- **Premium charts** with dark backgrounds, gridlines and Plotly transitions

### Indirect / Services — Amazon Procurement Standard
- **FTE Demand Decomposition**: breaks headcount into productive / overtime / absenteeism-adjusted units — challenges the right-sizing of supplier proposals
- **Rate Card Compliance**: quotes supplier annual FTE cost vs scope-specific benchmark — calculates annual overcharge exposure
- **Contract Leakage Waterfall**: models contracted value → scope additions → emergency requests → rework → SLA credits → actual billed TCO
- **SLA Financial Exposure**: quantifies penalty exposure + business impact from SLA gap before awarding
- **Productivity ROI Tracker**: investment → annual savings → payback months → 3-year net value
- **Multi-Year TCV**: base annual value → escalation → total contract value projection
- **Enhanced Should-Cost Engine**: clean-sheet labor + open-cost breakdown + unexplained quote value
- **New export columns**: Productivity ROI %, Payback Months, SLA Risk Cost, SLA Gap, Rate Card Gap %, Total Contract Value

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Dependencies
- Python 3.11+
- streamlit >= 1.30
- pandas >= 2.0
- plotly >= 5.18
- scipy >= 1.11 (for exact LP optimization; falls back to grid search if not available)

## Architecture
All logic is in `app.py` (Python only + CSS-in-Python). No JavaScript framework required.
