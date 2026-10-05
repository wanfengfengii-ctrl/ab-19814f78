"""Parser and interpreter for the probe motion program language.

Supported language (line oriented, one motion per line at most):

* ``;`` starts a comment that runs to the end of the line.
* Words are a letter immediately followed by a canonical decimal number
  (``[+-]?(digits[.digits]|.digits)``; no exponents, no NaN/Infinity).
* ``G0`` / ``G1``  - linear motion mode (modal).
* ``G20`` / ``G21`` - units: inches / millimetres (modal).
* ``G90`` / ``G91`` - absolute / relative coordinates (modal).
* ``X`` ``Y`` ``Z`` - axis words.

Modal settings persist across lines and settings given on a line apply to
that line's own coordinates.  Giving axis words before any motion mode
(G0/G1) has been established is an error.  Defaults: G21 (mm) and G90
(absolute); the motion mode starts unset.

Everything is computed with exact decimal arithmetic; positions are always
tracked in millimetres.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from typing import Optional

from .geometry import AXES, segment_intersects_box

# The audit only ever adds, subtracts and multiplies Decimals (the
# intersection test avoids division), so with a generous precision context
# every operation is exact for any realistic input.
getcontext().prec = 1000

MM_PER_INCH = Decimal("25.4")  # exact by definition

CANONICAL_DECIMAL_RE = re.compile(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)")
NONFINITE_DECIMAL_RE = re.compile(r"[+-]?(?:inf(?:inity)?|nan)", re.IGNORECASE)

# Supported G words mapped to (modal group, setting).
G_WORDS = {
    0: ("motion", "G0"),
    1: ("motion", "G1"),
    20: ("units", "inch"),
    21: ("units", "mm"),
    90: ("distance", "absolute"),
    91: ("distance", "relative"),
}

MAX_PROGRAM_LINES = 5000


class AuditError(Exception):
    """A domain-level audit failure.

    ``line`` is the 1-based number of the original program line that caused
    the failure (None for failures not tied to a line).  ``zone_index`` is
    the 0-based index of the forbidden zone that was hit, when applicable.
    """

    def __init__(self, reason, message, line=None, zone_index=None):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.line = line
        self.zone_index = zone_index


@dataclass
class Interpreter:
    """Executes a program and collects the audited millimetre segments."""

    workspace_min: dict
    workspace_max: dict
    zones: list  # list of (zone_min, zone_max) dict pairs, in millimetres
    position: dict  # current position, millimetres
    motion_mode: Optional[str] = None  # None until G0/G1 is established
    units: str = "mm"  # "mm" (G21) or "inch" (G20)
    distance: str = "absolute"  # "absolute" (G90) or "relative" (G91)
    segments: list = field(default_factory=list)

    def run(self, program):
        for lineno, raw in enumerate(program.splitlines(), start=1):
            self._line(lineno, raw)
        return self.segments, self.position

    # -- line processing -------------------------------------------------

    def _line(self, lineno, raw):
        code = raw.split(";", 1)[0].strip()
        if not code:
            return  # empty line or comment-only line: no motion
        pending_modals = {}
        axes = {}
        for token in code.split():
            self._word(lineno, token, pending_modals, axes)
        # Modal settings on a line take effect before that line's own
        # coordinates are interpreted.
        if "units" in pending_modals:
            self.units = pending_modals["units"]
        if "distance" in pending_modals:
            self.distance = pending_modals["distance"]
        if "motion" in pending_modals:
            self.motion_mode = pending_modals["motion"]
        if axes:
            if self.motion_mode is None:
                raise AuditError(
                    "missing_motion_mode",
                    f"line {lineno}: coordinates given before any motion mode "
                    "(G0/G1) was established",
                    line=lineno,
                )
            self._move(lineno, axes)

    def _word(self, lineno, token, pending_modals, axes):
        letter = token[0]
        payload = token[1:]
        if not letter.isalpha() or not payload:
            raise AuditError(
                "illegal_word",
                f"line {lineno}: malformed word {token!r}",
                line=lineno,
            )
        letter = letter.upper()
        if letter not in ("G", "X", "Y", "Z"):
            raise AuditError(
                "illegal_word",
                f"line {lineno}: unsupported word letter {letter!r}",
                line=lineno,
            )
        if NONFINITE_DECIMAL_RE.fullmatch(payload):
            raise AuditError(
                "non_finite_decimal",
                f"line {lineno}: non-finite decimal in word {token!r}",
                line=lineno,
            )
        if not CANONICAL_DECIMAL_RE.fullmatch(payload):
            raise AuditError(
                "illegal_word",
                f"line {lineno}: non-canonical decimal in word {token!r}",
                line=lineno,
            )
        value = Decimal(payload)
        if letter == "G":
            if value not in G_WORDS:
                raise AuditError(
                    "illegal_word",
                    f"line {lineno}: unsupported G code {token!r}",
                    line=lineno,
                )
            group, setting = G_WORDS[value]
            if group in pending_modals:
                raise AuditError(
                    "conflicting_modal",
                    f"line {lineno}: conflicting {group} modal words on the same line",
                    line=lineno,
                )
            pending_modals[group] = setting
        else:
            axis = letter.lower()
            if axis in axes:
                raise AuditError(
                    "duplicate_axis",
                    f"line {lineno}: duplicate axis word {letter!r}",
                    line=lineno,
                )
            axes[axis] = value

    # -- motion ----------------------------------------------------------

    def _move(self, lineno, axes):
        factor = MM_PER_INCH if self.units == "inch" else Decimal(1)
        start = dict(self.position)
        target = dict(self.position)
        for axis, raw_value in axes.items():
            value_mm = raw_value * factor
            if self.distance == "absolute":
                target[axis] = value_mm
            else:
                target[axis] = target[axis] + value_mm

        # Segment endpoints must stay inside the closed workspace.  The
        # start point was validated when it became the current position, so
        # checking the new endpoint is sufficient (the workspace is convex).
        for axis in AXES:
            if not (self.workspace_min[axis] <= target[axis] <= self.workspace_max[axis]):
                raise AuditError(
                    "workspace_violation",
                    f"line {lineno}: endpoint {axis}={target[axis]} leaves the "
                    f"workspace [{self.workspace_min[axis]}, {self.workspace_max[axis]}]",
                    line=lineno,
                )

        # The segment must not touch any forbidden zone, boundary included.
        # Zones are scanned in order so the reported index is stable.
        for zone_index, (zone_min, zone_max) in enumerate(self.zones):
            if segment_intersects_box(start, target, zone_min, zone_max):
                raise AuditError(
                    "forbidden_zone_violation",
                    f"line {lineno}: segment touches forbidden zone {zone_index}",
                    line=lineno,
                    zone_index=zone_index,
                )

        self.position = target
        self.segments.append({"start": start, "end": target})


def audit_program(initial_position, workspace_min, workspace_max, zones, program):
    """Run the full audit.

    Returns ``(segments, final_position)`` where every coordinate is an
    exact Decimal in millimetres.  Raises :class:`AuditError` on the first
    violation; no partial trajectory is returned in that case.
    """
    for axis in AXES:
        if not (workspace_min[axis] <= initial_position[axis] <= workspace_max[axis]):
            raise AuditError(
                "workspace_violation",
                f"initial position {axis}={initial_position[axis]} is outside "
                f"the workspace [{workspace_min[axis]}, {workspace_max[axis]}]",
                line=None,
            )
    interp = Interpreter(
        workspace_min=workspace_min,
        workspace_max=workspace_max,
        zones=zones,
        position=dict(initial_position),
    )
    return interp.run(program)
