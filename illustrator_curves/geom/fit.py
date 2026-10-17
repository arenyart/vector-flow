"""Least-squares cubic Bezier fitting of polylines (Schneider's algorithm)."""

import math

from . import bezier as bz
from .path import Path


def _norm(v):
    l = math.hypot(v[0], v[1])
    if l < 1e-15:
        return (0.0, 0.0)
    return (v[0] / l, v[1] / l)


def _turn(a, b, c):
    ux, uy = b[0] - a[0], b[1] - a[1]
    vx, vy = c[0] - b[0], c[1] - b[1]
    return abs(math.atan2(ux * vy - uy * vx, ux * vx + uy * vy))


def clean_polyline(pts, closed, eps):
    """Drop duplicate points and points that lie on the chord of their neighbours."""
    out = []
    for p in pts:
        if not out or bz.dist(out[-1], p) > eps:
            out.append(p)
    if closed and len(out) > 1 and bz.dist(out[0], out[-1]) <= eps:
        out.pop()
    changed = True
    while changed and len(out) > 3:
        changed = False
        res = []
        n = len(out)
        for i in range(n):
            if not closed and (i == 0 or i == n - 1):
                res.append(out[i])
                continue
            a = res[-1] if res else out[i - 1]
            c = out[(i + 1) % n]
            b = out[i]
            if bz._dist_point_segment(b, a, c) <= eps and bz.dist(a, c) > eps:
                ux, uy = b[0] - a[0], b[1] - a[1]
                vx, vy = c[0] - b[0], c[1] - b[1]
                if ux * vx + uy * vy >= 0:
                    changed = True
                    continue
            res.append(b)
        out = res
    return out


def _chord_params(pts, first, last):
    u = [0.0]
    for i in range(first + 1, last + 1):
        u.append(u[-1] + bz.dist(pts[i - 1], pts[i]))
    total = u[-1]
    if total <= 0:
        m = last - first
        return [i / m for i in range(m + 1)]
    return [x / total for x in u]


def _generate(pts, first, last, u, t1, t2):
    p0, p3 = pts[first], pts[last]
    c00 = c01 = c11 = x0 = x1 = 0.0
    for k, i in enumerate(range(first, last + 1)):
        t = u[k]
        mt = 1.0 - t
        b0 = mt * mt * mt
        b1 = 3 * mt * mt * t
        b2 = 3 * mt * t * t
        b3 = t * t * t
        a1 = (t1[0] * b1, t1[1] * b1)
        a2 = (t2[0] * b2, t2[1] * b2)
        c00 += a1[0] * a1[0] + a1[1] * a1[1]
        c01 += a1[0] * a2[0] + a1[1] * a2[1]
        c11 += a2[0] * a2[0] + a2[1] * a2[1]
        tx = pts[i][0] - (p0[0] * (b0 + b1) + p3[0] * (b2 + b3))
        ty = pts[i][1] - (p0[1] * (b0 + b1) + p3[1] * (b2 + b3))
        x0 += a1[0] * tx + a1[1] * ty
        x1 += a2[0] * tx + a2[1] * ty
    det = c00 * c11 - c01 * c01
    seg_len = bz.dist(p0, p3)
    al = ar = 0.0
    if abs(det) > 1e-18:
        al = (x0 * c11 - x1 * c01) / det
        ar = (c00 * x1 - c01 * x0) / det
    e = 1e-6 * seg_len
    if al < e or ar < e or al > 3 * seg_len or ar > 3 * seg_len:
        al = ar = seg_len / 3.0
    return (p0, (p0[0] + t1[0] * al, p0[1] + t1[1] * al), (p3[0] + t2[0] * ar, p3[1] + t2[1] * ar), p3)


def _max_error(pts, first, last, seg, u):
    maxd, split = 0.0, (first + last) // 2
    for k, i in enumerate(range(first, last + 1)):
        if k == 0 or i == last:
            continue
        d = bz.dist(bz.point(seg, u[k]), pts[i])
        if d > maxd:
            maxd, split = d, i
    return maxd, split


def _reparam(pts, first, last, u, seg):
    res = []
    for k, i in enumerate(range(first, last + 1)):
        t = u[k]
        p = bz.point(seg, t)
        d1 = bz.deriv(seg, t)
        d2 = bz.deriv2(seg, t)
        dx, dy = p[0] - pts[i][0], p[1] - pts[i][1]
        num = dx * d1[0] + dy * d1[1]
        den = d1[0] * d1[0] + d1[1] * d1[1] + dx * d2[0] + dy * d2[1]
        if abs(den) > 1e-18:
            t = t - num / den
        res.append(min(1.0, max(0.0, t)))
    return res


