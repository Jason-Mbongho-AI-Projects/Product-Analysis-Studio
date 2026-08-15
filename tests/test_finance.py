"""Financial model tests (spec 15).

These assert real economics, not just that functions return numbers. The
elasticity behaviour in particular is the requirement that price changes must
not assume constant customer count.
"""

from __future__ import annotations

import pytest

from pas.analysis.finance import (
    Economics,
    break_even,
    price_sensitivity_curve,
    project,
    revenue_maximising_change,
    simulate_price_change,
    unit_economics,
)

BASE = Economics(
    arpu_monthly=100.0,
    gross_margin_pct=80.0,
    cac=600.0,
    monthly_churn_pct=5.0,
    monthly_expansion_pct=0.0,
    customers=100,
)


def test_ltv_and_payback_are_correct_arithmetic():
    result = unit_economics(BASE)
    # contribution = 100 * 0.8 = 80; lifetime = 100/5 = 20 months
    assert result.contribution_monthly == pytest.approx(80.0)
    assert result.avg_lifetime_months == pytest.approx(20.0)
    assert result.ltv == pytest.approx(1600.0)
    assert result.ltv_cac_ratio == pytest.approx(1600.0 / 600.0)
    assert result.cac_payback_months == pytest.approx(7.5)
    assert result.mrr == pytest.approx(10_000.0)
    assert result.arr == pytest.approx(120_000.0)


def test_health_threshold_reflects_conventional_bar():
    weak = unit_economics(BASE)
    assert weak.ltv_cac_ratio < 3.0
    assert weak.is_healthy is False

    strong = unit_economics(
        Economics(arpu_monthly=100, gross_margin_pct=80, cac=300,
                  monthly_churn_pct=2, customers=100)
    )
    assert strong.ltv_cac_ratio >= 3.0
    assert strong.is_healthy is True


def test_expansion_offsetting_churn_is_capped_not_infinite():
    result = unit_economics(
        Economics(arpu_monthly=100, gross_margin_pct=80, cac=500,
                  monthly_churn_pct=3, monthly_expansion_pct=5)
    )
    assert result.avg_lifetime_months == 120.0
    assert result.ltv is not None and result.ltv < float("inf")
    assert any("unbounded" in w.lower() for w in result.warnings)


def test_zero_churn_is_flagged():
    result = unit_economics(
        Economics(arpu_monthly=50, gross_margin_pct=70, cac=100, monthly_churn_pct=0)
    )
    assert any("zero churn" in w.lower() for w in result.warnings)


def test_inputs_are_clamped_to_defensible_ranges():
    result = unit_economics(
        Economics(arpu_monthly=-10, gross_margin_pct=250, cac=-5, monthly_churn_pct=-3)
    )
    assert result.arpu_monthly == 0.0
    assert result.gross_margin_pct == 100.0
    assert result.cac == 0.0


# ---------------------------------------------------------------------------
# Elasticity - the core spec 15 requirement
# ---------------------------------------------------------------------------


def test_price_increase_reduces_customer_count():
    """Customer count must NOT stay constant when price changes."""
    scenario = simulate_price_change(BASE, price_change_pct=20, elasticity=-1.2)
    assert scenario.new_arpu == pytest.approx(120.0)
    assert scenario.new_customers < BASE.customers, "demand must fall as price rises"


def test_price_cut_increases_customer_count():
    scenario = simulate_price_change(BASE, price_change_pct=-20, elasticity=-1.2)
    assert scenario.new_arpu == pytest.approx(80.0)
    assert scenario.new_customers > BASE.customers


def test_elastic_demand_makes_price_rises_lose_revenue():
    """With elasticity < -1, raising price must reduce MRR."""
    elastic = simulate_price_change(BASE, price_change_pct=25, elasticity=-2.0)
    assert elastic.mrr_change_pct < 0, "elastic demand should lose revenue on a price rise"


def test_inelastic_demand_makes_price_rises_gain_revenue():
    """With elasticity > -1, raising price must increase MRR."""
    inelastic = simulate_price_change(BASE, price_change_pct=25, elasticity=-0.5)
    assert inelastic.mrr_change_pct > 0


def test_unit_elasticity_leaves_revenue_flat():
    scenario = simulate_price_change(BASE, price_change_pct=30, elasticity=-1.0)
    assert scenario.mrr_change_pct == pytest.approx(0.0, abs=0.01)


def test_zero_change_is_a_no_op():
    scenario = simulate_price_change(BASE, price_change_pct=0, elasticity=-1.5)
    assert scenario.new_arpu == pytest.approx(BASE.arpu_monthly)
    assert scenario.new_customers == pytest.approx(BASE.customers)
    assert scenario.mrr_change_pct == pytest.approx(0.0)


def test_positive_elasticity_is_rejected():
    """A positive elasticity would mean demand rises with price."""
    scenario = simulate_price_change(BASE, price_change_pct=20, elasticity=1.5)
    assert scenario.new_customers < BASE.customers


def test_sensitivity_curve_finds_the_revenue_peak():
    curve = price_sensitivity_curve(BASE, elasticity=-0.5)
    best = revenue_maximising_change(curve)
    assert best is not None
    # Inelastic demand: the highest tested price maximises revenue.
    assert best.price_change_pct == max(s.price_change_pct for s in curve)

    curve = price_sensitivity_curve(BASE, elasticity=-2.5)
    best = revenue_maximising_change(curve)
    # Elastic demand: the lowest tested price maximises revenue.
    assert best.price_change_pct == min(s.price_change_pct for s in curve)


# ---------------------------------------------------------------------------
# Break-even and projection
# ---------------------------------------------------------------------------


def test_break_even_customer_count():
    result = break_even(BASE, monthly_fixed_costs=40_000, net_new_customers_per_month=50)
    assert result.customers_needed == pytest.approx(500.0)  # 40000 / 80
    assert result.months_to_break_even == pytest.approx(8.0)  # (500-100)/50
    assert result.reachable is True


def test_break_even_already_reached():
    result = break_even(
        Economics(arpu_monthly=100, gross_margin_pct=80, cac=500,
                  monthly_churn_pct=5, customers=1000),
        monthly_fixed_costs=40_000,
    )
    assert result.months_to_break_even == 0.0


def test_break_even_unreachable_without_growth():
    result = break_even(BASE, monthly_fixed_costs=40_000, net_new_customers_per_month=0)
    assert result.reachable is False
    assert result.months_to_break_even is None


def test_break_even_impossible_at_zero_margin():
    result = break_even(
        Economics(arpu_monthly=100, gross_margin_pct=0, cac=500, monthly_churn_pct=5),
        monthly_fixed_costs=1000,
    )
    assert result.customers_needed is None
    assert result.reachable is False


def test_projection_churn_shrinks_base_without_acquisition():
    rows = project(BASE, months=12, new_customers_per_month=0)
    assert len(rows) == 12
    assert rows[-1].customers < BASE.customers
    assert rows[0].customers > rows[-1].customers


def test_projection_growth_outpaces_churn():
    rows = project(BASE, months=12, new_customers_per_month=20)
    assert rows[-1].customers > BASE.customers


def test_projection_accounts_for_cac_and_fixed_costs():
    rows = project(BASE, months=6, new_customers_per_month=10, monthly_fixed_costs=5000)
    last = rows[-1]
    assert last.cumulative_cac_spend == pytest.approx(6 * 10 * BASE.cac)
    assert last.cumulative_profit < last.cumulative_revenue
