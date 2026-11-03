# lobby_layout: NO EFFECT, STOP

> A game lobby sorted by personal history instead of popularity increases the number of bets per player.

Owner: product. Layer `lobby`, 100% of its traffic. Enrollment 2026-09-01 to 2026-09-15, each player followed for 7 days after the first exposure. Analysis date 2026-09-22 (planned horizon).

## Decision: NO EFFECT, STOP

**No effect worth shipping.**

- `bets_per_player` changed +0.2% (95% interval -0.3% to +0.6%, p = 0.53)
- 763 players saw several variants and were excluded (a randomisation bug worth fixing, small enough not to change the conclusion).
- guardrail `avg_stake`: ok (change -0.9%, interval -3.3% to +1.4%)
- The interval rules out an improvement of 3% or more: at most +0.6%.

Next: Stop the experiment and record the result: a clear null is information.

## Is the data trustworthy?

| Check | Result |
| --- | --- |
| Sample ratio (control 98,255, treatment 98,215) | ok, chi-square p = 0.928 |
| Pre-period balance (Holm-adjusted) | `pre_bets` p = 0.827, `pre_ggr` p = 0.636 · ok |
| Players who saw several variants | 763 excluded |
| Power | 98,215 players per arm; 74,493 needed to see +3% of `bets_per_player` with 80% power (achieved 90%) |

## Results

Change is relative to control. Intervals are 95%. The primary metric is tested alone at alpha = 0.05; secondary metrics are adjusted together with Holm; guardrails are one-sided non-inferiority tests against the allowed drop.

| Metric | Control | Treatment | Change | 95% interval | p | Method | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Primary** | | | | | | | |
| `bets_per_player` | 6.554 | 6.564 | +0.2% | -0.3% to +0.6% | 0.527 | CUPED | CUPED removed 93% of the variance; raw bootstrap interval of the difference (no CUPED) [-0.12, +0.11] |
| **Secondary** | | | | | | | |
| `ggr_per_player` | 2.614 | 2.997 | +14.7% | -18.8% to +48.1% | 0.354 | CUPED | Holm p = 0.606; CUPED removed 0% of the variance; raw bootstrap interval of the difference (no CUPED) [-0.34, +1.19] |
| `margin` | 0.040 | 0.046 | +16.3% | -17.5% to +50.0% | 0.303 | delta method | Holm p = 0.606 |
| **Guardrails** | | | | | | | |
| `avg_stake` | 10.007 | 9.915 | -0.9% | -3.3% to +1.4% | 0.442 | delta method | guardrail **ok** |

## Where is the effect? (exploratory, `bets_per_player`)

Segments are leads for the next experiment, not grounds to ship to one of them. Holm adjusts the segments of each dimension together.

| Dimension | Value | Players (control / treatment) | Change | 95% interval | Holm p |
| --- | --- | --- | --- | --- | --- |
| segment | casual | 68,681 / 68,626 | +0.2% | -0.7% to +1.1% | 1.000 |
| segment | regular | 24,670 / 24,705 | +0.3% | -0.5% to +1.0% | 1.000 |
| segment | vip | 4,904 / 4,884 | +0.1% | -0.7% to +0.9% | 1.000 |
| device | android | 44,436 / 44,028 | +0.5% | -0.2% to +1.2% | 0.186 |
| device | ios | 34,317 / 34,412 | -0.8% | -1.6% to +0.0% | 0.169 |
| device | web | 19,502 / 19,775 | +1.1% | -0.0% to +2.2% | 0.169 |
| country | AL | 9,651 / 9,774 | +1.2% | -0.4% to +2.7% | 0.836 |
| country | BA | 14,785 / 14,772 | -1.2% | -2.5% to +0.0% | 0.366 |
| country | HR | 14,602 / 14,670 | +0.9% | -0.3% to +2.2% | 0.836 |
| country | ME | 7,030 / 6,832 | +1.2% | -0.7% to +3.1% | 0.870 |
| country | MK | 6,854 / 6,962 | -0.0% | -1.8% to +1.8% | 1.000 |
| country | RS | 39,499 / 39,303 | +0.0% | -0.7% to +0.8% | 1.000 |
| country | SI | 5,834 / 5,902 | -0.2% | -2.1% to +1.8% | 1.000 |

## Warnings

- 763 players saw several variants and were excluded

## Metric definitions

- `bets_per_player`: Bets placed per exposed player in the window
- `ggr_per_player`: Gross gaming revenue (stake minus payout) per exposed player in the window
- `margin`: Hold, ggr / stake, over all players of the arm (a ratio of sums)
- `avg_stake`: Average stake per bet. Guardrail for responsible gaming, a rise is not a win
