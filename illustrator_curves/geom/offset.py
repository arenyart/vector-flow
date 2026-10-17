"""Offset Path and Outline Stroke.

Both are built from a Minkowski-style decomposition: every polyline edge becomes
a rectangle, every corner gets a join wedge and open ends get caps. The union of
these pieces is the stroke; offsetting a filled shape is the shape plus (or
minus) the stroke of its boundary. This is robust against the self-intersections
that plague naive edge-shifting offsets.
"""

import math

from . import bezier as bz
from .fit import fit_polyline
from .path import paths_diagonal, polygon_area, separate_touching
from .planar import _pairs_in_grid, overlay

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


def _rdp_chain(pts, tol):
    """Douglas–Peucker. Endpoints stay."""
    n = len(pts)
    if n < 3:
        return pts
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    tol2 = tol * tol
    while stack:
        i, j = stack.pop()
        ax, ay = pts[i]
        bx, by = pts[j]
        abx, aby = bx - ax, by - ay
        ll = abx * abx + aby * aby
        best, bestd = -1, tol2
        for k in range(i + 1, j):
            px, py = pts[k]
            if ll == 0.0:
                d2 = (px - ax) * (px - ax) + (py - ay) * (py - ay)
            else:
                t = ((px - ax) * abx + (py - ay) * aby) / ll
                if t < 0.0:
                    t = 0.0
                elif t > 1.0:
                    t = 1.0
                qx, qy = ax + abx * t, ay + aby * t
                d2 = (px - qx) * (px - qx) + (py - qy) * (py - qy)
            if d2 > bestd:
                bestd, best = d2, k
        if best >= 0:
            keep[best] = True
            stack.append((i, best))
            stack.append((best, j))
    return [p for p, flag in zip(pts, keep) if flag]


def _decimate_ring(pts, tol):
    """Drop points a closed ring can spare without moving more than ``tol``."""
    n = len(pts)
    if n < 16 or tol <= 0:
        return pts
    i0 = min(range(n), key=lambda i: (pts[i][0], pts[i][1]))
    i1 = max(range(n), key=lambda i: (pts[i][0], pts[i][1]))
    if i0 == i1:
        return pts

    def chain(a, b):
        if a <= b:
            return pts[a:b + 1]
        return pts[a:] + pts[:b + 1]

    left = _rdp_chain(chain(i0, i1), tol)
    right = _rdp_chain(chain(i1, i0), tol)
    return left[:-1] + right[:-1]


def _fit_loops(loops, fit_error, corner_angle, fit):
    from .path import Path

    out = []
    for loop in loops:
        pts = [e[0] for e in loop]
        if fit and len(pts) >= 16:
            pts = _decimate_ring(pts, fit_error * 0.5)
        if fit:
            p = fit_polyline(pts, True, fit_error, corner_angle)
        else:
            p = Path.from_polyline(pts, True)
        if p is not None and p.nodes:
            out.append(p)
    return separate_touching(out, max(paths_diagonal(out), 1e-9) * 1e-5)


def _crosses(a, b, eps):
    """True when segment ``a`` meets the interior of ``b`` or they properly cross."""
    ax, ay, bx, by = a
    rx, ry = bx - ax, by - ay
    rr = rx * rx + ry * ry
    if rr == 0.0:
        return False
    lr = math.sqrt(rr)
    et = eps / lr
    cx, cy, dx, dy = b
    sx, sy = dx - cx, dy - cy
    ss = sx * sx + sy * sy
    if ss == 0.0:
        return False
    ls = math.sqrt(ss)
    eu = eps / ls
    for px, py in ((cx, cy), (dx, dy)):
        t = ((px - ax) * rx + (py - ay) * ry) / rr
        if et < t < 1.0 - et and abs((px - ax) * ry - (py - ay) * rx) <= eps * lr:
            return True
    for px, py in ((ax, ay), (bx, by)):
        u = ((px - cx) * sx + (py - cy) * sy) / ss
        if eu < u < 1.0 - eu and abs((px - cx) * sy - (py - cy) * sx) <= eps * ls:
            return True
    den = rx * sy - ry * sx
    if abs(den) <= 1e-12 * lr * ls:
        return False
    qx, qy = cx - ax, cy - ay
    t = (qx * sy - qy * sx) / den
    u = (qx * ry - qy * rx) / den
    return et < t < 1.0 - et and eu < u < 1.0 - eu


