"""Exact decimal geometry for the toolpath audit.

The audit must decide whether a closed 3D segment touches a closed
axis-aligned box (a forbidden zone).  All arithmetic is done with
``decimal.Decimal`` and the intersection test is phrased entirely without
division, so every comparison is exact: each axis constrains the segment
parameter ``t`` to an interval stored as a fraction ``num/den`` with
``den > 0``, and fractions are compared by cross-multiplication.
"""
from __future__ import annotations

from decimal import Decimal

AXES = ("x", "y", "z")

_ZERO = Decimal(0)
_ONE = Decimal(1)


def segment_intersects_box(start, end, box_min, box_max):
    """Return True iff the closed segment ``start``->``end`` touches the
    closed box ``[box_min, box_max]``.

    Touching the boundary counts as intersection.  ``start``, ``end``,
    ``box_min`` and ``box_max`` are dicts mapping "x"/"y"/"z" to Decimal.
    """
    # Current intersection of the per-axis t-intervals, clamped to [0, 1],
    # kept as fractions with positive denominators.
    lo_num, lo_den = _ZERO, _ONE  # running maximum of lower bounds (starts at t=0)
    hi_num, hi_den = _ONE, _ONE   # running minimum of upper bounds (starts at t=1)

    for axis in AXES:
        a = start[axis]
        d = end[axis] - a
        mn = box_min[axis]
        mx = box_max[axis]

        if d == 0:
            # Segment is constant along this axis: it must lie inside the slab.
            if a < mn or a > mx:
                return False
            continue

        if d > 0:
            n_lo = mn - a   # t where the segment enters the slab: (mn - a) / d
            n_hi = mx - a   # t where the segment leaves the slab: (mx - a) / d
            den = d
        else:
            # Same fractions with a positive denominator.
            n_lo = a - mx
            n_hi = a - mn
            den = -d

        # t_low = max(t_low, n_lo/den):  n_lo/den > lo_num/lo_den  <=>
        # n_lo*lo_den > lo_num*den  (all denominators are positive).
        if n_lo * lo_den > lo_num * den:
            lo_num, lo_den = n_lo, den
        # t_high = min(t_high, n_hi/den).
        if n_hi * hi_den < hi_num * den:
            hi_num, hi_den = n_hi, den

    # The segment touches the box iff t_low <= t_high.
    return lo_num * hi_den <= hi_num * lo_den
