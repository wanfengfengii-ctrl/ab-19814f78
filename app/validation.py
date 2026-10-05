"""Request-body validation for the audit endpoint.

JSON numbers are parsed straight into ``Decimal`` (never ``float``) so the
values the caller wrote are the values the audit uses.
"""
from __future__ import annotations

import json
from decimal import Decimal

from .gcode import (
    AXES,
    CANONICAL_DECIMAL_RE,
    MAX_PROGRAM_LINES,
    NONFINITE_DECIMAL_RE,
)

MAX_FORBIDDEN_ZONES = 20


class RequestError(Exception):
    """A structurally invalid request (maps to HTTP 400)."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _reject_constant(value):
    # json.parse_constant is only called for NaN / Infinity / -Infinity.
    raise RequestError(f"non-finite number {value!r} is not allowed")


def parse_body(raw):
    """Parse the request body as JSON with exact decimal numbers."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise RequestError("request body must be UTF-8 JSON")
    try:
        body = json.loads(
            text,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=_reject_constant,
        )
    except RequestError:
        raise
    except json.JSONDecodeError as exc:
        raise RequestError(f"invalid JSON: {exc}")
    if not isinstance(body, dict):
        raise RequestError("request body must be a JSON object")
    return body


def _decimal(value, where):
    if isinstance(value, bool):
        raise RequestError(f"{where} must be a decimal, not a boolean")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise RequestError(f"{where} must be a finite decimal")
        return value
    if isinstance(value, str):
        text = value.strip()
        if NONFINITE_DECIMAL_RE.fullmatch(text):
            raise RequestError(f"{where} must be a finite decimal")
        if not CANONICAL_DECIMAL_RE.fullmatch(text):
            raise RequestError(f"{where} is not a canonical decimal: {value!r}")
        return Decimal(text)
    raise RequestError(f"{where} must be a decimal number or decimal string")


def _position(obj, where):
    if not isinstance(obj, dict):
        raise RequestError(f"{where} must be an object with x, y, z coordinates")
    out = {}
    for axis in AXES:
        if axis not in obj:
            raise RequestError(f"{where} is missing coordinate {axis!r}")
        out[axis] = _decimal(obj[axis], f"{where}.{axis}")
    return out


def _box(obj, where):
    if not isinstance(obj, dict):
        raise RequestError(f"{where} must be an object with 'min' and 'max'")
    if "min" not in obj or "max" not in obj:
        raise RequestError(f"{where} requires both 'min' and 'max'")
    mn = _position(obj["min"], f"{where}.min")
    mx = _position(obj["max"], f"{where}.max")
    for axis in AXES:
        if mn[axis] > mx[axis]:
            raise RequestError(f"{where}: min.{axis} exceeds max.{axis}")
    return mn, mx


def validate_request(body):
    """Validate a parsed request body.

    Returns ``(initial_position, workspace_min, workspace_max, zones,
    program)`` with all coordinates as exact Decimals in millimetres.
    """
    missing = [k for k in ("initial_position", "workspace", "program") if k not in body]
    if missing:
        raise RequestError(f"missing required field(s): {', '.join(missing)}")

    initial = _position(body["initial_position"], "initial_position")
    ws_min, ws_max = _box(body["workspace"], "workspace")

    zones_raw = body.get("forbidden_zones", [])
    if not isinstance(zones_raw, list):
        raise RequestError("forbidden_zones must be an array")
    if len(zones_raw) > MAX_FORBIDDEN_ZONES:
        raise RequestError(
            f"at most {MAX_FORBIDDEN_ZONES} forbidden zones are allowed"
        )
    zones = [_box(zone, f"forbidden_zones[{i}]") for i, zone in enumerate(zones_raw)]

    program = body["program"]
    if not isinstance(program, str):
        raise RequestError("program must be a string")
    if len(program.splitlines()) > MAX_PROGRAM_LINES:
        raise RequestError(f"program must not exceed {MAX_PROGRAM_LINES} lines")

    return initial, ws_min, ws_max, zones, program
