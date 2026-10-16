"""Round or chamfer the corners of a path."""

import math

from . import bezier as bz
from .path import Path

ROUND = "ROUND"
CHAMFER = "CHAMFER"
INVERTED = "INVERTED"


def _unit(v):
    l = math.hypot(v[0], v[1])
    return (v[0] / l, v[1] / l) if l > 1e-15 else (0.0, 0.0)


def _angle(u, v):
    return math.atan2(abs(u[0] * v[1] - u[1] * v[0]), u[0] * v[0] + u[1] * v[1])


def corner_angles(path, min_angle=math.radians(1.0)):
    """Map node index -> turning angle for every node that is a corner."""
    nodes = path.nodes
    n = len(nodes)
    segs = path.segments()
    m = len(segs)
    result = {}
    if m == 0:
        return result
    for i in range(n):
        if not path.closed and (i == 0 or i == n - 1):
            continue
        tin = _unit(bz.tangent_end(segs[i - 1]))
        tout = _unit(bz.tangent_start(segs[i % m]))
        if tin == (0.0, 0.0) or tout == (0.0, 0.0):
            continue
        phi = _angle(tin, tout)
        if min_angle <= phi < math.pi - 1e-3:
            result[i] = phi
    return result


def _arc_handles(a, b, ta, tb, psi):
    chord = bz.dist(a, b)
    r = chord / (2.0 * math.sin(psi / 2.0))
    h = 4.0 / 3.0 * math.tan(psi / 4.0) * r
    return (a, (a[0] + ta[0] * h, a[1] + ta[1] * h), (b[0] - tb[0] * h, b[1] - tb[1] * h), b)


def _tangent_at(seg, t, at_end):
    d = _unit(bz.deriv(seg, t))
    if d == (0.0, 0.0):
        d = _unit(bz.tangent_end(seg) if at_end else bz.tangent_start(seg))
    return d


def _corner_segment(a, b, ta, tb, corner, mode):
    if mode == CHAMFER or bz.dist(a, b) < 1e-15:
        return bz.line(a, b)
    if mode == INVERTED:
        # concave arc centred on the original corner point
        chord = (b[0] - a[0], b[1] - a[1])
        ra = (a[0] - corner[0], a[1] - corner[1])
        rb = (b[0] - corner[0], b[1] - corner[1])
        ta = _unit((-ra[1], ra[0]))
        if ta[0] * chord[0] + ta[1] * chord[1] < 0:
            ta = (-ta[0], -ta[1])
        tb = _unit((-rb[1], rb[0]))
        if tb[0] * chord[0] + tb[1] * chord[1] < 0:
            tb = (-tb[0], -tb[1])
    psi = _angle(ta, tb)
    if psi < 1e-6:
        return bz.line(a, b)
    return _arc_handles(a, b, ta, tb, psi)


def fillet_path(path, radius, mode=ROUND, selected_only=False, min_angle=math.radians(1.0)):
    """Replace corners with circular arcs, inverted arcs or straight chamfers.

    The trim on each side is clamped so neighbouring fillets never overlap.
    """
    if radius <= 0 or len(path.nodes) < 2:
        return path.copy()
    nodes = path.nodes
    n = len(nodes)
    segs = path.segments()
    m = len(segs)
    corners = corner_angles(path, min_angle)
    if selected_only:
        corners = {i: a for i, a in corners.items() if nodes[i].selected}
    if not corners:
        return path.copy()

    lengths = [bz.length(s) for s in segs]
    trim_start = [0.0] * m
    trim_end = [0.0] * m
    for i, phi in corners.items():
        si, so = (i - 1) % m, i % m
        d = radius * math.tan(phi / 2.0)
        lim_in = lengths[si] * (0.5 if ((i - 1) % n) in corners else 0.999)
        lim_out = lengths[so] * (0.5 if ((i + 1) % n) in corners else 0.999)
        d = min(d, lim_in, lim_out)
        trim_end[si] = d
        trim_start[so] = d

    trimmed = []
    params = []
    for k, s in enumerate(segs):
        t0 = bz.t_at_length(s, trim_start[k]) if trim_start[k] > 0 else 0.0
        t1 = bz.t_at_length(s, lengths[k] - trim_end[k]) if trim_end[k] > 0 else 1.0
        if t1 < t0:
            t0 = t1 = 0.5 * (t0 + t1)
        trimmed.append(bz.sub(s, t0, t1))
        params.append((t0, t1))

    eps = 1e-12 * max(1.0, max(lengths))
    out = []
    corner_seg_index = set()
    for k in range(m):
        if bz.length(trimmed[k]) > eps or not out:
            out.append(trimmed[k])
        end_node = (k + 1) % n
        if end_node in corners:
            nk = (k + 1) % m
            a, b = out[-1][3], trimmed[nk][0]
            ta = _tangent_at(segs[k], params[k][1], True)
            tb = _tangent_at(segs[nk], params[nk][0], False)
            corner_seg_index.add(len(out))
            out.append(_corner_segment(a, b, ta, tb, nodes[end_node].co, mode))
    if len(out) > 1 and bz.length(out[0]) <= eps:
        out.pop(0)
        corner_seg_index = {i - 1 for i in corner_seg_index}
    result = Path.from_segments(out, path.closed, path.meta)
    count = len(result.nodes)
    for idx in corner_seg_index:
        result.nodes[idx % count].selected = True
        result.nodes[(idx + 1) % count].selected = True
    return result
