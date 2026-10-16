import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from illustrator_curves.geom import bezier as bz  # noqa: E402
from illustrator_curves.geom import shapes  # noqa: E402
from illustrator_curves.geom.boolean import boolean  # noqa: E402
from illustrator_curves.geom.fillet import fillet_path, corner_angles  # noqa: E402
from illustrator_curves.geom.fit import fit_polyline, simplify_path  # noqa: E402
from illustrator_curves.geom.offset import offset_paths, outline_paths  # noqa: E402
from illustrator_curves.geom.path import Path  # noqa: E402
from illustrator_curves.geom.pen import PenState, constrain_45  # noqa: E402


def square(x, y, s):
    return Path.from_polyline([(x, y), (x + s, y), (x + s, y + s), (x, y + s)], closed=True)


def circle(cx, cy, r):
    return shapes.ellipse(r, r).transformed(lambda p: (p[0] + cx, p[1] + cy))


def total_area(paths):
    return sum(p.area(1e-5) for p in paths)


TOL = 1e-4


class TestBezier:
    def test_split_and_sub_reconstruct(self):
        seg = ((0, 0), (1, 2), (3, 2), (4, 0))
        a, b = bz.split(seg, 0.3)
        assert bz.point(a, 1.0) == pytest.approx(bz.point(seg, 0.3))
        s = bz.sub(seg, 0.2, 0.7)
        assert bz.point(s, 0.0) == pytest.approx(bz.point(seg, 0.2))
        assert bz.point(s, 1.0) == pytest.approx(bz.point(seg, 0.7))
        r = bz.sub(seg, 0.7, 0.2)
        assert bz.point(r, 0.0) == pytest.approx(bz.point(seg, 0.7))

    def test_length_of_line_and_t_at_length(self):
        seg = bz.line((0, 0), (10, 0))
        assert bz.length(seg) == pytest.approx(10)
        assert bz.point(seg, bz.t_at_length(seg, 2.5))[0] == pytest.approx(2.5, abs=1e-6)

    def test_flatten_respects_tolerance(self):
        seg = ((0, 0), (0, 1), (1, 1), (1, 0))
        ts = bz.flatten_ts(seg, 1e-3)
        for a, b in zip(ts, ts[1:]):
            mid = bz.point(seg, 0.5 * (a + b))
            pa, pb = bz.point(seg, a), bz.point(seg, b)
            assert bz._dist_point_segment(mid, pa, pb) <= 1.1e-3


class TestBoolean:
    def test_union_of_overlapping_squares(self):
        res = boolean([[square(0, 0, 2)], [square(1, 1, 2)]], "UNION", TOL)
        assert len(res) == 1
        assert total_area(res) == pytest.approx(7.0)
        assert len(res[0].nodes) == 8

    def test_intersect_difference_exclude(self):
        a, b = [square(0, 0, 2)], [square(1, 1, 2)]
        assert total_area(boolean([a, b], "INTERSECT", TOL)) == pytest.approx(1.0)
        assert total_area(boolean([a, b], "DIFFERENCE", TOL)) == pytest.approx(3.0)
        assert total_area(boolean([a, b], "EXCLUDE", TOL)) == pytest.approx(6.0, rel=1e-4)

    def test_touching_loops_are_separated(self):
        res = boolean([[square(0, 0, 1)], [square(1, 1, 1)]], "UNION", TOL)
        assert len(res) == 2
        assert total_area(res) == pytest.approx(2.0, rel=1e-4)
        a = {n.co for n in res[0].nodes}
        b = {n.co for n in res[1].nodes}
        assert not (a & b)

    def test_hole_is_produced(self):
        res = boolean([[square(0, 0, 4)], [square(1, 1, 2)]], "DIFFERENCE", TOL)
        assert len(res) == 2
        assert total_area(res) == pytest.approx(12.0)

    def test_shared_edges(self):
        res = boolean([[square(0, 0, 1)], [square(1, 0, 1)]], "UNION", TOL)
        assert len(res) == 1
        assert total_area(res) == pytest.approx(2.0)
        assert len(res[0].nodes) == 4  # collinear edges are merged

    def test_identical_shapes(self):
        res = boolean([[square(0, 0, 1)], [square(0, 0, 1)]], "UNION", TOL)
        assert total_area(res) == pytest.approx(1.0)
        assert boolean([[square(0, 0, 1)], [square(0, 0, 1)]], "EXCLUDE", TOL) == []

    def test_disjoint_intersect_is_empty(self):
        assert boolean([[square(0, 0, 1)], [square(5, 5, 1)]], "INTERSECT", TOL) == []

    def test_circles_keep_curves(self):
        res = boolean([[circle(0, 0, 1)], [circle(1, 0, 1)]], "UNION", TOL)
        assert len(res) == 1
        # two circular lenses: exact area of union of two unit circles at distance 1
        lens = 2 * math.acos(0.5) - 0.5 * math.sqrt(3)
        expected = 2 * math.pi - lens
        assert total_area(res) == pytest.approx(expected, rel=2e-3)
        # curves are reconstructed from the source segments, not a polygon soup
        assert len(res[0].nodes) <= 8

    def test_circle_minus_square_mixed(self):
        res = boolean([[circle(0, 0, 1)], [square(0, -2, 4)]], "DIFFERENCE", TOL)
        assert len(res) == 1
        assert total_area(res) == pytest.approx(math.pi / 2, rel=2e-3)

    def test_three_operands(self):
        ops = [[square(0, 0, 2)], [square(1, 0, 2)], [square(0.5, 1, 2)]]
        inter = boolean(ops, "INTERSECT", TOL)
        assert total_area(inter) == pytest.approx(1.0 * 1.0)


