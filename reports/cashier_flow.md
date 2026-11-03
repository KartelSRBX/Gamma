# cashier_flow: INVALID, DO NOT READ

> A one-page cashier instead of three steps raises 7-day deposit conversion.

Owner: payments. Layer `promo`, 50% of its traffic. Enrollment 2026-09-01 to 2026-09-15, each player followed for 7 days after the first exposure. Analysis date 2026-09-22 (planned horizon).

## Decision: INVALID, DO NOT READ

**The data cannot be trusted, so no result is reported as a finding.**

- sample ratio mismatch: control: 49569 (53.31% vs 50.00% planned), treatment: 43419 (46.69% vs 50.00% planned); chi2=406.7, p=1.87e-90
- Estimates are shown below for diagnosis only: `deposit_conversion` changed -0.0% (95% interval -2.0% to +1.9%, p = 0.99)

Next: Find why players are missing or unevenly assigned (logging of the exposure event, bot filters, redirects, a platform that does not support the variant). Fix it and restart the experiment; do not correct the numbers afterwards.

## Is the data trustworthy?

| Check | Result |
| --- | --- |
| Sample ratio (control 49,569, treatment 43,419) | **FAILED**, chi-square p = 1.87e-90 |
| Pre-period balance (Holm-adjusted) | `pre_converted` p = 1.000, `pre_deposit_amount` p = 1.000, `pre_ggr` p = 0.612 · ok |
| Players who saw several variants | 0 excluded |
| Power | 43,419 players per arm; 42,920 needed to see +3% of `deposit_conversion` with 80% power (achieved 80%) |

## Results

Change is relative to control. Intervals are 95%. The primary metric is tested alone at alpha = 0.05; secondary metrics are adjusted together with Holm; guardrails are one-sided non-inferiority tests against the allowed drop.

| Metric | Control | Treatment | Change | 95% interval | p | Method | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Primary** | | | | | | | |
| `deposit_conversion` | 0.295 | 0.295 | -0.0% | -2.0% to +1.9% | 0.986 | CUPED (linear on 0/1) | CUPED removed 3% of the variance |
| **Secondary** | | | | | | | |
| `deposit_per_player` | 49.683 | 50.021 | +0.7% | -4.7% to +6.0% | 0.802 | CUPED | Holm p = 0.802; CUPED removed 34% of the variance; raw bootstrap interval of the difference (no CUPED) [-2.62, +4.04] |
| **Guardrails** | | | | | | | |
| `ggr_per_player` | 2.369 | 2.717 | +14.7% | -38.9% to +68.3% | 0.564 | CUPED | CUPED removed 0% of the variance; guardrail **inconclusive** |

## Where is the effect? (exploratory, `deposit_conversion`)

Segments are leads for the next experiment, not grounds to ship to one of them. Holm adjusts the segments of each dimension together.

| Dimension | Value | Players (control / treatment) | Change | 95% interval | Holm p |
| --- | --- | --- | --- | --- | --- |
| segment | casual | 34,730 / 30,483 | +1.0% | -1.9% to +3.9% | 1.000 |
| segment | regular | 12,387 / 10,817 | -0.8% | -3.9% to +2.2% | 1.000 |
| segment | vip | 2,452 / 2,119 | -0.5% | -4.0% to +2.9% | 1.000 |
| device | android | 22,313 / 22,328 | -0.2% | -3.0% to +2.6% | 0.883 |
| device | ios | 17,334 / 11,284 | -3.4% | -6.9% to +0.1% | 0.126 |
| device | web | 9,922 / 9,807 | +5.0% | +0.6% to +9.5% | 0.070 |
| country | AL | 4,914 / 4,314 | +0.1% | -6.0% to +6.3% | 1.000 |
| country | BA | 7,523 / 6,536 | +2.2% | -2.9% to +7.4% | 1.000 |
| country | HR | 7,385 / 6,397 | +1.9% | -3.2% to +7.1% | 1.000 |
| country | ME | 3,535 / 3,064 | +1.6% | -5.8% to +8.9% | 1.000 |
| country | MK | 3,516 / 3,052 | -6.7% | -13.6% to +0.1% | 0.434 |
| country | RS | 19,782 / 17,428 | -0.8% | -3.9% to +2.3% | 1.000 |
| country | SI | 2,914 / 2,628 | +0.9% | -7.3% to +9.1% | 1.000 |

## Warnings

- sample ratio mismatch: control: 49569 (53.31% vs 50.00% planned), treatment: 43419 (46.69% vs 50.00% planned); chi2=406.7, p=1.87e-90

## Metric definitions

- `deposit_conversion`: Share of players who deposited within the window after exposure
- `deposit_per_player`: Deposited amount per exposed player in the window (heavy right tail)
- `ggr_per_player`: Gross gaming revenue (stake minus payout) per exposed player in the window
