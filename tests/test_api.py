"""End-to-end tests of the HTTP API (server runs in a thread)."""
import json
import unittest
import urllib.error
import urllib.request

from app.server import create_server

BASE_REQUEST = {
    "initial_position": {"x": "0", "y": "0", "z": "0"},
    "workspace": {
        "min": {"x": "-1000", "y": "-1000", "z": "-1000"},
        "max": {"x": "1000", "y": "1000", "z": "1000"},
    },
    "forbidden_zones": [],
    "program": "G21\nG90\nG1 X10\n",
}


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        import threading

        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path):
        with urllib.request.urlopen(self.url(path), timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())

    def post(self, payload, raw=None):
        data = raw.encode() if raw is not None else json.dumps(payload).encode()
        req = urllib.request.Request(
            self.url("/api/toolpaths/audit"),
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    # -- health -----------------------------------------------------------

    def test_health(self):
        status, body = self.get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_unknown_path(self):
        try:
            self.get("/nope")
            self.fail("expected 404")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)

    # -- success path ------------------------------------------------------

    def test_successful_audit(self):
        status, body = self.post(BASE_REQUEST)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["units"], "mm")
        self.assertEqual(body["segment_count"], 1)
        self.assertEqual(body["segments"][0]["end"], {"x": "10", "y": "0", "z": "0"})
        self.assertEqual(body["final_position"], {"x": "10", "y": "0", "z": "0"})

    def test_json_numbers_accepted_and_exact(self):
        payload = dict(BASE_REQUEST)
        payload["initial_position"] = {"x": 0.25, "y": 0, "z": 0}
        payload["program"] = "G91\nG1 X0.1\n"
        status, body = self.post(payload)
        self.assertTrue(body["ok"])
        self.assertEqual(body["final_position"]["x"], "0.35")

    def test_inch_relative_move(self):
        payload = dict(BASE_REQUEST)
        payload["program"] = "G20 G91\nG1 X1\nG1 Y-0.5 Z0.25\n"
        status, body = self.post(payload)
        self.assertTrue(body["ok"])
        self.assertEqual(
            body["final_position"], {"x": "25.4", "y": "-12.7", "z": "6.35"}
        )
        self.assertEqual(body["segments"][1]["start"]["x"], "25.4")

    # -- audit failures -----------------------------------------------------

    def test_forbidden_zone_failure_shape(self):
        payload = dict(BASE_REQUEST)
        payload["forbidden_zones"] = [
            {"min": {"x": "5", "y": "-1", "z": "-1"}, "max": {"x": "6", "y": "1", "z": "1"}}
        ]
        status, body = self.post(payload)
        self.assertEqual(status, 200)
        self.assertFalse(body["ok"])
        self.assertNotIn("segments", body)  # no partial trajectory
        self.assertEqual(body["error"]["reason"], "forbidden_zone_violation")
        self.assertEqual(body["error"]["line"], 3)
        self.assertEqual(body["error"]["zone_index"], 0)

    def test_parse_error_located(self):
        payload = dict(BASE_REQUEST)
        payload["program"] = "G1 X1\n\n; comment\nG1 X2 X3\n"
        status, body = self.post(payload)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["reason"], "duplicate_axis")
        self.assertEqual(body["error"]["line"], 4)
        self.assertIsNone(body["error"]["zone_index"])

    # -- request validation --------------------------------------------------

    def test_missing_field(self):
        status, body = self.post({"program": "G1 X1\n"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["reason"], "invalid_request")

    def test_invalid_json(self):
        status, body = self.post(None, raw="{not json")
        self.assertEqual(status, 400)

    def test_json_nan_rejected(self):
        raw = '{"initial_position": {"x": NaN, "y": 0, "z": 0}, "workspace": {"min": {"x": -1, "y": -1, "z": -1}, "max": {"x": 1, "y": 1, "z": 1}}, "program": "G1 X0"}'
        status, body = self.post(None, raw=raw)
        self.assertEqual(status, 400)

    def test_too_many_zones(self):
        payload = dict(BASE_REQUEST)
        z = {"min": {"x": "0", "y": "0", "z": "0"}, "max": {"x": "1", "y": "1", "z": "1"}}
        payload["forbidden_zones"] = [z] * 21
        status, body = self.post(payload)
        self.assertEqual(status, 400)

    def test_too_many_lines(self):
        payload = dict(BASE_REQUEST)
        payload["program"] = "G21\n" * 5001
        status, body = self.post(payload)
        self.assertEqual(status, 400)

    def test_inverted_workspace(self):
        payload = dict(BASE_REQUEST)
        payload["workspace"] = {
            "min": {"x": "10", "y": "0", "z": "0"},
            "max": {"x": "5", "y": "1", "z": "1"},
        }
        status, body = self.post(payload)
        self.assertEqual(status, 400)

    def test_non_canonical_request_decimal(self):
        payload = dict(BASE_REQUEST)
        payload["initial_position"] = {"x": "1e2", "y": "0", "z": "0"}
        status, body = self.post(payload)
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
