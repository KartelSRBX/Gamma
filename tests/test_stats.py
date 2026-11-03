from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from gamma.config import Metric
from gamma.stats import design, estimators, multiple, quality, sequential, validate

RNG = np.random.default_rng(7)


def sample(n=4000, effect=0.0):
    c = RNG.lognormal(1.0, 1.0, n)
    t = RNG.lognormal(1.0, 1.0, n) * (1 + effect)
    return c, t


# --- estimators agree with the textbook ------------------------------------------------------


def test_welch_matches_scipy():
    c, t = sample(3000, 0.05)
    est = estimators.welch_test(c, t)
    ref = stats.ttest_ind(t, c, equal_var=False)
    assert est.p == pytest.approx(ref.pvalue, rel=1e-9)
    ci = ref.confidence_interval(0.95)
    assert est.ci == pytest.approx((ci.low, ci.high), rel=1e-9)
    assert est.diff == pytest.approx(t.mean() - c.mean())


def test_binary_test_matches_chi_square_without_correction():
    c = (RNG.random(5000) < 0.30).astype(float)
    t = (RNG.random(5200) < 0.33).astype(float)
    table = [[t.sum(), len(t) - t.sum()], [c.sum(), len(c) - c.sum()]]
    ref = stats.chi2_contingency(table, correction=False)
    assert estimators.binary_test(c, t).p == pytest.approx(ref[1], rel=1e-9)


def test_ratio_test_with_unit_denominator_is_the_mean_difference():
    c, t = sample(3000, 0.05)
    ones_c, ones_t = np.ones_like(c), np.ones_like(t)
    ratio = estimators.ratio_test(c, ones_c, t, ones_t)
    welch = estimators.welch_test(c, t)
    assert ratio.diff == pytest.approx(welch.diff)
    assert ratio.se == pytest.approx(welch.se, rel=1e-3)


def test_ratio_standard_error_matches_a_bootstrap_of_players():
    n = 4000
    den = RNG.poisson(5, n) + 1.0
    num = den * RNG.beta(2, 5, n) + RNG.normal(0, 1, n)
    idx = np.arange(n)
    boot = []
    for _ in range(1500):
        s = RNG.choice(idx, n)
        boot.append(num[s].sum() / den[s].sum())
    r, var = estimators._ratio_arm(num, den)
    assert r == pytest.approx(num.sum() / den.sum())
    assert np.sqrt(var) == pytest.approx(np.std(boot), rel=0.08)


def test_cuped_keeps_the_effect_and_shrinks_the_noise():
    n = 20000
    base = RNG.lognormal(1.0, 1.0, 2 * n)
    pre = base * RNG.lognormal(0, 0.3, 2 * n)
    post = base * RNG.lognormal(0, 0.3, 2 * n)
    y_c, y_t = post[:n], post[n:] * 1.05
    x_c, x_t = pre[:n], pre[n:]
    raw = estimators.welch_test(y_c, y_t)
    cup = estimators.cuped_test("continuous", y_c, x_c, y_t, x_t)
    truth = 0.05 * post.mean()
    assert abs(cup.diff - truth) < 4 * cup.se  # unbiased: the effect survives the adjustment
    assert cup.se < 0.6 * raw.se
    assert cup.variance_reduction and cup.variance_reduction > 0.5
    # theta is the regression slope
    assert cup.theta == pytest.approx(
        np.cov(np.r_[x_c, x_t], np.r_[y_c, y_t])[0, 1] / np.r_[x_c, x_t].var(ddof=1)
    )


def test_cuped_is_invariant_to_shifting_the_covariate():
    n = 5000
    x = RNG.normal(10, 2, 2 * n)
    y = x + RNG.normal(0, 1, 2 * n)
    a = estimators.cuped_test("continuous", y[:n], x[:n], y[n:], x[n:])
    b = estimators.cuped_test("continuous", y[:n], x[:n] + 100, y[n:], x[n:] + 100)
    assert a.diff == pytest.approx(b.diff)
    assert a.p == pytest.approx(b.p)


def test_cuped_without_signal_in_the_covariate_changes_nothing_much():
    n = 5000
    y = RNG.normal(0, 1, 2 * n)
    x = RNG.normal(0, 1, 2 * n)
    cup = estimators.cuped_test("continuous", y[:n], x[:n], y[n:], x[n:])
    assert cup.variance_reduction < 0.01


def test_relative_interval_contains_the_relative_estimate():
    c, t = sample(3000, 0.1)
    est = estimators.welch_test(c, t)
    assert est.rel_ci[0] < est.rel_diff < est.rel_ci[1]


def test_bootstrap_interval_is_close_to_welch_on_a_large_sample():
    c, t = sample(5000, 0.1)
    lo, hi = estimators.bootstrap_diff_ci(c, t, resamples=1500)
    welch = estimators.welch_test(c, t)
    assert lo == pytest.approx(welch.ci[0], abs=0.15 * welch.se * 3)
    assert hi == pytest.approx(welch.ci[1], abs=0.15 * welch.se * 3)


# --- design ------------------------------------------------------------------------------------


def test_sample_size_matches_published_values():
    # 10% baseline, +10% relative, 80% power, alpha 5%: the classic ~14,750 per arm
    assert design.sample_size_binary(0.10, 0.10) == pytest.approx(14_750, abs=60)
    # sd = mean: n = 2 (1.96 + 0.84)^2 / mde^2
    assert design.sample_size_mean(1.0, 1.0, 0.1) == pytest.approx(1570, abs=5)


