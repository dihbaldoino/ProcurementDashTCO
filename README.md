# Executive Procurement TCO Dashboard — v25 FINAL

This version fixes the finance view by explicitly offsetting gross payment-term financial cost with Treasury Return / Working Capital Carry.

## Core decision logic

### Gross financial cost

Current:

```text
Current Financial Cost = Current Spend × equivalent financial rate for current payment term
```

Proposal:

```text
New Financial Cost = Σ(100% volume-equivalent supplier spend × supplier share × equivalent financial rate for supplier payment term)
```

### Treasury return offset

Current:

```text
Current Treasury Return = Current Spend × equivalent treasury return for current payment term
```

Proposal:

```text
New Treasury Return = Σ(100% volume-equivalent supplier spend × supplier share × equivalent treasury return for supplier payment term)
```

### Net financial saving / impact

```text
Gross Financial Delta = New Financial Cost - Current Financial Cost
Treasury Return Offset = Current Treasury Return - New Treasury Return
Net Financial Delta = Gross Financial Delta + Treasury Return Offset
```

Negative delta = saving / favorable.
Positive delta = impact / unfavorable.

This means a longer payment term can increase gross supplier financing cost, but still be economically favorable once the additional Treasury Return is considered.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Requirements

```text
streamlit>=1.30
pandas>=2.0
plotly>=5.18
scipy>=1.11
```