class TestOffset:
    def test_square_outward_round(self):
        res = offset_paths([square(0, 0, 2)], 0.5, "ROUND", tol=1e-4)
        assert len(res) == 1
        assert total_area(res) == pytest.approx(4 + 4 * 2 * 0.5 + math.pi * 0.25, rel=2e-3)

    def test_square_outward_miter(self):
        res = offset_paths([square(0, 0, 2)], 0.5, "MITER", tol=1e-4)
        assert total_area(res) == pytest.approx(9.0, rel=1e-4)
        assert len(res[0].nodes) == 4

    def test_square_outward_bevel(self):
        res = offset_paths([square(0, 0, 2)], 0.5, "BEVEL", tol=1e-4)
        assert total_area(res) == pytest.approx(9.0 - 4 * 0.125, rel=1e-4)

    def test_square_inward(self):
        res = offset_paths([square(0, 0, 2)], -0.5, "MITER", tol=1e-4)
        assert total_area(res) == pytest.approx(1.0, rel=1e-4)

    def test_inward_collapses(self):
        assert offset_paths([square(0, 0, 2)], -1.5, "MITER", tol=1e-4) == []

    def test_circle_offset(self):
        res = offset_paths([circle(0, 0, 1)], 0.25, "ROUND", tol=1e-4)
        assert total_area(res) == pytest.approx(math.pi * 1.25 ** 2, rel=2e-3)
        res = offset_paths([circle(0, 0, 1)], -0.25, "ROUND", tol=1e-4)
        assert total_area(res) == pytest.approx(math.pi * 0.75 ** 2, rel=2e-3)

    def test_outline_open_line(self):
        p = Path.from_polyline([(0, 0), (4, 0)], closed=False)
        assert total_area(outline_paths([p], 1.0, cap="BUTT", tol=1e-4)) == pytest.approx(4.0, rel=1e-4)
        assert total_area(outline_paths([p], 1.0, cap="SQUARE", tol=1e-4)) == pytest.approx(5.0, rel=1e-4)
        assert total_area(outline_paths([p], 1.0, cap="ROUND", tol=1e-4)) == pytest.approx(4 + math.pi * 0.25, rel=2e-3)

    def test_outline_closed_square_is_ring(self):
        res = outline_paths([square(0, 0, 4)], 1.0, "MITER", tol=1e-4)
        assert len(res) == 2
        assert total_area(res) == pytest.approx(25 - 9, rel=1e-4)

    def test_outline_self_intersecting_zigzag(self):
        p = Path.from_polyline([(0, 0), (4, 0), (4, 4), (2, -2)], closed=False)
        res = outline_paths([p], 0.5, "ROUND", "ROUND", tol=1e-4)
        assert res and total_area(res) > 0