def _self_intersects(pts, closed=True):
    n = len(pts)
    m = n if closed else n - 1
    if m < 4:
        return False
    edges = []
    xs = []
    ys = []
    for i in range(m):
        a = pts[i]
        b = pts[(i + 1) % n]
        edges.append((a[0], a[1], b[0], b[1]))
        xs.append(a[0])
        ys.append(a[1])
    scale = max(max(xs) - min(xs), max(ys) - min(ys), 1e-9)
    eps = scale * 1e-9

    def adjacent(i, j):
        d = abs(i - j)
        return d <= 1 or (closed and d == m - 1)

    pairs = ((i, j) for i in range(m) for j in range(i + 1, m)) if m < 80 else _pairs_in_grid(edges, eps)
    for i, j in pairs:
        if not adjacent(i, j) and _crosses(edges[i], edges[j], eps):
            return True
    return False


def _line_hit(p, d, q, e):
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-14:
        return None
    qx, qy = q[0] - p[0], q[1] - p[1]
    t = (qx * e[1] - qy * e[0]) / den
    return (p[0] + d[0] * t, p[1] + d[1] * t)


def _gap_points(v, p1, p2, radius, join, miter_limit, tol):
    """Points bridging the gap between two offset edges, from ``p1`` through to ``p2``."""
    if radius <= 0:
        return [p1]
    n1 = ((p1[0] - v[0]) / radius, (p1[1] - v[1]) / radius)
    n2 = ((p2[0] - v[0]) / radius, (p2[1] - v[1]) / radius)
    if join == MITER:
        sx, sy = n1[0] + n2[0], n1[1] + n2[1]
        sl = math.hypot(sx, sy)
        cos_half = sl / 2.0
        if cos_half > 1e-9 and 1.0 / cos_half <= miter_limit:
            m = radius / cos_half
            return [(v[0] + sx / sl * m, v[1] + sy / sl * m)]
        return [p1, p2]
    if join != ROUND:
        return [p1, p2]
    cross = n1[0] * n2[1] - n1[1] * n2[0]
    dot = n1[0] * n2[0] + n1[1] * n2[1]
    sweep = math.atan2(cross, dot)
    if abs(abs(sweep) - math.pi) < 1e-9:
        sweep = math.pi if cross >= 0 else -math.pi
    # A corner smoother than the tolerance does not need an arc. One bisector
    # point keeps the outline a clean polygon instead of a sawtooth.
    if radius * (1.0 - math.cos(abs(sweep) * 0.5)) <= tol:
        sx, sy = n1[0] + n2[0], n1[1] + n2[1]
        sl = math.hypot(sx, sy)
        if sl <= 1e-9:
            return [p1]
        m = radius / (sl * 0.5)
        return [(v[0] + sx / sl * m, v[1] + sy / sl * m)]
    steps = max(1, int(math.ceil(abs(sweep) / _arc_step(radius, tol))))
    a0 = math.atan2(n1[1], n1[0])
    pts = [p1]
    for k in range(1, steps):
        ang = a0 + sweep * k / steps
        pts.append((v[0] + radius * math.cos(ang), v[1] + radius * math.sin(ang)))
    pts.append(p2)
    return pts


