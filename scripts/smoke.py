#!/usr/bin/env python3
"""End-to-end smoke test against a running toolpath-audit API.

Exercises the health endpoint, a plain millimetre program, an inch program
with relative moves, and the main rejection paths.  Exits 0 on success, 1
on any failure.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    line = f"[{status}] {name}"
    if detail and not condition:
        line += f" -- {detail}"
    print(line, flush=True)
    if not condition:
        FAILURES.append(name)


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())
    except OSError:
        return None, None


def audit(payload):
    req = urllib.request.Request(
        BASE + "/api/toolpaths/audit",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def base_payload(**overrides):
    payload = {
        "initial_position": {"x": "0", "y": "0", "z": "0"},
        "workspace": {
            "min": {"x": "-500", "y": "-500", "z": "-500"},
            "max": {"x": "500", "y": "500", "z": "500"},
        },
        "forbidden_zones": [],
        "program": "",
    }
    payload.update(overrides)
    return payload


def wait_for_health(timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, _ = get("/health")
        if status == 200:
            return True
        time.sleep(1)
    return False


def main():
    print(f"smoke testing API at {BASE}", flush=True)
    check("health endpoint becomes ready", wait_for_health(), "no 200 from /health")
    if FAILURES:
        return finish()

    status, body = get("/health")
    check("health returns ok", status == 200 and body.get("status") == "ok", str(body))

    # 1. Plain millimetre absolute program.
    status, body = audit(base_payload(program="G21\nG90\nG1 X10 Y5 Z-2\nG0 X0 Y0 Z0\n"))
    check("mm absolute program accepted", status == 200 and body.get("ok") is True, str(body))
    if body:
        check(
            "mm absolute final position",
            body.get("final_position") == {"x": "0", "y": "0", "z": "0"},
            str(body.get("final_position")),
        )
        check("mm absolute segment count", body.get("segment_count") == 2, str(body))

    # 2. Inch units with relative motion (required smoke case).
    inch_program = (
        "; inch relative smoke\n"
        "G20 G91\n"
        "G1 X1            ; one inch in x\n"
        "G1 Y-0.5 Z0.25\n"
    )
    status, body = audit(base_payload(program=inch_program))
    check("inch relative program accepted", status == 200 and body.get("ok") is True, str(body))
    if body and body.get("ok"):
        check(
            "inch relative final position is exact mm",
            body.get("final_position") == {"x": "25.4", "y": "-12.7", "z": "6.35"},
            str(body.get("final_position")),
        )
        check(
            "inch relative segments normalised to mm",
            body.get("segments") == [
                {"start": {"x": "0", "y": "0", "z": "0"}, "end": {"x": "25.4", "y": "0", "z": "0"}},
                {"start": {"x": "25.4", "y": "0", "z": "0"}, "end": {"x": "25.4", "y": "-12.7", "z": "6.35"}},
            ],
            str(body.get("segments")),
        )

    # 3. Forbidden zone contact (boundary touch) is rejected with zone index.
    zone_payload = base_payload(
        program="G21 G90\nG1 X10\n",
        forbidden_zones=[
            {"min": {"x": "10", "y": "-1", "z": "-1"}, "max": {"x": "20", "y": "1", "z": "1"}}
        ],
    )
    status, body = audit(zone_payload)
    check(
        "zone boundary touch rejected",
        status == 200
        and body.get("ok") is False
        and body.get("error", {}).get("reason") == "forbidden_zone_violation"
        and body["error"].get("zone_index") == 0
        and body["error"].get("line") == 2,
        str(body),
    )
    check("rejection carries no partial trajectory", body is not None and "segments" not in body, str(body))

    # 4. Workspace violation is reported.
    status, body = audit(base_payload(program="G1 X999\n"))
    check(
        "workspace violation reported",
        body is not None
        and body.get("ok") is False
        and body.get("error", {}).get("reason") == "workspace_violation"
        and body["error"].get("line") == 1,
        str(body),
    )

    # 5. Language errors are located to their line.
    cases = [
        ("G1 X1 X2\n", "duplicate_axis", 1),
        ("G1 Xnan\n", "non_finite_decimal", 1),
        ("G1 X1 F5\n", "illegal_word", 1),
        ("G90 G91 G1 X1\n", "conflicting_modal", 1),
        ("G21\nX5\n", "missing_motion_mode", 2),
    ]
    for program, reason, line in cases:
        _, body = audit(base_payload(program=program))
        check(
            f"error {reason} located at line {line}",
            body is not None
            and body.get("ok") is False
            and body.get("error", {}).get("reason") == reason
            and body["error"].get("line") == line,
            f"{program!r} -> {body}",
        )

    # 6. Malformed requests get HTTP 400.
    status, body = audit({"program": "G1 X1"})
    check("missing fields rejected with 400", status == 400, f"status={status} body={body}")

    return finish()


def finish():
    if FAILURES:
        print(f"SMOKE FAILED: {len(FAILURES)} check(s) failed: {', '.join(FAILURES)}", flush=True)
        return 1
    print("SMOKE OK: all checks passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
