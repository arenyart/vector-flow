"""Pathfinder-style booleans that keep the original Bezier geometry."""

from . import bezier as bz
from .path import Path, paths_diagonal, separate_touching
from .planar import overlay

UNION = "UNION"
INTERSECT = "INTERSECT"
DIFFERENCE = "DIFFERENCE"
EXCLUDE = "EXCLUDE"


def _predicate(op, ngroups):
    if op == UNION:
        return lambda w: any(x % 2 for x in w)
    if op == INTERSECT:
        return lambda w: all(x % 2 for x in w)
    if op == DIFFERENCE:
        return lambda w: (w[0] % 2 != 0) and not any(x % 2 for x in w[1:])
    if op == EXCLUDE:
        return lambda w: sum(1 for x in w if x % 2) % 2 == 1
    raise ValueError("unknown boolean operation %r" % op)


def build_loops(groups, tol):
    """Flatten every path of every group into tagged loops for :func:`overlay`."""
    sources = {}
    loops = []
    for g, paths in enumerate(groups):
        for pi, path in enumerate(paths):
            segs = path.segments(force_closed=True)
            if not segs:
                continue
            pts, tags = [], []
            for si, seg in enumerate(segs):
                key = (g, pi, si)
                sources[key] = seg
                ts = bz.flatten_ts(seg, tol)
                for k in range(len(ts) - 1):
                    pts.append(seg[0] if k == 0 else bz.point(seg, ts[k]))
                    tags.append((key, ts[k], ts[k + 1]))
            if len(pts) >= 2:
                loops.append((g, pts, tags))
    return loops, sources


def _continuous(e1, e2):
    t1, t2 = e1[2], e2[2]
    if t1 is None or t2 is None or t1[0] != t2[0]:
        return False
    if abs(t1[2] - t2[1]) > 1e-9:
        return False
    return (t1[2] - t1[1]) * (t2[2] - t2[1]) > 0


def _snap(seg, a, b):
    p0, p1, p2, p3 = seg
    d0 = (a[0] - p0[0], a[1] - p0[1])
    d3 = (b[0] - p3[0], b[1] - p3[1])
    return (a, (p1[0] + d0[0], p1[1] + d0[1]), (p2[0] + d3[0], p2[1] + d3[1]), b)


def _collinear_lines(s1, s2):
    if not (bz.is_line(s1, 1e-7) and bz.is_line(s2, 1e-7)):
        return False
    ax, ay = s1[3][0] - s1[0][0], s1[3][1] - s1[0][1]
    bx, by = s2[3][0] - s2[0][0], s2[3][1] - s2[0][1]
    la = (ax * ax + ay * ay) ** 0.5
    lb = (bx * bx + by * by) ** 0.5
    if la == 0 or lb == 0:
        return True
    return abs(ax * by - ay * bx) / (la * lb) < 1e-7 and (ax * bx + ay * by) > 0


def loop_to_path(loop, sources):
    """Rebuild Bezier segments from a tagged loop returned by :func:`overlay`."""
    n = len(loop)
    start = 0
    for i in range(n):
        if not _continuous(loop[i - 1], loop[i]):
            start = i
            break
    edges = loop[start:] + loop[:start]

    segs = []
    i = 0
    while i < n:
        j = i
        tag = edges[i][2]
        if tag is not None:
            while j + 1 < n and _continuous(edges[j], edges[j + 1]):
                j += 1
            seg = bz.sub(sources[tag[0]], tag[1], edges[j][2][2])
            seg = _snap(seg, edges[i][0], edges[j][1])
        else:
            seg = bz.line(edges[i][0], edges[i][1])
        if segs and _collinear_lines(segs[-1], seg):
            segs[-1] = bz.line(segs[-1][0], seg[3])
        else:
            segs.append(seg)
        i = j + 1
    if len(segs) > 1 and _collinear_lines(segs[-1], segs[0]):
        segs[0] = bz.line(segs[-1][0], segs[0][3])
        segs.pop()
    return Path.from_segments(segs, closed=True)


def boolean(groups, op, tol):
    """Combine operands.

    ``groups`` is a list of operands, each a list of :class:`Path`. Each operand
    uses the even-odd fill rule (nested loops are holes, like Blender's 2D fill).
    For DIFFERENCE the first operand is the base and the others are subtracted.
    """
    groups = [g for g in groups if g]
    if not groups:
        return []
    loops, sources = build_loops(groups, tol)
    out = overlay(loops, len(groups), _predicate(op, len(groups)))
    result = [loop_to_path(l, sources) for l in out]
    return separate_touching(result, max(paths_diagonal(result), 1e-9) * 1e-5)
