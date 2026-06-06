# Executive Procurement TCO & Should-Cost Dashboard — v41

## What is new in v41

- Added **Global View / Local View** in the sidebar.
- **Global View** keeps the country-based analysis built in previous versions.
- **Local View** lets the user analyze localities, sites, plants, regions or business units inside the selected anchor country.
- Added **Executive View** tab with a concise executive summary.
- Added **Executive Dash View** tab with a visual heatmap and ranking view.
- The heatmap adapts to the selected scope:
  - Global View: country-level points.
  - Local View: locality-level points inside the anchor country.
- Heatmap can be driven by: Spend, Saving, Suppliers, SLA / Performance or Risk.
- Selected countries/localities automatically feed the same TCO, supplier proposal, risk, optimization and executive stacks.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```
