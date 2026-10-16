"""Offset Path and Outline Stroke.

Both are built from a Minkowski-style decomposition: every polyline edge becomes
a rectangle, every corner gets a join wedge and open ends get caps. The union of
these pieces is the stroke; offsetting a filled shape is the shape plus (or
minus) the stroke of its boundary. This is robust against the self-intersections
that plague naive edge-shifting offsets.
"""

import math

from .fit import fit_polyline
from .path import polygon_area
from .planar import overlay

MITER = "MITER"
ROUND = "ROUND"
BEVEL = "BEVEL"
BUTT = "BUTT"
SQUARE = "SQUARE"


def _arc_step(radius, tol):
    if radius <= tol:
        return math.radians(30.0)
    step = 2.0 * math.acos(max(-1.0, 1.0 - tol / radius))
    return min(max(step, math.radians(2.0)), math.radians(12.0))


def _ccw(poly):
    if polygon_area(poly) < 0:
        poly.reverse()
    return poly


def _circle(c, r, tol):
    n = max(8, int(math.ceil(2.0 * math.pi / _arc_step(r, tol))))
    return [(c[0] + r * math.cos(2.0 * math.pi * i / n), c[1] + r * math.sin(2.0 * math.pi * i / n)) for i in range(n)]


def _dedupe(pts, closed, eps):
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > eps:
            out.append(p)
    if closed and len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= eps:
        out.pop()
    return out


def _join(v, d1, d2, hw, join, miter_limit, tol):
    cr = d1[0] * d2[1] - d1[1] * d2[0]
    dt = d1[0] * d2[0] + d1[1] * d2[1]
    if abs(cr) < 1e-12 and dt > 0:
        return None
    if cr > 0:
        n1, n2 = (d1[1], -d1[0]), (d2[1], -d2[0])
    else:
        n1, n2 = (-d1[1], d1[0]), (-d2[1], d2[0])
    a = (v[0] + n1[0] * hw, v[1] + n1[1] * hw)
    b = (v[0] + n2[0] * hw, v[1] + n2[1] * hw)
    if join == ROUND:
        a0 = math.atan2(n1[1], n1[0])
        sweep = math.atan2(n1[0] * n2[1] - n1[1] * n2[0], n1[0] * n2[0] + n1[1] * n2[1])
        if abs(abs(sweep) - math.pi) < 1e-9:
            # reversal: sweep around the forward direction
            sweep = math.pi if cr > 0 else -math.pi
        steps = max(1, int(math.ceil(abs(sweep) / _arc_step(hw, tol))))
        poly = [v, a]
        for k in range(1, steps):
            ang = a0 + sweep * k / steps
            poly.append((v[0] + hw * math.cos(ang), v[1] + hw * math.sin(ang)))
        poly.append(b)
    elif join == MITER:
        sx, sy = n1[0] + n2[0], n1[1] + n2[1]
        sl = math.hypot(sx, sy)
        cos_half = sl / 2.0
        if cos_half > 1e-9 and 1.0 / cos_half <= miter_limit:
            m = hw / cos_half
            poly = [v, a, (v[0] + sx / sl * m, v[1] + sy / sl * m), b]
        else:
            poly = [v, a, b]
    else:
        poly = [v, a, b]
    if abs(polygon_area(poly)) <= (hw * 1e-9) ** 2:
        return None
    return _ccw(poly)


