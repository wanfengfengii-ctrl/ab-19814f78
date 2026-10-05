"""Tests for the program parser / interpreter."""
import unittest
from decimal import Decimal

from app.gcode import AuditError, audit_program

WS_MIN = {"x": Decimal("-1000"), "y": Decimal("-1000"), "z": Decimal("-1000")}
WS_MAX = {"x": Decimal("1000"), "y": Decimal("1000"), "z": Decimal("1000")}
ORIGIN = {"x": Decimal(0), "y": Decimal(0), "z": Decimal(0)}


def zone(mn, mx):
    return (
        {"x": Decimal(mn[0]), "y": Decimal(mn[1]), "z": Decimal(mn[2])},
        {"x": Decimal(mx[0]), "y": Decimal(mx[1]), "z": Decimal(mx[2])},
    )


def run(program, initial=ORIGIN, zones=()):
    return audit_program(initial, WS_MIN, WS_MAX, list(zones), program)


def expect_error(reason, program, initial=ORIGIN, zones=()):
    try:
        run(program, initial=initial, zones=zones)
    except AuditError as exc:
        assert exc.reason == reason, f"expected {reason}, got {exc.reason}: {exc.message}"
        return exc
    raise AssertionError(f"expected AuditError({reason}) for program {program!r}")


class ModalTests(unittest.TestCase):
    def test_absolute_mm_moves(self):
        segments, final = run("G21\nG90\nG1 X10 Y5 Z-2\nG0 X0 Y0 Z0\n")
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["end"], {"x": Decimal(10), "y": Decimal(5), "z": Decimal(-2)})
        self.assertEqual(final, ORIGIN)

    def test_relative_moves_accumulate_exactly(self):
        segments, final = run("G91\nG1 X0.1\nG1 X0.2\n")
        # 0.1 + 0.2 == 0.3 exactly in decimal arithmetic.
        self.assertEqual(final["x"], Decimal("0.3"))

    def test_inch_conversion_is_exact(self):
        segments, final = run("G20 G90\nG1 X1\n")
        self.assertEqual(final["x"], Decimal("25.4"))

    def test_same_line_settings_apply_to_that_line(self):
        # G20 and G91 appear on the same line as the motion: they must take
        # effect before the coordinates are interpreted.
        _, final = run("G20 G91 G1 X1\n")
        self.assertEqual(final["x"], Decimal("25.4"))

    def test_modal_settings_persist(self):
        _, final = run("G20\nG91\nG1 X1\nX1\n")
        self.assertEqual(final["x"], Decimal("50.8"))

    def test_units_switch_mid_program(self):
        _, final = run("G90\nG1 X10\nG20 G1 X1\nG21 G1 X20\n")
        self.assertEqual(final["x"], Decimal(20))

    def test_motion_mode_persists(self):
        segments, _ = run("G1 X1\nX2\nX3\n")
        self.assertEqual(len(segments), 3)

    def test_g0_and_g1_both_move(self):
        segments, _ = run("G0 X1\nG1 X2\n")
        self.assertEqual(len(segments), 2)

    def test_word_order_does_not_matter(self):
        _, final = run("X5 G91 G1\n")
        self.assertEqual(final["x"], Decimal(5))

    def test_defaults_are_mm_absolute(self):
        _, final = run("G1 X7\n")
        self.assertEqual(final["x"], Decimal(7))


class CommentAndBlankLineTests(unittest.TestCase):
    def test_empty_and_comment_lines_produce_no_motion(self):
        program = "; header comment\n\n   \nG1 X1 ; trailing comment\n; another\n"
        segments, final = run(program)
        self.assertEqual(len(segments), 1)
        self.assertEqual(final["x"], Decimal(1))

    def test_comment_only_program(self):
        segments, final = run("; nothing to do\n\n")
        self.assertEqual(segments, [])
        self.assertEqual(final, ORIGIN)

    def test_semicolon_inside_line(self):
        segments, _ = run("G1 X1;move to x1\n")
        self.assertEqual(len(segments), 1)