def test_power_is_80_percent_at_the_prescribed_size():
    n = design.sample_size_binary(0.2, 0.05)
    assert design.power_binary(0.2, 0.05, n) == pytest.approx(0.8, abs=0.005)
    n = design.sample_size_mean(5.0, 20.0, 0.05)
    assert design.power_mean(5.0, 20.0, 0.05, n) == pytest.approx(0.8, abs=0.005)


def test_variance_reduction_cuts_the_sample_size_by_the_same_share():
    full = design.sample_size_mean(1.0, 3.0, 0.1)
    assert design.sample_size_mean(1.0, 3.0, 0.1, variance_reduction=0.5) == pytest.approx(
        full / 2, abs=2
    )


def test_impossible_rate_is_refused():
    with pytest.raises(ValueError, match="leaves"):
        design.sample_size_binary(0.6, 0.9)


# --- quality and multiplicity ---------------------------------------------------------------


def test_srm_fires_on_a_missing_share_and_not_on_noise():
    assert quality.srm_test(
        {"control": 50_000, "treatment": 43_000}, {"control": 1, "treatment": 1}
    ).failed
    assert not quality.srm_test(
        {"control": 50_000, "treatment": 50_210}, {"control": 1, "treatment": 1}
    ).failed


def test_srm_respects_uneven_weights():
    assert not quality.srm_test(
        {"control": 9_000, "treatment": 1_010}, {"control": 90, "treatment": 10}
    ).failed
    assert quality.srm_test(
        {"control": 5_000, "treatment": 5_000}, {"control": 90, "treatment": 10}
    ).failed


def test_holm_known_example():
    # classic example: p = 0.01, 0.04, 0.03, 0.005 -> 0.03, 0.06, 0.06, 0.02
    assert multiple.holm([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.03, 0.06, 0.06, 0.02])


def test_benjamini_hochberg_known_example():
    assert multiple.benjamini_hochberg([0.01, 0.04, 0.03, 0.005]) == pytest.approx(
        [0.02, 0.04, 0.04, 0.02]
    )


def test_adjusted_p_values_never_decrease_and_stay_in_range():
    p = RNG.random(30).tolist()
    for f in (multiple.holm, multiple.benjamini_hochberg):
        adj = np.array(f(p))
        assert (adj >= np.array(p) - 1e-12).all() and (adj <= 1).all()


# --- sequential boundaries ------------------------------------------------------------------


def test_one_look_is_the_fixed_horizon_test():
    assert sequential.boundaries([1.0])[0] == pytest.approx(1.96, abs=0.005)


def test_boundaries_start_high_and_end_near_the_fixed_value():
    z = sequential.boundaries([0.2, 0.4, 0.6, 0.8, 1.0])
    assert z == sorted(z, reverse=True)
    assert z[0] > 4 and 2.0 < z[-1] < 2.15


def test_boundaries_control_the_error_rate_by_brute_force():
    looks = [0.25, 0.5, 0.75, 1.0]
    z = np.array(sequential.boundaries(looks))
    rng = np.random.default_rng(0)
    steps = rng.standard_normal((200_000, 4)) * np.sqrt(np.diff([0, *looks]))
    s = steps.cumsum(axis=1)
    zs = np.abs(s) / np.sqrt(looks)
    rate = (zs > z).any(axis=1).mean()
    assert rate == pytest.approx(0.05, abs=0.003)
    naive = (zs > 1.96).any(axis=1).mean()
    assert naive > 0.10  # the problem the boundaries solve


# --- the method checks themselves, on a small synthetic world ---------------------------------


@pytest.fixture(scope="module")
def world():
    n = 60_000
    activity = RNG.lognormal(0, 0.6, n)
    pre = RNG.poisson(5 * activity).astype(float)
    post = RNG.poisson(5 * activity).astype(float)
    conv = (RNG.random(n) < 1 - np.exp(-0.05 * activity * 5)).astype(float)
    pre_conv = (RNG.random(n) < 1 - np.exp(-0.05 * activity * 5)).astype(float)
    return {"bets": post, "pre_bets": pre, "converted": conv, "pre_converted": pre_conv}


CONT = Metric(
    name="bets_per_player",
    kind="continuous",
    num="bets",
    pre="pre_bets",
    better="higher",
    description="x",
)
BIN = Metric(
    name="deposit_conversion",
    kind="binary",
    num="converted",
    pre="pre_converted",
    better="higher",
    description="x",
)


def test_a_a_false_positive_rate_is_near_nominal(world):
    res = validate.false_positive_rates(world, [CONT, BIN], n=3000, trials=500)
    for methods in res.values():
        for rate in methods.values():
            assert 0.02 < rate.value < 0.085, rate


def test_planted_lift_is_found_at_the_planned_power_and_covered(world):
    row = validate.power_and_coverage(world, BIN, 0.10, trials=300)
    assert 0.70 < row.raw.value < 0.90
    assert row.coverage.value > 0.90


def test_cuped_finds_more_than_raw_when_the_pre_period_is_informative(world):
    row = validate.power_and_coverage(world, CONT, 0.03, trials=200)
    assert row.cuped.value > row.raw.value
    assert row.variance_ratio < 0.8


def test_peeking_inflates_errors_and_the_plan_repairs_them(world):
    res = validate.peeking(world, BIN, n=5000, looks=5, trials=600)
    assert res.naive.value > 0.09
    assert res.sequential.value < 0.075
    assert res.fixed.value < 0.075


def test_srm_check_rates():
    false_alarm, hit = validate.srm_rates(20_000, 3000, drop=0.08)
    assert false_alarm.value < 0.005
    assert hit.value > 0.99
