"""Mortgage and purchase-cost simulation (French amortisation).

Everything here is an *estimate*. Tax rates and bank rules live in config/needs.yaml
(`costs:` and `mortgage:`) so they can be corrected without touching code. Defaults are
the Comunidad de Madrid general rates; check them before relying on a number.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostRates:
    itp: float = 0.06          # transmisiones patrimoniales (second-hand), Comunidad de Madrid general rate
    ajd: float = 0.0075        # actos jurídicos documentados
    iva_new: float = 0.10      # IVA on new-build housing
    other_pct: float = 0.012   # notary + registry + gestoría + appraisal, rough % of price
    max_ltv: float = 0.80      # typical maximum financing vs price


def monthly_payment(principal: float, annual_rate_pct: float, years: int) -> float:
    n = int(years * 12)
    if n <= 0:
        raise ValueError("years must be > 0")
    if principal <= 0:
        return 0.0
    r = annual_rate_pct / 100.0 / 12.0
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


def purchase_costs(price: float, new_build: bool, rates: CostRates) -> dict:
    taxes = price * ((rates.iva_new + rates.ajd) if new_build else rates.itp)
    other = price * rates.other_pct
    return {"taxes": taxes, "other": other, "total": taxes + other}


def simulate(
    price: float,
    savings: float,
    years: int,
    tin_pct: float,
    net_income_monthly: float | None = None,
    new_build: bool = False,
    rates: CostRates | None = None,
    stress_steps_pp: tuple[float, ...] = (1.0, 2.0),
) -> dict:
    """Savings pay taxes and costs first; whatever is left is the down payment."""
    rates = rates or CostRates()
    c = purchase_costs(price, new_build, rates)
    down_payment = max(0.0, savings - c["total"])
    loan = max(0.0, price - down_payment)
    ltv = loan / price if price else 0.0
    min_savings = price * (1 - rates.max_ltv) + c["total"]
    shortfall = max(0.0, min_savings - savings)

    pay = monthly_payment(loan, tin_pct, years)
    out = {
        "price": price,
        "taxes": c["taxes"],
        "other_costs": c["other"],
        "upfront_total": c["total"] + down_payment,
        "loan": loan,
        "ltv": ltv,
        "monthly": pay,
        "total_interest": pay * years * 12 - loan,
        "min_savings_needed": min_savings,
        "savings_shortfall": shortfall,
        "effort_ratio": None,
        "stress": [],
    }
    for step in stress_steps_pp:
        p = monthly_payment(loan, tin_pct + step, years)
        s = {"tin_pct": tin_pct + step, "monthly": p, "effort_ratio": None}
        if net_income_monthly:
            s["effort_ratio"] = p / net_income_monthly
        out["stress"].append(s)
    if net_income_monthly:
        out["effort_ratio"] = pay / net_income_monthly
    return out


def effort_ratio(monthly_housing_cost: float, net_income_monthly: float) -> float:
    """Same quantity the Notariado 'tasa de esfuerzo' tool reports: housing cost / net income."""
    return monthly_housing_cost / net_income_monthly
