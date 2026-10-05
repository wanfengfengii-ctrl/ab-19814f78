"""Exactness tests for the segment/box intersection predicate."""
import unittest
from decimal import Decimal

from app.geometry import segment_intersects_box


def P(x, y, z):
    return {"x": Decimal(x), "y": Decimal(y), "z": Decimal(z)}


def box(mn, mx):
    return P(*mn), P(*mx)


class SegmentBoxTests(unittest.TestCase):
    def test_crossing_segment(self):
        mn, mx = box((5, -1, -1), (6, 1, 1))
        self.assertTrue(segment_intersects_box(P(0, 0, 0), P(10, 0, 0), mn, mx))

    def test_missing_segment(self):
        mn, mx = box((5, -1, -1), (6, 1, 1))
        self.assertFalse(segment_intersects_box(P(0, 0, 0), P(4, 0, 0), mn, mx))

    def test_endpoint_on_boundary_counts(self):
        mn, mx = box((10, -1, -1), (12, 1, 1))
        # Segment ends exactly on the box face x=10: contact.
        self.assertTrue(segment_intersects_box(P(0, 0, 0), P(10, 0, 0), mn, mx))

    def test_start_on_boundary_counts(self):
        mn, mx = box((0, -1, -1), (2, 1, 1))
        self.assertTrue(segment_intersects_box(P(0, 0, 0), P(-5, 0, 0), mn, mx))

    def test_degenerate_segment_inside(self):
        mn, mx = box((1, 1, 1), (2, 2, 2))
        self.assertTrue(segment_intersects_box(P("1.5", "1.5", "1.5"), P("1.5", "1.5", "1.5"), mn, mx))

    def test_degenerate_segment_outside(self):
        mn, mx = box((1, 1, 1), (2, 2, 2))
        self.assertFalse(segment_intersects_box(P(3, 3, 3), P(3, 3, 3), mn, mx))

    def test_parallel_outside_slab(self):
        mn, mx = box((1, 1, 1), (2, 2, 2))
        self.assertFalse(segment_intersects_box(P(0, 3, 0), P(1, 3, 1), mn, mx))

    def test_diagonal_graze_of_corner(self):
        mn, mx = box((1, 1, 1), (2, 2, 2))
        # Passes exactly through the corner (1,1,1).
        self.assertTrue(segment_intersects_box(P(0, 0, 0), P(3, 3, 3), mn, mx))

    def test_diagonal_just_missing_corner(self):
        mn, mx = box((1, 1, 1), (2, 2, 2))
        # While x and y are inside [1, 2] (t in [1/3, 2/3]), z stays below 1.
        self.assertFalse(segment_intersects_box(P(0, 0, 0), P(3, 3, "1.4"), mn, mx))

    def test_exact_decimal_boundary(self):
        # 0.1 + 0.2 == 0.3 exactly in decimal arithmetic; the endpoint must
        # be reported as touching the box whose face is at x = 0.3.
        end_x = Decimal("0.1") + Decimal("0.2")
        mn, mx = box(("0.3", "-1", "-1"), ("1", "1", "1"))
        self.assertTrue(segment_intersects_box(P(0, 0, 0), P(end_x, 0, 0), mn, mx))

    def test_exact_decimal_just_short(self):
        mn, mx = box(("0.3000000000000000001", "-1", "-1"), ("1", "1", "1"))
        end_x = Decimal("0.1") + Decimal("0.2")
        self.assertFalse(segment_intersects_box(P(0, 0, 0), P(end_x, 0, 0), mn, mx))

    def test_negative_direction(self):
        mn, mx = box((-6, -1, -1), (-5, 1, 1))
        self.assertTrue(segment_intersects_box(P(0, 0, 0), P(-10, 0, 0), mn, mx))
        self.assertFalse(segment_intersects_box(P(0, 0, 0), P(-4, 0, 0), mn, mx))

    def test_zero_thickness_box(self):
        # A degenerate (flat) forbidden zone still counts when touched.
        mn, mx = box((5, -1, -1), (5, 1, 1))
        self.assertTrue(segment_intersects_box(P(0, 0, 0), P(10, 0, 0), mn, mx))
        self.assertFalse(segment_intersects_box(P(0, 0, 0), P(4, 0, 0), mn, mx))

    def test_segment_inside_box(self):
        mn, mx = box((0, 0, 0), (10, 10, 10))
        self.assertTrue(segment_intersects_box(P(2, 2, 2), P(3, 3, 3), mn, mx))


if __name__ == "__main__":
    unittest.main()
