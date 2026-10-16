"""Cubic Bezier helpers operating on plain 2D tuples.

A segment is a 4-tuple of points ``(p0, p1, p2, p3)``; a point is ``(x, y)``.
"""

import math

_GL_X = (-0.9061798459386640, -0.5384693101056831, 0.0, 0.5384693101056831, 0.9061798459386640)
_GL_W = (0.2369268850561891, 0.4786286704993665, 0.5688888888888889, 0.4786286704993665, 0.2369268850561891)


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def line(a, b):
    """A straight segment expressed as a cubic (handles at 1/3 and 2/3)."""
    return (a, lerp(a, b, 1.0 / 3.0), lerp(a, b, 2.0 / 3.0), b)


def point(seg, t):
    p0, p1, p2, p3 = seg
    mt = 1.0 - t
    a = mt * mt * mt
    b = 3.0 * mt * mt * t
    c = 3.0 * mt * t * t
    d = t * t * t
    return (a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
            a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])


def deriv(seg, t):
    p0, p1, p2, p3 = seg
    mt = 1.0 - t
    a = 3.0 * mt * mt
    b = 6.0 * mt * t
    c = 3.0 * t * t
    return (a * (p1[0] - p0[0]) + b * (p2[0] - p1[0]) + c * (p3[0] - p2[0]),
            a * (p1[1] - p0[1]) + b * (p2[1] - p1[1]) + c * (p3[1] - p2[1]))


def deriv2(seg, t):
    p0, p1, p2, p3 = seg
    mt = 1.0 - t
    return (6.0 * mt * (p2[0] - 2 * p1[0] + p0[0]) + 6.0 * t * (p3[0] - 2 * p2[0] + p1[0]),
            6.0 * mt * (p2[1] - 2 * p1[1] + p0[1]) + 6.0 * t * (p3[1] - 2 * p2[1] + p1[1]))


def split(seg, t):
    p0, p1, p2, p3 = seg
    a = lerp(p0, p1, t)
    b = lerp(p1, p2, t)
    c = lerp(p2, p3, t)
    d = lerp(a, b, t)
    e = lerp(b, c, t)
    f = lerp(d, e, t)
    return (p0, a, d, f), (f, e, c, p3)


def reverse(seg):
    return (seg[3], seg[2], seg[1], seg[0])


def sub(seg, t0, t1):
    """The part of ``seg`` between parameters ``t0`` and ``t1`` (reversed if t0 > t1)."""
    if t0 > t1:
        return reverse(sub(seg, t1, t0))
    if t0 <= 0.0 and t1 >= 1.0:
        return seg
    if t0 > 0.0:
        if t0 >= 1.0:
            p = seg[3]
            return (p, p, p, p)
        seg = split(seg, t0)[1]
        t1 = (t1 - t0) / (1.0 - t0)
    if t1 < 1.0:
        seg = split(seg, t1)[0]
    return seg


def _dist_point_segment(p, a, b):
    abx, aby = b[0] - a[0], b[1] - a[1]
    ll = abx * abx + aby * aby
    if ll <= 0.0:
        return dist(p, a)
    t = ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / ll
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(p[0] - (a[0] + abx * t), p[1] - (a[1] + aby * t))


def flatness(seg):
    """Upper bound on the distance between the curve and its chord."""
    p0, p1, p2, p3 = seg
    return max(_dist_point_segment(p1, p0, p3), _dist_point_segment(p2, p0, p3))


def is_line(seg, eps=1e-9):
    scale = max(dist(seg[0], seg[3]), 1e-12)
    return flatness(seg) <= eps * max(scale, 1.0)


def flatten_ts(seg, tol, max_depth=16):
    """Parameters at which the segment can be approximated by straight chords."""
    if flatness(seg) <= tol * 1e-3:
        return [0.0, 1.0]
    ts = [0.0]
    stack = [(0.0, 1.0, seg, 0)]
    while stack:
        t0, t1, s, depth = stack.pop()
        if depth >= max_depth or (depth >= 1 and flatness(s) <= tol):
            ts.append(t1)
            continue
        left, right = split(s, 0.5)
        tm = 0.5 * (t0 + t1)
        stack.append((tm, t1, right, depth + 1))
        stack.append((t0, tm, left, depth + 1))
    return ts


def _speed(seg, t):
    d = deriv(seg, t)
    return math.hypot(d[0], d[1])


def length(seg, t0=0.0, t1=1.0, pieces=8):
    if t1 <= t0:
        return 0.0
    total = 0.0
    h = (t1 - t0) / pieces
    for k in range(pieces):
        a = t0 + k * h
        mid = a + 0.5 * h
        for x, w in zip(_GL_X, _GL_W):
            total += w * _speed(seg, mid + 0.5 * h * x)
    return total * 0.5 * h


def t_at_length(seg, s):
    """Parameter where the arc length measured from t=0 equals ``s``."""
    total = length(seg)
    if s <= 0.0 or total <= 0.0:
        return 0.0
    if s >= total:
        return 1.0
    lo, hi = 0.0, 1.0
    t = s / total
    for _ in range(50):
        f = length(seg, 0.0, t) - s
        if abs(f) < total * 1e-10:
            break
        if f > 0:
            hi = t
        else:
            lo = t
        sp = _speed(seg, t)
        nt = t - f / sp if sp > 1e-12 else 0.5 * (lo + hi)
        t = nt if lo < nt < hi else 0.5 * (lo + hi)
    return t


def tangent_start(seg):
    p0 = seg[0]
    for q in (seg[1], seg[2], seg[3]):
        dx, dy = q[0] - p0[0], q[1] - p0[1]
        if dx * dx + dy * dy > 1e-24:
            return dx, dy
    return 0.0, 0.0


def tangent_end(seg):
    p3 = seg[3]
    for q in (seg[2], seg[1], seg[0]):
        dx, dy = p3[0] - q[0], p3[1] - q[1]
        if dx * dx + dy * dy > 1e-24:
            return dx, dy
    return 0.0, 0.0
