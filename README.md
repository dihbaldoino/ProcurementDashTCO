# Executive Procurement TCO & Should-Cost Dashboard — v39

Two-in-one Streamlit cockpit for procurement decision making.

## Modes

- **Direct Materials**: landed cost, FX, incoterm, MOQ, unit price × volume, inventory carrying, working capital and supplier optimization.
- **Indirect / Services**: service scope, pricing model, headcount/FTE economics, hourly rates, overtime KPIs, supplier scorecards, contract leakage, open-cost / should-cost, productivity gains and risk-adjusted service TCO.

## What changed in v39

- Added a visual **Dynamic Market Scope** selector in the sidebar.
- The user can select which countries are included in the analysis instead of being locked to Brazil, Mexico, Argentina and Colombia.
- Added an **Anchor / Primary Country** selector. This country receives its own executive result stack.
- All other selected countries are consolidated into **Other selected markets**.
- Country cards, supplier proposals, supplier performance, custom analysis items, risk constraints, share sliders, optimization and executive results now follow the selected market scope.
- New countries receive practical auto-seeded defaults so the tool remains simple and fast to use, while still allowing the buyer to edit the country assumptions.
- Maintained the two visual identities: Direct Materials and Indirect / Services.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notes

- Negative deltas mean savings. Positive deltas mean cost impact.
- Financial assumptions should be validated by Finance/Treasury before official saving recognition.
- Services mode treats proposal spend as risk-adjusted Service TCO after productivity gains and custom adjustments.
