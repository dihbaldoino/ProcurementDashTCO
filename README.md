# Executive Procurement TCO & Should-Cost Dashboard v23 FINAL

Final reviewed version for strategic raw-material sourcing decisions.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Core modeling rules

1. **Current baseline is independent from proposals.** Current financial cost and current treasury return use the country current/reference period only.
2. **Supplier proposals use their own proposed payment term.** A 150-day supplier proposal uses a 150-day financial-rate period and a 150-day treasury-return period.
3. **Supplier proposal spend is 100% volume-equivalent spend before financial cost.** The share projection applies the allocation later.
4. **Negative delta = saving. Positive delta = impact.** This is used across spend, financial cost, all-in cost and economic value.
5. **Inventory carrying cost follows ownership.** Lead time is only charged when the buyer owns inventory during transit/stock.

## Final improvements included

- Clear separation between Commercial Spend, Financial Cost, Treasury/Working-Capital Carry, Inventory Carrying Cost and Economic All-In Value.
- Explicit financial audit by country.
- Payment terms and return periods are recalculated supplier-by-supplier.
- Share Projection remains a scenario gadget; supplier proposal inputs remain active and independent.
- Kraljic minimum shares, supplier approval and capacity constraints.
- Infeasible constraints are surfaced instead of silently overridden.
- Exact linear-programming optimization with SciPy when available; conservative grid fallback otherwise.
- Optimization minimizes economic all-in cost first and uses supplier risk as a secondary factor.
- Inventory ownership assumptions by supplier/country.
- Supplier risk matrix and weighted risk.
- Executive charts: Total Cost Stack, Economic Value Decomposition, Supplier Share Projection and Cost x Risk Decision Map.

## Business case preset

The app is preloaded with the DFO / Isopropyl Palmitate scenario:

- Current spend: BRL 20MM.
- ChemPrime: +25% price, 90-day payment term.
- OleoGlobal: 15% below old price, 70-day payment term.
- Overseas: OleoGlobal + 5%, 150-day payment term.
- Distribuicao: OleoGlobal + 9%, 120-day payment term.
- Default strategic allocation: 40% ChemPrime, 40% Overseas, 20% Distribuicao.
- Country-specific financial rates, treasury returns and carrying rates.

## Governance note

Commercial saving, financial impact and working-capital benefit should be reported separately. Final saving recognition should be aligned with Finance/Treasury/Controllership.
