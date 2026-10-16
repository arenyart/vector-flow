"""Path model mirroring Blender's Bezier splines, in 2D."""

import math

from . import bezier as bz


def _mirror(center, p):
    return (2.0 * center[0] - p[0], 2.0 * center[1] - p[1])


class Node:
    """A control point: position plus left/right handles (Blender convention)."""

    __slots__ = ("co", "hl", "hr", "selected", "hl_type", "hr_type")

    def __init__(self, co, hl=None, hr=None, selected=False, hl_type=None, hr_type=None):
        self.co = (float(co[0]), float(co[1]))
        self.hl = (float(hl[0]), float(hl[1])) if hl is not None else self.co
        self.hr = (float(hr[0]), float(hr[1])) if hr is not None else self.co
        self.selected = selected
        self.hl_type = hl_type
        self.hr_type = hr_type

    def copy(self):
        return Node(self.co, self.hl, self.hr, self.selected, self.hl_type, self.hr_type)

    def __repr__(self):
        return "Node(%r, hl=%r, hr=%r)" % (self.co, self.hl, self.hr)


class Path:
    def __init__(self, nodes, closed=False, meta=None):
        self.nodes = list(nodes)
        self.closed = bool(closed)
        self.meta = dict(meta) if meta else {}

    def __len__(self):
        return len(self.nodes)

    def copy(self):
        return Path([n.copy() for n in self.nodes], self.closed, self.meta)

    def segments(self, force_closed=False):
        """Cubic segments of the path. ``force_closed`` adds a straight closing segment to open paths."""
        nodes = self.nodes
        n = len(nodes)
        if n == 0:
            return []
        segs = []
        for i in range(n - 1):
            a, b = nodes[i], nodes[i + 1]
            segs.append((a.co, a.hr, b.hl, b.co))
        if self.closed:
            a, b = nodes[-1], nodes[0]
            segs.append((a.co, a.hr, b.hl, b.co))
        elif force_closed and n > 1 and bz.dist(nodes[-1].co, nodes[0].co) > 0.0:
            segs.append(bz.line(nodes[-1].co, nodes[0].co))
        return segs

    @classmethod
    def from_segments(cls, segs, closed, meta=None):
        segs = [s for s in segs if s is not None]
        if not segs:
            return cls([], closed, meta)
        nodes = []
        if closed:
            for i, s in enumerate(segs):
                nodes.append(Node(s[0], segs[i - 1][2], s[1]))
        else:
            first = segs[0]
            nodes.append(Node(first[0], _mirror(first[0], first[1]), first[1]))
            for i in range(1, len(segs)):
                nodes.append(Node(segs[i][0], segs[i - 1][2], segs[i][1]))
            last = segs[-1]
            nodes.append(Node(last[3], last[2], _mirror(last[3], last[2])))
        return cls(nodes, closed, meta)

    @classmethod
    def from_polyline(cls, points, closed, meta=None):
        pts = [(float(p[0]), float(p[1])) for p in points]
        n = len(pts)
        if n == 0:
            return cls([], closed, meta)
        if n == 1:
            return cls([Node(pts[0])], closed, meta)
        segs = [bz.line(pts[i], pts[i + 1]) for i in range(n - 1)]
        if closed:
            segs.append(bz.line(pts[-1], pts[0]))
        return cls.from_segments(segs, closed, meta)

    def flatten(self, tol, force_closed=False):
        """Polyline approximation. Closed paths do not repeat the first point."""
        segs = self.segments(force_closed)
        if not segs:
            return [n.co for n in self.nodes]
        pts = []
        for seg in segs:
            ts = bz.flatten_ts(seg, tol)
            pts.append(seg[0])
            for t in ts[1:-1]:
                pts.append(bz.point(seg, t))
        if not (self.closed or force_closed):
            pts.append(segs[-1][3])
        return pts

    def reversed(self):
        nodes = [Node(n.co, n.hr, n.hl, n.selected, n.hr_type, n.hl_type) for n in reversed(self.nodes)]
        return Path(nodes, self.closed, self.meta)

    def transformed(self, fn):
        nodes = [Node(fn(n.co), fn(n.hl), fn(n.hr), n.selected, n.hl_type, n.hr_type) for n in self.nodes]
        return Path(nodes, self.closed, self.meta)

    def bounds(self):
        xs, ys = [], []
        for n in self.nodes:
            for p in (n.co, n.hl, n.hr):
                xs.append(p[0])
                ys.append(p[1])
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))

    def area(self, tol=1e-4):
        """Signed area (positive when counter-clockwise)."""
        return polygon_area(self.flatten(tol, force_closed=True))


def polygon_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return 0.5 * a


def paths_bounds(paths):
    bs = [p.bounds() for p in paths if p.nodes]
    if not bs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def paths_diagonal(paths):
    b = paths_bounds(paths)
    return math.hypot(b[2] - b[0], b[3] - b[1])


def assign_handle_types(path, eps=1e-6):
    """Pick Blender handle types that reproduce the geometry without distorting it.

    Nodes with explicit types keep them. Straight neighbours get VECTOR, smooth
    curved joins ALIGNED, everything else FREE.
    """
    nodes = path.nodes
    n = len(nodes)
    segs = path.segments()
    result = []
    for i, node in enumerate(nodes):
        left = segs[i - 1] if (path.closed or i > 0) and segs else None
        right = segs[i] if (path.closed or i < n - 1) and i < len(segs) else None
        left_line = left is not None and bz.is_line(left, eps)
        right_line = right is not None and bz.is_line(right, eps)
        if left is None:
            left_line = right_line
        if right is None:
            right_line = left_line
        lt = "VECTOR" if left_line else "FREE"
        rt = "VECTOR" if right_line else "FREE"
        if lt == "FREE" and rt == "FREE":
            ax, ay = node.hl[0] - node.co[0], node.hl[1] - node.co[1]
            bx, by = node.hr[0] - node.co[0], node.hr[1] - node.co[1]
            la, lb = math.hypot(ax, ay), math.hypot(bx, by)
            if la > 1e-12 and lb > 1e-12:
                cross = (ax * by - ay * bx) / (la * lb)
                dot = (ax * bx + ay * by) / (la * lb)
                if abs(cross) < 1e-4 and dot < 0:
                    lt = rt = "ALIGNED"
        result.append((node.hl_type or lt, node.hr_type or rt))
    return result
