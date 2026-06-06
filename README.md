# Executive Procurement TCO & Should-Cost Dashboard — v36

Two-in-one Streamlit cockpit for procurement decision making:

- **Direct Materials**: landed cost, FX, incoterm, MOQ, unit price × volume, inventory carrying, working capital and supplier optimization.
- **Indirect / Services**: executive services cockpit with service scope, pricing model, headcount/FTE economics, hourly rates, overtime KPIs, supplier scorecards, contract leakage, service should-cost, productivity gains and risk-adjusted service TCO.

## What changed in v36

- Visual lock improvements for KPI cards, executive panels, tables and chart shells to keep dimensions and alignment more consistent.
- Sidebar **Executive result visibility** selector to choose which result stacks appear on screen.
- Added **AI Executive Copilot** stack:
  - button to generate a concise executive recommendation from the current scenario;
  - local deterministic analysis for now, ready to be replaced by a real AI/API call later;
  - copy/paste prompt payload for an external AI tool.
- Direct Materials and Indirect / Services continue to use different visual identities.
- Existing supplier count and top supplier focus sliders are preserved.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notes

- Negative deltas mean savings. Positive deltas mean cost impact.
- Financial assumptions should be validated by Finance/Treasury before official saving recognition.
- Services mode treats proposal spend as risk-adjusted Service TCO after productivity gains.
