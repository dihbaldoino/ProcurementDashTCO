# Executive Procurement TCO & Should-Cost Dashboard v15

Senior Director Edition for strategic raw-material sourcing decisions.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## What is new in v15

- Commercial spend, gross payment-term financial cost and working-capital economic value are separated.
- Current and new scenarios are compared apples-to-apples.
- Country-specific payment-term rates, treasury returns and inventory carrying rates.
- Supplier proposal inputs remain active and independent from the share sliders.
- Share Projection has Automatic and Manual modes.
- Kraljic minimum share locks the supplier floor in the sliders.
- Supplier approval and maximum share/capacity constraints.
- Multi-dimensional supplier risk scoring and weighted risk.
- Cost Optimization updates the share sliders automatically.
- Optimization minimizes economic all-in cost first and uses weighted risk as tie-breaker.
- Executive charts include Total Cost Stack, Economic Value Decomposition, Supplier Share Projection and Cost x Risk Decision Map.

## Procurement convention

Delta values are displayed as:

- Negative = saving, shown in green.
- Positive = impact, shown in red.

## Important note

Financial cost and treasury return assumptions should be validated by Finance/Treasury before official saving recognition.

## Business Case Preset v16

This version is preloaded with the DFO Isopropyl Palmitate business case assumptions:

- Current spend: BRL 20MM total, with 65% Brazil / 35% LATAM.
- ChemPrime new proposal: +25% price increase.
- OleoGlobal economics: 15% below old price.
- Overseas route: OleoGlobal price + 5%, 150-day payment term.
- Local distributor route: OleoGlobal price + 9%, 120-day payment term.
- Proposed allocation: 40% ChemPrime, 40% Overseas, 20% Local Distribution.
- Country-specific payment-term financial rates, treasury return rates and carrying rates loaded from the business case assumptions.

Recommended use:

```bash
pip install -r requirements.txt
streamlit run app.py
```
