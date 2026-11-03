# welcome_bonus: SHIP

> Raising the first-deposit bonus cap from 50 to 100 EUR makes more players deposit within 7 days of seeing the offer, without lowering revenue per player.

Owner: growth. Layer `promo`, 50% of its traffic. Enrollment 2026-09-01 to 2026-09-15, each player followed for 7 days after the first exposure. Analysis date 2026-09-22 (planned horizon).

## Decision: SHIP

**Ship: the primary metric moved the right way and every guardrail is safe.**

- `deposit_conversion` changed +4.0% (95% interval +2.1% to +6.0%, p = 3.7e-05)
- guardrail `stake_per_player`: ok (change +3.7%, interval +2.6% to +4.9%)
- The lower end of the interval (+2.1%) is below the 3% the test was planned to detect: the effect is real but may be smaller than hoped.

Next: Roll out gradually and watch the guardrails; keep a small holdout to confirm the effect.

## Is the data trustworthy?

| Check | Result |
| --- | --- |
| Sample ratio (control 48,937, treatment 49,309) | ok, chi-square p = 0.235 |
| Pre-period balance (Holm-adjusted) | `pre_converted` p = 0.134, `pre_deposit_amount` p = 0.629, `pre_bets` p = 0.007, `pre_ggr` p = 0.629, `pre_stake` p = 0.015 · ok |
| Players who saw several variants | 0 excluded |
| Power | 48,937 players per arm; 41,950 needed to see +3% of `deposit_conversion` with 80% power (achieved 86%) |

## Results

Change is relative to control. Intervals are 95%. The primary metric is tested alone at alpha = 0.05; secondary metrics are adjusted together with Holm; guardrails are one-sided non-inferiority tests against the allowed drop.

| Metric | Control | Treatment | Change | 95% interval | p | Method | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Primary** | | | | | | | |
| `deposit_conversion` | 0.293 | 0.305 | +4.0% | +2.1% to +6.0% | 3.7e-05 | CUPED (linear on 0/1) | CUPED removed 3% of the variance |
| **Secondary** | | | | | | | |
| `deposit_per_player` | 49.086 | 51.625 | +5.2% | -0.2% to +10.5% | 0.052 | CUPED | Holm p = 0.104; CUPED removed 33% of the variance; raw bootstrap interval of the difference (no CUPED) [-1.45, +4.87] |
| `bets_per_player` | 6.524 | 6.689 | +2.5% | +1.8% to +3.2% | 9.9e-13 | CUPED | Holm p = 3e-12; CUPED removed 93% of the variance; raw bootstrap interval of the difference (no CUPED) [-0.27, +0.07] |
| `ggr_per_player` | 2.874 | 2.932 | +2.0% | -37.8% to +41.8% | 0.921 | CUPED | Holm p = 0.921; CUPED removed 0% of the variance; raw bootstrap interval of the difference (no CUPED) [-1.08, +1.09] |
| **Guardrails** | | | | | | | |
| `stake_per_player` | 64.587 | 67.005 | +3.7% | +2.6% to +4.9% | 1.6e-10 | CUPED | CUPED removed 96% of the variance; guardrail **ok** |

## Where is the effect? (exploratory, `deposit_conversion`)

Segments are leads for the next experiment, not grounds to ship to one of them. Holm adjusts the segments of each dimension together.

| Dimension | Value | Players (control / treatment) | Change | 95% interval | Holm p |
| --- | --- | --- | --- | --- | --- |
| segment | casual | 34,051 / 34,358 | +4.5% | +1.6% to +7.5% | 0.005 |
| segment | regular | 12,344 / 12,535 | +4.2% | +1.2% to +7.1% | 0.010 |
| segment | vip | 2,542 / 2,416 | +2.9% | -0.6% to +6.3% | 0.096 |
| device | android | 22,130 / 22,072 | +4.2% | +1.3% to +7.1% | 0.013 |
| device | ios | 16,988 / 17,387 | +4.2% | +0.9% to +7.5% | 0.021 |
| device | web | 9,819 / 9,850 | +3.4% | -1.0% to +7.7% | 0.126 |
| country | AL | 4,811 / 4,849 | +4.6% | -1.6% to +10.9% | 0.535 |
| country | BA | 7,405 / 7,294 | +5.6% | +0.5% to +10.7% | 0.167 |
| country | HR | 7,200 / 7,538 | +5.0% | +0.0% to +10.1% | 0.219 |
| country | ME | 3,395 / 3,513 | -2.1% | -9.0% to +4.8% | 1.000 |
| country | MK | 3,492 / 3,403 | -2.1% | -9.2% to +5.1% | 1.000 |
| country | RS | 19,629 / 19,808 | +5.3% | +2.2% to +8.5% | 0.004 |
| country | SI | 3,005 / 2,904 | +2.2% | -5.7% to +10.1% | 1.000 |

## Metric definitions

- `deposit_conversion`: Share of players who deposited within the window after exposure
- `deposit_per_player`: Deposited amount per exposed player in the window (heavy right tail)
- `bets_per_player`: Bets placed per exposed player in the window
- `ggr_per_player`: Gross gaming revenue (stake minus payout) per exposed player in the window
- `stake_per_player`: Turnover (sum of stakes) per exposed player in the window
