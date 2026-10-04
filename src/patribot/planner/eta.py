"""ETA baseline `baseline_hist` (architecture doc §6, baselines B1/B2): predicted arrival delay at a station from
historical delay percentiles, falling back to coarser levels when a train has little history. Pure functions.

For a train arriving at a station in a given run month, the first level with enough runs wins:

  1. train × station × month       n >= MIN_RUNS                          basis "train_station_month"
  2. train × station, all months   n >= MIN_RUNS                          basis "train_station"
  3. prior: the train's final-arrival delay (that month if n >= MIN_RUNS, else all months), scaled by the fraction of
     the route travelled to the station                                    basis "train_route_scaled"
  4. prior: the same for the corridor's member trains (largest corridor sample)  basis "corridor_route_scaled"
  5. zero delay                                                             basis "none"

When the station has 1..MIN_RUNS-1 runs of its own, its numbers are shrunk toward the prior with weight
n / (n + SHRINK_K) (basis "train_station_shrunk"). `history_runs` counts runs of THIS train behind the estimate
(0 for the corridor and zero fallbacks: the API's "fallback estimate").

Reliability = P(arrival delay <= ON_TIME_MIN). Station levels use the empirical share; a scaled prior uses a normal
approximation fitted to its scaled P50/P90 (the empirical share when the station is at the end of the route). The
corridor fallback's reliability is pulled halfway toward 0.5; with no history at all it is 0.5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from patribot.planner.model import DelayStat, DelayStats

MIN_RUNS = 5
SHRINK_K = 5.0
ON_TIME_MIN = 30.0
NO_HISTORY_RELIABILITY = 0.5  # uninformative: no evidence either way
# Other trains' punctuality says only so much about this one: the corridor fallback's reliability is pulled halfway
# toward NO_HISTORY_RELIABILITY, so a train without history does not outrank a measured one on borrowed numbers.
CORRIDOR_RELIABILITY_WEIGHT = 0.5
Z90 = 1.2815515655446004  # standard normal 90th percentile


@dataclass(frozen=True)
class DelayEstimate:
    p50: float  # minutes; negative = early
    p90: float
    reliability: float  # P(delay <= ON_TIME_MIN), 0..1
    history_runs: int
    basis: str

    @property
    def is_fallback(self) -> bool:
        return self.history_runs == 0


ZERO = DelayEstimate(0.0, 0.0, NO_HISTORY_RELIABILITY, 0, "none")


def normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def prob_within(p50: float, p90: float, threshold: float = ON_TIME_MIN) -> float:
    """P(delay <= threshold) under a normal fitted to the median and the 90th percentile."""
    sigma = (p90 - p50) / Z90
    if sigma <= 1e-9:
        return 1.0 if p50 <= threshold else 0.0
    return normal_cdf((threshold - p50) / sigma)


def _enough(stat: DelayStat | None) -> DelayStat | None:
    return stat if stat is not None and stat.n_runs >= MIN_RUNS else None


def _scaled(stat: DelayStat, fraction: float, runs: int, basis: str, rel_weight: float = 1.0) -> DelayEstimate:
    p50, p90 = stat.p50 * fraction, max(stat.p90, stat.p50) * fraction
    # near the end of the route the train's own on-time share applies; elsewhere a normal fit to the scaled spread
    rel = stat.pct_within if fraction >= 0.95 and stat.pct_within is not None else prob_within(p50, p90)
    rel = rel_weight * rel + (1 - rel_weight) * NO_HISTORY_RELIABILITY
    return DelayEstimate(p50, p90, rel, runs, basis)


def prior_estimate(
    stats: DelayStats, train_no: str, month: str | None, route_fraction: float, corridors: tuple[str, ...] = ()
) -> DelayEstimate:
    """Levels 3–5: the train's (else its corridors') final-arrival delay scaled by the route fraction, else zero."""
    frac = min(1.0, max(0.0, route_fraction))
    t = (_enough(stats.train.get((train_no, month))) if month else None) or _enough(stats.train.get((train_no, "all")))
    if t is not None:
        return _scaled(t, frac, t.n_runs, "train_route_scaled")
    best: DelayStat | None = None
    for c in corridors:
        s = (_enough(stats.corridor.get((c, month))) if month else None) or _enough(stats.corridor.get((c, "all")))
        if s is not None and (best is None or s.n_runs > best.n_runs):
            best = s
    if best is not None:
        return _scaled(best, frac, 0, "corridor_route_scaled", CORRIDOR_RELIABILITY_WEIGHT)
    return ZERO


def estimate_delay(
    stats: DelayStats,
    train_no: str,
    station: str,
    month: str | None,
    route_fraction: float | None,
    corridors: tuple[str, ...] = (),
) -> DelayEstimate:
    """Arrival-delay estimate for `train_no` at `station` on a run starting in `month` ('YYYY-MM' or None)."""
    if month and (m := _enough(stats.stop_month.get((train_no, station, month)))):
        return DelayEstimate(m.p50, max(m.p90, m.p50), _rel(m), m.n_runs, "train_station_month")
    own = stats.stop_all.get((train_no, station))
    if own is not None and own.n_runs >= MIN_RUNS:
        return DelayEstimate(own.p50, max(own.p90, own.p50), _rel(own), own.n_runs, "train_station")
    prior = prior_estimate(stats, train_no, month, route_fraction if route_fraction is not None else 1.0, corridors)
    if own is None or own.n_runs <= 0:
        return prior
    w = own.n_runs / (own.n_runs + SHRINK_K)
    p50 = w * own.p50 + (1 - w) * prior.p50
    p90 = max(w * max(own.p90, own.p50) + (1 - w) * prior.p90, p50)
    rel = w * _rel(own) + (1 - w) * prior.reliability
    return DelayEstimate(p50, p90, rel, own.n_runs, "train_station_shrunk")


def _rel(stat: DelayStat) -> float:
    return stat.pct_within if stat.pct_within is not None else prob_within(stat.p50, stat.p90)