def stroke_pieces(pts, closed, half_width, join=ROUND, cap=BUTT, miter_limit=4.0, tol=1e-3):
    """Convex pieces (CCW) whose union is the stroke of a polyline."""
    hw = float(half_width)
    pts = _dedupe(pts, closed, hw * 1e-9 + 1e-15)
    n = len(pts)
    if n < 2 or hw <= 0:
        return []
    if closed and n < 3:
        closed = False
    pieces = []
    dirs = []
    m = n if closed else n - 1
    for i in range(m):
        a = pts[i]
        b = pts[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        l = math.hypot(dx, dy)
        u = (dx / l, dy / l)
        nx, ny = -u[1] * hw, u[0] * hw
        pieces.append([(a[0] - nx, a[1] - ny), (b[0] - nx, b[1] - ny), (b[0] + nx, b[1] + ny), (a[0] + nx, a[1] + ny)])
        dirs.append(u)
    if closed:
        verts = [(pts[i], dirs[i - 1], dirs[i]) for i in range(n)]
    else:
        verts = [(pts[i], dirs[i - 1], dirs[i]) for i in range(1, n - 1)]
    for v, d1, d2 in verts:
        wedge = _join(v, d1, d2, hw, join, miter_limit, tol)
        if wedge:
            pieces.append(wedge)
    if not closed:
        for p, d, sgn in ((pts[0], dirs[0], -1.0), (pts[-1], dirs[-1], 1.0)):
            if cap == ROUND:
                pieces.append(_circle(p, hw, tol))
            elif cap == SQUARE:
                nx, ny = -d[1] * hw, d[0] * hw
                ex, ey = p[0] + sgn * d[0] * hw, p[1] + sgn * d[1] * hw
                pieces.append(_ccw([(p[0] - nx, p[1] - ny), (ex - nx, ey - ny), (ex + nx, ey + ny), (p[0] + nx, p[1] + ny)]))
    return pieces


def _fit_loops(loops, fit_error, corner_angle, fit):
    from .path import Path

    out = []
    for loop in loops:
        pts = [e[0] for e in loop]
        if fit:
            p = fit_polyline(pts, True, fit_error, corner_angle)
        else:
            p = Path.from_polyline(pts, True)
        if p is not None and p.nodes:
            out.append(p)
    return out


def offset_paths(paths, distance, join=ROUND, miter_limit=4.0, tol=1e-3, fit=True,
                 fit_error=None, corner_angle=math.radians(30.0)):
    """Offset filled shapes outward (distance > 0) or inward (distance < 0).

    Closed paths form one even-odd filled shape. Open paths are outlined with
    round caps for positive distances and ignored for negative ones.
    """
    if distance == 0:
        return [p.copy() for p in paths]
    hw = abs(distance)
    fit_error = fit_error if fit_error is not None else tol
    loops = []
    pieces = []
    for p in paths:
        if len(p.nodes) < 2:
            continue
        if p.closed:
            pts = p.flatten(tol)
            if len(pts) >= 3:
                loops.append((0, pts, None))
                pieces.extend(stroke_pieces(pts, True, hw, join, BUTT, miter_limit, tol))
        elif distance > 0:
            pieces.extend(stroke_pieces(p.flatten(tol), False, hw, join, ROUND, miter_limit, tol))
    loops.extend((1, pc, None) for pc in pieces)
    if distance > 0:
        pred = lambda w: (w[0] % 2 != 0) or w[1] > 0
    else:
        pred = lambda w: (w[0] % 2 != 0) and not w[1] > 0
    return _fit_loops(overlay(loops, 2, pred), fit_error, corner_angle, fit)


def outline_paths(paths, width, join=ROUND, cap=BUTT, miter_limit=4.0, tol=1e-3, fit=True,
                  fit_error=None, corner_angle=math.radians(30.0)):
    """Convert strokes of the given width into filled outlines (Illustrator's Outline Stroke)."""
    hw = abs(width) * 0.5
    if hw <= 0:
        return []
    fit_error = fit_error if fit_error is not None else tol
    pieces = []
    for p in paths:
        if len(p.nodes) < 2 and not p.closed:
            continue
        pieces.extend(stroke_pieces(p.flatten(tol), p.closed, hw, join, cap, miter_limit, tol))
    loops = [(0, pc, None) for pc in pieces]
    return _fit_loops(overlay(loops, 1, lambda w: w[0] > 0), fit_error, corner_angle, fit)