def fit_cubic(pts, t1, t2, error):
    """Fit Bezier segments through ``pts`` with end tangents ``t1``/``t2`` (pointing inward)."""
    out = []
    stack = [(0, len(pts) - 1, t1, t2)]
    while stack:
        first, last, th1, th2 = stack.pop()
        if last <= first:
            continue
        if last - first == 1:
            d = bz.dist(pts[first], pts[last]) / 3.0
            p0, p3 = pts[first], pts[last]
            out.append((p0, (p0[0] + th1[0] * d, p0[1] + th1[1] * d), (p3[0] + th2[0] * d, p3[1] + th2[1] * d), p3))
            continue
        u = _chord_params(pts, first, last)
        seg = _generate(pts, first, last, u, th1, th2)
        maxe, split = _max_error(pts, first, last, seg, u)
        if maxe < error:
            out.append(seg)
            continue
        if maxe <= 100.0 * error:
            best = (maxe, split, seg)
            for _ in range(20):
                u = _reparam(pts, first, last, u, seg)
                seg = _generate(pts, first, last, u, th1, th2)
                maxe, split = _max_error(pts, first, last, seg, u)
                if maxe < best[0] * 0.999:
                    best = (maxe, split, seg)
                elif maxe >= best[0]:
                    break
                if maxe < error:
                    break
            maxe, split, seg = best
            if maxe < error:
                out.append(seg)
                continue
        if maxe > 4.0 * error:
            # far from fitting: a balanced split recovers better than the worst-point split
            half = 0.5 * u[-1]
            split = first + min(range(len(u)), key=lambda k: abs(u[k] - half))
        split = min(max(split, first + 1), last - 1)
        tc = _norm((pts[split - 1][0] - pts[split + 1][0], pts[split - 1][1] - pts[split + 1][1]))
        if tc == (0.0, 0.0):
            tc = _norm((pts[split - 1][0] - pts[split][0], pts[split - 1][1] - pts[split][1]))
        stack.append((split, last, (-tc[0], -tc[1]), th2))
        stack.append((first, split, th1, tc))
    return out


def _end_tangent(p0, p1, p2):
    """Second-order one-sided tangent estimate at ``p0`` (pointing towards ``p1``)."""
    h1 = bz.dist(p0, p1)
    h2 = bz.dist(p1, p2)
    t = _norm((p1[0] - p0[0], p1[1] - p0[1]))
    if h1 <= 0 or h2 <= 0 or _turn(p0, p1, p2) > math.radians(20.0):
        return t
    a = -(2 * h1 + h2) / (h1 * (h1 + h2))
    b = (h1 + h2) / (h1 * h2)
    c = -h1 / (h2 * (h1 + h2))
    d = _norm((a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]))
    return d if d[0] * t[0] + d[1] * t[1] > 0.5 else t


def _piece_segments(piece, error):
    if len(piece) == 2:
        return [bz.line(piece[0], piece[1])]
    t1 = _end_tangent(piece[0], piece[1], piece[2])
    t2 = _end_tangent(piece[-1], piece[-2], piece[-3])
    return fit_cubic(piece, t1, t2, error)


def fit_polyline(points, closed, error, corner_angle=math.radians(35.0)):
    """Fit a :class:`Path` to a polyline, keeping sharp corners above ``corner_angle``."""
    pts = clean_polyline(list(points), closed, error * 0.02)
    n = len(pts)
    if n < 2 or (closed and n < 3):
        return None
    if closed:
        corners = [i for i in range(n) if _turn(pts[i - 1], pts[i], pts[(i + 1) % n]) > corner_angle]
        if not corners:
            seq = pts + [pts[0]]
            t = _norm((pts[1][0] - pts[-1][0], pts[1][1] - pts[-1][1]))
            segs = fit_cubic(seq, t, (-t[0], -t[1]), error)
            return Path.from_segments(segs, closed=True)
        s = corners[0]
        rot = pts[s:] + pts[:s]
        cidx = sorted(((c - s) % n) for c in corners) + [n]
        rot.append(rot[0])
        segs = []
        for a, b in zip(cidx[:-1], cidx[1:]):
            segs.extend(_piece_segments(rot[a:b + 1], error))
        return Path.from_segments(segs, closed=True)
    corners = [i for i in range(1, n - 1) if _turn(pts[i - 1], pts[i], pts[i + 1]) > corner_angle]
    cidx = [0] + corners + [n - 1]
    segs = []
    for a, b in zip(cidx[:-1], cidx[1:]):
        segs.extend(_piece_segments(pts[a:b + 1], error))
    return Path.from_segments(segs, closed=False)


def simplify_path(path, error, corner_angle=math.radians(35.0), flatten_tol=None):
    """Re-fit a path with fewer control points (Illustrator's Simplify)."""
    if len(path.nodes) < 2:
        return path.copy()
    tol = flatten_tol if flatten_tol is not None else error * 0.1
    pts = path.flatten(tol)
    res = fit_polyline(pts, path.closed, error, corner_angle)
    if res is None:
        return path.copy()
    res.meta = dict(path.meta)
    return res