def _parallel_closed(pts, shift, join, miter_limit, tol):
    """Parallel curve of a simple closed loop. ``shift`` > 0 moves edges to their left."""
    n = len(pts)
    dirs = []
    ends = []
    for i in range(n):
        a = pts[i]
        b = pts[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1e-15:
            return None
        ux, uy = dx / length, dy / length
        ox, oy = -uy * shift, ux * shift
        dirs.append((ux, uy))
        ends.append(((a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)))
    out = []
    radius = abs(shift)
    for i in range(n):
        d1 = dirs[i - 1]
        d2 = dirs[i]
        p1 = ends[i - 1][1]
        p2 = ends[i][0]
        cr = d1[0] * d2[1] - d1[1] * d2[0]
        dt = d1[0] * d2[0] + d1[1] * d2[1]
        if abs(cr) < 1e-12 and dt > 0:
            out.append(p1)
            continue
        if cr * shift < 0:
            out.extend(_gap_points(pts[i], p1, p2, radius, join, miter_limit, tol))
        else:
            hit = _line_hit(p1, d1, p2, d2)
            out.append(hit if hit is not None else p1)
    return _dedupe(out, True, max(radius * 1e-9, 1e-15))


def _parallel_open(pts, shift, join, miter_limit, tol):
    """Offset an open polyline to its left. ``shift`` > 0 moves edges left."""
    n = len(pts)
    if n < 2:
        return None
    dirs = []
    ends = []
    for i in range(n - 1):
        a, b = pts[i], pts[i + 1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1e-15:
            return None
        ux, uy = dx / length, dy / length
        ox, oy = -uy * shift, ux * shift
        dirs.append((ux, uy))
        ends.append(((a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy)))
    out = [ends[0][0]]
    radius = abs(shift)
    for i in range(1, n - 1):
        d1, d2 = dirs[i - 1], dirs[i]
        p1, p2 = ends[i - 1][1], ends[i][0]
        cr = d1[0] * d2[1] - d1[1] * d2[0]
        dt = d1[0] * d2[0] + d1[1] * d2[1]
        if abs(cr) < 1e-12 and dt > 0:
            out.append(p1)
            continue
        if cr * shift < 0:
            out.extend(_gap_points(pts[i], p1, p2, radius, join, miter_limit, tol))
        else:
            hit = _line_hit(p1, d1, p2, d2)
            out.append(hit if hit is not None else p1)
    out.append(ends[-1][1])
    return _dedupe(out, False, max(radius * 1e-9, 1e-15))


def _cap_points(center, direction, hw, cap, tol, bulge):
    """Points between the left and right sides of a cap, excluding the sides themselves.

    ``bulge`` is +1 at the end of the path and -1 at the start.
    """
    dx, dy = direction
    nx, ny = -dy, dx
    if cap == BUTT:
        return []
    if cap == SQUARE:
        bx, by = dx * bulge * hw, dy * bulge * hw
        return [(center[0] + nx * hw + bx, center[1] + ny * hw + by),
                (center[0] - nx * hw + bx, center[1] - ny * hw + by)]
    # Semicircle from the left side (end) or the right side (start) through the bulge.
    if bulge < 0:
        nx, ny = -nx, -ny
    a0 = math.atan2(ny, nx)
    steps = max(2, int(math.ceil(math.pi / _arc_step(hw, tol))))
    pts = []
    for k in range(1, steps):
        ang = a0 - math.pi * k / steps
        pts.append((center[0] + hw * math.cos(ang), center[1] + hw * math.sin(ang)))
    return pts


def _stroke_ring(pts, hw, join, cap, miter_limit, tol):
    """Filled outline of one open polyline, or None if it cannot be built directly."""
    left = _parallel_open(pts, hw, join, miter_limit, tol)
    right = _parallel_open(pts, -hw, join, miter_limit, tol)
    if not left or not right or len(left) < 2 or len(right) < 2:
        return None

    def direc(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        return (dx / length, dy / length)

    ring = (left + _cap_points(pts[-1], direc(pts[-2], pts[-1]), hw, cap, tol, 1)
            + right[::-1] + _cap_points(pts[0], direc(pts[0], pts[1]), hw, cap, tol, -1))
    ring = _dedupe(ring, True, max(hw * 1e-9, 1e-15))
    if ring and polygon_area(ring) < 0:
        ring.reverse()
    return ring


def _is_convex(pts):
    sign = 0
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        cx, cy = pts[(i + 1) % n]
        cr = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cr) <= 1e-12:
            continue
        s = 1 if cr > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def _inside(pts, x, y):
    c = False
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xin = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < xin:
                c = not c
    return c


def _inset_collapsed(src, result, area, distance, tol):
    """True when an inward offset of a convex loop has crossed through itself."""
    depth = abs(distance) * 0.5
    if depth <= tol:
        return False
    n = len(src)
    best_i, best_l = 0, -1.0
    for i in range(n):
        a = src[i]
        b = src[(i + 1) % n]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length > best_l:
            best_i, best_l = i, length
    if best_l <= 1e-15:
        return True
    a = src[best_i]
    b = src[(best_i + 1) % n]
    ux, uy = (b[0] - a[0]) / best_l, (b[1] - a[1]) / best_l
    lx, ly = -uy, ux
    if area < 0:
        lx, ly = -lx, -ly
    px = (a[0] + b[0]) * 0.5 + lx * depth
    py = (a[1] + b[1]) * 0.5 + ly * depth
    if not _inside(src, px, py):
        return True
    return _inside(result, px, py)


def _try_fast_offset(paths, distance, join, miter_limit, tol, fit, fit_error, corner_angle):
    """Parallel-curve offset for one simple loop. ``None`` means the robust union is required."""
    closed = []
    for p in paths:
        if len(p.nodes) < 2:
            continue
        if not p.closed:
            return None
        closed.append(p)
    if len(closed) != 1:
        return None
    pts = _dedupe(closed[0].flatten(tol), True, 1e-12)
    if len(pts) < 3:
        return None
    convex = _is_convex(pts)
    if not convex and _self_intersects(pts):
        return None
    area = polygon_area(pts)
    if abs(area) <= 1e-16:
        return None
    # Positive area is counter-clockwise, so the material is on the left and an
    # outward offset (distance > 0) steps to the right.
    loop = _parallel_closed(pts, -math.copysign(1.0, area) * distance, join, miter_limit, tol)
    if not loop or len(loop) < 3:
        return None
    if not convex and _self_intersects(loop):
        return None
    if polygon_area(loop) * area <= 0:
        return []
    if convex:
        if distance < 0 and _inset_collapsed(pts, loop, area, distance, tol):
            return []
    else:
        # A loop that crossed through the shape comes back simple, but its edges
        # no longer sit at the requested distance.
        target = abs(distance)
        limit = max(tol * 8.0, target * 1e-3)
        bad = 0
        m = len(loop)
        for i in range(m):
            a = loop[i]
            b = loop[(i + 1) % m]
            mid = ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
            if abs(_boundary_distance(pts, mid) - target) > limit:
                bad += 1
        if bad == m:
            return []
        if bad:
            return None
    return _fit_loops([[(pt, pt, None) for pt in loop]], fit_error, corner_angle, fit)


def _boundary_distance(pts, p):
    best = math.inf
    n = len(pts)
    for i in range(n):
        d = bz._dist_point_segment(p, pts[i], pts[(i + 1) % n])
        if d < best:
            best = d
    return best


def _offset_via_overlay(paths, distance, join, miter_limit, tol, fit, fit_error, corner_angle):
    hw = abs(distance)
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


def _try_fast_stroke(paths, hw, join, cap, miter_limit, tol, fit, fit_error, corner_angle):
    """Direct outline of one open path. ``None`` if the stroke folds over itself."""
    chosen = []
    for p in paths:
        if len(p.nodes) < 2:
            continue
        if p.closed:
            return None
        chosen.append(p)
    if len(chosen) != 1:
        return None
    pts = _dedupe(chosen[0].flatten(tol), False, 1e-12)
    if len(pts) < 2 or (len(pts) >= 4 and _self_intersects(pts, closed=False)):
        return None
    ring = _stroke_ring(pts, hw, join, cap, miter_limit, tol)
    if not ring or len(ring) < 3 or _self_intersects(ring):
        return None
    return _fit_loops([[(pt, pt, None) for pt in ring]], fit_error, corner_angle, fit)


def offset_paths(paths, distance, join=ROUND, miter_limit=4.0, tol=1e-3, fit=True,
                 fit_error=None, corner_angle=math.radians(30.0)):
    """Offset filled shapes outward (distance > 0) or inward (distance < 0).

    Closed paths form one even-odd filled shape. Open paths are outlined with
    round caps for positive distances and ignored for negative ones.
    """
    if distance == 0:
        return [p.copy() for p in paths]
    fit_error = fit_error if fit_error is not None else tol
    fast = _try_fast_offset(paths, distance, join, miter_limit, tol, fit, fit_error, corner_angle)
    if fast is not None:
        return fast
    if distance > 0:
        stroked = _try_fast_stroke(paths, abs(distance), join, ROUND, miter_limit, tol, fit,
                                   fit_error, corner_angle)
        if stroked is not None:
            return stroked
    return _offset_via_overlay(paths, distance, join, miter_limit, tol, fit, fit_error, corner_angle)


def outline_paths(paths, width, join=ROUND, cap=BUTT, miter_limit=4.0, tol=1e-3, fit=True,
                  fit_error=None, corner_angle=math.radians(30.0)):
    """Convert strokes of the given width into filled outlines (Illustrator's Outline Stroke)."""
    hw = abs(width) * 0.5
    if hw <= 0:
        return []
    fit_error = fit_error if fit_error is not None else tol
    stroked = _try_fast_stroke(paths, hw, join, cap, miter_limit, tol, fit, fit_error, corner_angle)
    if stroked is not None:
        return stroked
    pieces = []
    for p in paths:
        if len(p.nodes) < 2 and not p.closed:
            continue
        pieces.extend(stroke_pieces(p.flatten(tol), p.closed, hw, join, cap, miter_limit, tol))
    loops = [(0, pc, None) for pc in pieces]
    return _fit_loops(overlay(loops, 1, lambda w: w[0] > 0), fit_error, corner_angle, fit)
