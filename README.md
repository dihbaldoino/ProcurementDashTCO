# Executive Procurement TCO & Should-Cost Dashboard — v34

Two-in-one Streamlit procurement decision cockpit.

## Modes

### Direct Materials
Calculates spend from landed unit price x volume, including:
- quote currency and FX
- Incoterm
- base / quoted unit price
- conversion cost
- fixed margin
- international freight
- insurance
- customs / brokerage fees
- import duties / taxes
- domestic freight
- local taxes
- MOQ flag
- landed unit price and 100% equivalent spend

### Indirect / Services
Calculates proposal spend from Service TCO and transforms the UI according to the selected service scope:
- IT Services / Digital & Outsourcing
- Facilities / Cleaning & Workplace
- Industrial MRO / VMI / Fastenal-style outsourcing
- Professional Services / Consulting
- Marketing / Agency Services
- Logistics / Transport Services
- BPO / Call Center
- Generic Indirect Service

Services mode includes:
- service / buying scope selector
- scope-specific operational drivers
- pricing model selector
- contracted / proposed service value
- budget and demand/scope index
- change orders and scope creep
- internal management cost
- rework / quality cost
- downtime / compliance cost
- SLA credits / rebates
- supplier-led productivity gain field
- risk probability x impact expected risk cost
- weighted supplier performance scorecard
- supplier tier
- performance-adjusted cost

## Core economics
The engine continues to calculate:
- Current Spend / Service TCO
- New Spend / Supplier proposal TCO
- Gross financial cost
- Treasury / working-capital return offset
- Inventory carrying cost when applicable
- Economic all-in impact
- Brazil + LATAM total result
- Share allocation and cost optimization

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```