class ErrorLocationTests(unittest.TestCase):
    def test_error_reports_original_line_number(self):
        exc = expect_error("illegal_word", "; c1\n\nG1 X1\nG1 X2 Q3\n")
        self.assertEqual(exc.line, 4)

    def test_illegal_word(self):
        expect_error("illegal_word", "G1 X1 F100\n")  # F is not supported
        expect_error("illegal_word", "G1 X1 42\n")
        expect_error("illegal_word", "G1 X1 X\n")
        expect_error("illegal_word", "G7 X1\n")
        expect_error("illegal_word", "G1 X1e3\n")  # exponent is not canonical
        expect_error("illegal_word", "G1 X1.\n")

    def test_duplicate_axis(self):
        exc = expect_error("duplicate_axis", "G1 X1 Y2 X3\n")
        self.assertEqual(exc.line, 1)

    def test_conflicting_modal(self):
        expect_error("conflicting_modal", "G90 G91 G1 X1\n")
        expect_error("conflicting_modal", "G0 G1 X1\n")
        expect_error("conflicting_modal", "G20 G21\n")

    def test_non_finite_decimal(self):
        expect_error("non_finite_decimal", "G1 Xnan\n")
        expect_error("non_finite_decimal", "G1 X-inf\n")
        expect_error("non_finite_decimal", "G1 XInfinity\n")

    def test_missing_motion_mode(self):
        exc = expect_error("missing_motion_mode", "G21\nG90\nX5\n")
        self.assertEqual(exc.line, 3)

    def test_first_error_wins(self):
        exc = expect_error("duplicate_axis", "G1 X1 X2\nG1 Xnan\n")
        self.assertEqual(exc.line, 1)


class WorkspaceTests(unittest.TestCase):
    def test_endpoint_on_workspace_boundary_is_allowed(self):
        _, final = run("G1 X1000\n")
        self.assertEqual(final["x"], Decimal(1000))

    def test_endpoint_outside_workspace_rejected(self):
        exc = expect_error("workspace_violation", "G1 X1000.0001\n")
        self.assertEqual(exc.line, 1)

    def test_relative_move_outside_workspace(self):
        expect_error("workspace_violation", "G91\nG1 X900\nG1 X200\n")

    def test_initial_position_outside_workspace(self):
        exc = expect_error(
            "workspace_violation",
            "G1 X0\n",
            initial={"x": Decimal("1001"), "y": Decimal(0), "z": Decimal(0)},
        )
        self.assertIsNone(exc.line)


class ForbiddenZoneTests(unittest.TestCase):
    ZONES = [zone(("10", "-1", "-1"), ("20", "1", "1"))]

    def test_segment_crossing_zone_rejected(self):
        exc = expect_error("forbidden_zone_violation", "G1 X30\n", zones=self.ZONES)
        self.assertEqual(exc.zone_index, 0)
        self.assertEqual(exc.line, 1)

    def test_touching_zone_boundary_rejected(self):
        # Endpoint lands exactly on the zone face x=10: contact.
        expect_error("forbidden_zone_violation", "G1 X10\n", zones=self.ZONES)

    def test_just_short_of_zone_is_allowed(self):
        segments, final = run("G1 X9.999\n", zones=self.ZONES)
        self.assertEqual(len(segments), 1)
        self.assertEqual(final["x"], Decimal("9.999"))

    def test_exact_decimal_boundary_contact(self):
        # 0.1 + 0.2 == 0.3 exactly: the probe tip ends exactly on the zone.
        zones = [zone(("0.3", "-1", "-1"), ("1", "1", "1"))]
        expect_error("forbidden_zone_violation", "G91\nG1 X0.1\nG1 X0.2\n", zones=zones)

    def test_lowest_zone_index_reported(self):
        # The segment crosses both zones; the lower index must be reported.
        zones = [
            zone(("5", "-1", "-1"), ("6", "1", "1")),
            zone(("3", "-1", "-1"), ("4", "1", "1")),
        ]
        exc = expect_error("forbidden_zone_violation", "G1 X10\n", zones=zones)
        self.assertEqual(exc.zone_index, 0)

    def test_first_violating_line_reported(self):
        program = "G1 X5\nG1 X30\nG1 X40\n"
        exc = expect_error("forbidden_zone_violation", program, zones=self.ZONES)
        self.assertEqual(exc.line, 2)

    def test_degenerate_move_inside_zone_rejected(self):
        zones = [zone(("0", "-1", "-1"), ("1", "1", "1"))]
        expect_error("forbidden_zone_violation", "G91\nG1 X0\n", zones=zones)


class NoPartialTrajectoryTests(unittest.TestCase):
    def test_failure_raises_instead_of_returning_segments(self):
        # A valid first move followed by a violation must raise, so the
        # caller never sees the partial trajectory.
        program = "G1 X5\nG1 X9999\n"
        expect_error("workspace_violation", program)


if __name__ == "__main__":
    unittest.main()
