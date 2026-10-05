"""HTTP API for the toolpath audit service (standard library only).

Endpoints
---------
GET  /health                  -> {"status": "ok"}
POST /api/toolpaths/audit     -> audit a probe program (see README)

Audit outcomes (success or violation) are reported with HTTP 200 and an
``ok`` flag; structurally invalid requests get HTTP 400.  A failed audit
never contains any trajectory data.
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .gcode import AXES, AuditError, audit_program
from .validation import RequestError, parse_body, validate_request

AUDIT_PATH = "/api/toolpaths/audit"
HEALTH_PATH = "/health"


def format_decimal(value):
    """Canonical plain decimal string: no exponent, no trailing zeros."""
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def format_position(pos):
    return {axis: format_decimal(pos[axis]) for axis in AXES}


def success_payload(segments, final_position):
    return {
        "ok": True,
        "units": "mm",
        "segment_count": len(segments),
        "segments": [
            {"start": format_position(seg["start"]), "end": format_position(seg["end"])}
            for seg in segments
        ],
        "final_position": format_position(final_position),
    }


def error_payload(reason, message, line=None, zone_index=None):
    return {
        "ok": False,
        "error": {
            "line": line,
            "reason": reason,
            "message": message,
            "zone_index": zone_index,
        },
    }


class AuditHandler(BaseHTTPRequestHandler):
    server_version = "ToolpathAudit/1.0"
    protocol_version = "HTTP/1.1"

    # -- helpers ---------------------------------------------------------

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self):
        self._send_json(
            404,
            error_payload("not_found", f"unknown path {self.path!r}"),
        )

    # -- routes ----------------------------------------------------------

    def do_GET(self):
        if self.path == HEALTH_PATH:
            self._send_json(200, {"status": "ok"})
        elif self.path == "/":
            self._send_json(
                200,
                {
                    "service": "toolpath-audit",
                    "endpoints": {"health": HEALTH_PATH, "audit": AUDIT_PATH},
                },
            )
        else:
            self._not_found()

    def do_POST(self):
        if self.path != AUDIT_PATH:
            self._not_found()
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            body = parse_body(raw)
            initial, ws_min, ws_max, zones, program = validate_request(body)
        except RequestError as exc:
            self._send_json(400, error_payload("invalid_request", exc.message))
            return
        try:
            segments, final_position = audit_program(
                initial, ws_min, ws_max, zones, program
            )
        except AuditError as exc:
            self._send_json(
                200,
                error_payload(exc.reason, exc.message, exc.line, exc.zone_index),
            )
            return
        except Exception as exc:  # pragma: no cover - defensive
            self.log_error("unexpected audit failure: %r", exc)
            self._send_json(500, error_payload("internal_error", "internal error"))
            return
        self._send_json(200, success_payload(segments, final_position))

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def create_server(host="0.0.0.0", port=8000):
    return ThreadingHTTPServer((host, port), AuditHandler)
