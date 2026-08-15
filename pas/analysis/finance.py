"""Deterministic unit economics and pricing simulation (spec 15).

Every number here is computed in Python from explicit inputs. The model supplies
*estimates* of the inputs (ARPU, churn, CAC, elasticity) and must say where they
came from; it never produces the derived figures. That separation is what makes
these projections reproducible and auditable rather than plausible-looking
invention.

The elasticity model matters: raising price does not keep customer count
constant. A constant-elasticity demand curve is used, so revenue can fall when
price rises - which is the whole point of running the simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class Economics:
    """Input assumptions for a pricing scenario."""

    arpu_monthly: float
    gross_margin_pct: float
    cac: float
    monthly_churn_pct: float
    monthly_expansion_pct: float = 0.0
    customers: int = 100

    def normalised(self) -> "Economics":
        """Coerce inputs into defensible ranges.

        Model-estimated inputs occasionally arrive as percentages above 100 or
        negative churn; clamping here keeps a bad estimate from producing an
        infinite LTV downstream.
        """
        return Economics(
            arpu_monthly=max(0.0, self.arpu_monthly),
            gross_margin_pct=_clamp(self.gross_margin_pct, 0.0, 100.0),
            cac=max(0.0, self.cac),
            monthly_churn_pct=_clamp(self.monthly_churn_pct, 0.0, 100.0),
            monthly_expansion_pct=_clamp(self.monthly_expansion_pct, 0.0, 100.0),
            customers=max(0, int(self.customers)),
        )


@dataclass
class UnitEconomics:
    """Derived per-customer economics."""

    arpu_monthly: float
    gross_margin_pct: float
    contribution_monthly: float
    net_churn_pct: float
    avg_lifetime_months: float | None
    ltv: float | None
    cac: float
    ltv_cac_ratio: float | None
    cac_payback_months: float | None
    mrr: float
    arr: float
    warnings: list[str] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        """The conventional SaaS bar: LTV:CAC >= 3 and payback <= 12 months."""
        return (
            self.ltv_cac_ratio is not None
            and self.ltv_cac_ratio >= 3.0
            and self.cac_payback_months is not None
            and self.cac_payback_months <= 12.0
        )


def unit_economics(economics: Economics) -> UnitEconomics:
    """Compute LTV, LTV:CAC and payback from assumptions."""
    inputs = economics.normalised()
    warnings: list[str] = []

    margin = inputs.gross_margin_pct / 100.0
    contribution = inputs.arpu_monthly * margin

    # Net revenue churn: expansion from existing accounts offsets logo churn.
    net_churn_pct = inputs.monthly_churn_pct - inputs.monthly_expansion_pct

    lifetime: float | None
    ltv: float | None
    if net_churn_pct <= 0:
        # Negative net churn implies infinite lifetime, which is not a usable
        # planning number. Cap at 10 years and say so.
        lifetime = 120.0
        ltv = contribution * lifetime
        warnings.append(
            "Expansion meets or exceeds churn, implying unbounded lifetime value. "
            "Capped at 120 months for planning."
        )
    else:
        lifetime = 100.0 / net_churn_pct
        ltv = contribution * lifetime

    if inputs.monthly_churn_pct == 0:
        warnings.append("Zero churn assumed. Verify this against real retention data.")

    ratio = (ltv / inputs.cac) if (ltv is not None and inputs.cac > 0) else None
    payback = (inputs.cac / contribution) if contribution > 0 else None

    if payback is None:
        warnings.append("Contribution margin is zero, so CAC can never be recovered.")

    mrr = inputs.arpu_monthly * inputs.customers
    return UnitEconomics(
        arpu_monthly=inputs.arpu_monthly,
        gross_margin_pct=inputs.gross_margin_pct,
        contribution_monthly=contribution,
        net_churn_pct=net_churn_pct,
        avg_lifetime_months=lifetime,
        ltv=ltv,
        cac=inputs.cac,
        ltv_cac_ratio=ratio,
        cac_payback_months=payback,
        mrr=mrr,
        arr=mrr * 12,
        warnings=warnings,
    )


@dataclass
class PriceScenario:
    """The outcome of moving price by a given percentage."""

    price_change_pct: float
    new_arpu: float
    demand_multiplier: float
    new_customers: float
    new_mrr: float
    new_arr: float
    mrr_change_pct: float
    economics: UnitEconomics


def simulate_price_change(
    economics: Economics,
    price_change_pct: float,
    elasticity: float = -1.0,
) -> PriceScenario:
    """Model a price change with a constant-elasticity demand curve.

    Q1/Q0 = (P1/P0) ** elasticity

    With elasticity below -1 demand is elastic, so a price rise *reduces*
    revenue. Assuming customer count holds constant - which the spec explicitly
    forbids - would hide exactly that outcome.
    """
    inputs = economics.normalised()
    # Elasticity must be negative; a positive value would mean raising price
    # increases demand, which is not a curve worth planning against.
    elasticity = min(-0.01, float(elasticity))

    price_ratio = max(0.01, 1.0 + price_change_pct / 100.0)
    demand_multiplier = price_ratio**elasticity

    new_arpu = inputs.arpu_monthly * price_ratio
    new_customers = inputs.customers * demand_multiplier

    scenario_inputs = Economics(
        arpu_monthly=new_arpu,
        gross_margin_pct=inputs.gross_margin_pct,
        cac=inputs.cac,
        monthly_churn_pct=inputs.monthly_churn_pct,
        monthly_expansion_pct=inputs.monthly_expansion_pct,
        customers=int(round(new_customers)),
    )
    derived = unit_economics(scenario_inputs)

    baseline_mrr = inputs.arpu_monthly * inputs.customers
    new_mrr = new_arpu * new_customers
    change_pct = ((new_mrr / baseline_mrr - 1) * 100) if baseline_mrr > 0 else 0.0

    return PriceScenario(
        price_change_pct=price_change_pct,
        new_arpu=new_arpu,
        demand_multiplier=demand_multiplier,
        new_customers=new_customers,
        new_mrr=new_mrr,
        new_arr=new_mrr * 12,
        mrr_change_pct=change_pct,
        economics=derived,
    )


def price_sensitivity_curve(
    economics: Economics,
    elasticity: float = -1.0,
    changes: tuple[float, ...] = (-30, -20, -10, 0, 10, 20, 30, 50),
) -> list[PriceScenario]:
    """Run a spread of price changes to expose the revenue-maximising point."""
    return [simulate_price_change(economics, change, elasticity) for change in changes]


def revenue_maximising_change(scenarios: list[PriceScenario]) -> PriceScenario | None:
    return max(scenarios, key=lambda s: s.new_mrr, default=None)


@dataclass
class BreakEven:
    monthly_fixed_costs: float
    contribution_per_customer: float
    customers_needed: float | None
    mrr_needed: float | None
    months_to_break_even: float | None
    reachable: bool


def break_even(
    economics: Economics,
    monthly_fixed_costs: float,
    net_new_customers_per_month: float = 0.0,
) -> BreakEven:
    """Customers required to cover fixed costs, and how long that takes."""
    inputs = economics.normalised()
    contribution = inputs.arpu_monthly * (inputs.gross_margin_pct / 100.0)

    if contribution <= 0:
        return BreakEven(monthly_fixed_costs, contribution, None, None, None, False)

    needed = monthly_fixed_costs / contribution
    remaining = max(0.0, needed - inputs.customers)
    months = (
        (remaining / net_new_customers_per_month)
        if net_new_customers_per_month > 0
        else None
    )
    if remaining == 0:
        months = 0.0

    return BreakEven(
        monthly_fixed_costs=monthly_fixed_costs,
        contribution_per_customer=contribution,
        customers_needed=needed,
        mrr_needed=needed * inputs.arpu_monthly,
        months_to_break_even=months,
        reachable=months is not None,
    )


@dataclass
class ProjectionMonth:
    month: int
    customers: float
    mrr: float
    cumulative_revenue: float
    cumulative_cac_spend: float
    cumulative_profit: float


def project(
    economics: Economics,
    months: int = 24,
    new_customers_per_month: float = 0.0,
    monthly_fixed_costs: float = 0.0,
) -> list[ProjectionMonth]:
    """Month-by-month projection with churn compounding against acquisition."""
    inputs = economics.normalised()
    margin = inputs.gross_margin_pct / 100.0
    churn = inputs.monthly_churn_pct / 100.0
    expansion = inputs.monthly_expansion_pct / 100.0

    customers = float(inputs.customers)
    arpu = inputs.arpu_monthly
    cumulative_revenue = 0.0
    cumulative_cac = 0.0
    rows: list[ProjectionMonth] = []

    for month in range(1, max(1, months) + 1):
        churned = customers * churn
        customers = max(0.0, customers - churned + new_customers_per_month)
        # Expansion lifts revenue per retained account rather than headcount.
        arpu *= 1 + expansion

        mrr = customers * arpu
        cumulative_revenue += mrr * margin
        cumulative_cac += new_customers_per_month * inputs.cac

        rows.append(
            ProjectionMonth(
                month=month,
                customers=customers,
                mrr=mrr,
                cumulative_revenue=cumulative_revenue,
                cumulative_cac_spend=cumulative_cac,
                cumulative_profit=cumulative_revenue
                - cumulative_cac
                - monthly_fixed_costs * month,
            )
        )
    return rows