class TestFillet:
    def test_square_fillet_area(self):
        r = 0.5
        res = fillet_path(square(0, 0, 4), r)
        assert len(res.nodes) == 8
        assert res.area(1e-5) == pytest.approx(16 - (4 - math.pi) * r * r, rel=1e-4)

    def test_chamfer(self):
        res = fillet_path(square(0, 0, 4), 1.0, mode="CHAMFER")
        assert res.area(1e-5) == pytest.approx(16 - 4 * 0.5, rel=1e-6)

    def test_inverted(self):
        res = fillet_path(square(0, 0, 4), 1.0, mode="INVERTED")
        assert res.area(1e-5) == pytest.approx(16 - math.pi, rel=1e-3)

    def test_radius_is_clamped(self):
        res = fillet_path(square(0, 0, 2), 100.0)
        assert res.area(1e-5) == pytest.approx(math.pi, rel=1e-3)

    def test_selected_only(self):
        p = square(0, 0, 4)
        p.nodes[0].selected = True
        res = fillet_path(p, 1.0, selected_only=True)
        assert len(res.nodes) == 5

    def test_smooth_nodes_are_not_corners(self):
        assert corner_angles(circle(0, 0, 1)) == {}


class TestFit:
    def test_fit_circle_points(self):
        pts = [(math.cos(a), math.sin(a)) for a in [2 * math.pi * i / 200 for i in range(200)]]
        p = fit_polyline(pts, True, 1e-3)
        assert len(p.nodes) <= 8
        assert p.area(1e-5) == pytest.approx(math.pi, rel=2e-3)

    def test_keeps_corners(self):
        pts = [(0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (0, 2)]
        p = fit_polyline(pts, True, 1e-3)
        assert len(p.nodes) == 4
        assert p.area(1e-5) == pytest.approx(4.0)

    def test_simplify_reduces_nodes(self):
        pts = [(x / 50.0, math.sin(x / 50.0 * math.pi)) for x in range(101)]
        p = Path.from_polyline(pts, closed=False)
        s = simplify_path(p, 3e-3)
        assert len(s.nodes) <= 8
        poly = s.flatten(1e-5)
        for pt in pts[::7]:
            d = min(bz._dist_point_segment(pt, a, b) for a, b in zip(poly, poly[1:]))
            assert d < 4e-3


class TestPen:
    def test_click_and_drag(self):
        st = PenState()
        st.add((0, 0))
        st.release()
        st.add((2, 0))
        st.drag((3, 1))
        st.release()
        nodes = st.resolved()
        assert nodes[0].hr == pytest.approx((2 / 3, 0))
        assert nodes[1].hr == (3, 1)
        assert nodes[1].hl == (1, -1)
        assert nodes[1].hl_type == "ALIGNED"

    def test_cusp_drag(self):
        st = PenState()
        st.add((0, 0))
        st.release()
        st.add((2, 0))
        st.drag((3, 1), cusp=True)
        n = st.resolved()[1]
        assert n.hr_type == "FREE" and n.hl_type == "VECTOR"

    def test_constrain(self):
        assert constrain_45((0, 0), (1, 0.1))[1] == pytest.approx(0, abs=1e-12)
        x, y = constrain_45((0, 0), (1, 0.9))
        assert x == pytest.approx(y)


class TestShapes:
    def test_areas(self):
        assert shapes.rectangle(2, 3).area(1e-5) == pytest.approx(6)
        assert shapes.ellipse(2, 1).area(1e-5) == pytest.approx(2 * math.pi, rel=1e-3)
        assert shapes.polygon(4, 1).area(1e-5) == pytest.approx(2.0)
        assert shapes.star(5, 1, 0.5).area(1e-5) > 0
        assert shapes.rectangle(2, 2, 0.5).area(1e-5) == pytest.approx(4 - (4 - math.pi) * 0.25, rel=1e-4)
