"""Planar overlay of polygon soups with winding-number region extraction.

Every input loop belongs to a *group* (an operand). All edges are split at their
mutual intersections, coincident pieces are merged, and for every resulting edge
we compute the winding number of each group just to its left and to its right.
A caller-supplied predicate decides which side is "inside" the result; edges
where the predicate differs across the edge form the output boundary.

Edges may carry a *tag* ``(source, t0, t1)`` that is interpolated through the
splits, which lets callers rebuild exact Bezier geometry afterwards.
"""

import math
from bisect import bisect_right


def _vertex_pool(snap):
    cells = {}
    coords = []

    def vid(x, y):
        cx = math.floor(x / snap)
        cy = math.floor(y / snap)
        best = -1
        bestd = snap * snap
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                for k in cells.get((i, j), ()):
                    vx, vy = coords[k]
                    d = (vx - x) ** 2 + (vy - y) ** 2
                    if d <= bestd:
                        bestd = d
                        best = k
        if best >= 0:
            return best
        coords.append((x, y))
        cells.setdefault((cx, cy), []).append(len(coords) - 1)
        return len(coords) - 1

    return vid, coords


def _find_splits(edges, eps):
    """For each edge, a list of (t, point) interior split locations."""
    splits = [[] for _ in edges]
    n = len(edges)
    minx = [min(e[0], e[2]) for e in edges]
    maxx = [max(e[0], e[2]) for e in edges]
    miny = [min(e[1], e[3]) for e in edges]
    maxy = [max(e[1], e[3]) for e in edges]
    order = sorted(range(n), key=minx.__getitem__)
    sorted_minx = [minx[i] for i in order]

    for oi in range(n):
        i = order[oi]
        ax, ay, bx, by = edges[i][:4]
        rx, ry = bx - ax, by - ay
        rr = rx * rx + ry * ry
        lr = math.sqrt(rr)
        et = eps / lr
        hi = bisect_right(sorted_minx, maxx[i] + eps)
        for oj in range(oi + 1, hi):
            j = order[oj]
            if miny[j] > maxy[i] + eps or maxy[j] < miny[i] - eps:
                continue
            cx, cy, dx, dy = edges[j][:4]
            sx, sy = dx - cx, dy - cy
            ss = sx * sx + sy * sy
            ls = math.sqrt(ss)
            eu = eps / ls

            # endpoints of j touching the interior of i
            for px, py in ((cx, cy), (dx, dy)):
                t = ((px - ax) * rx + (py - ay) * ry) / rr
                if et < t < 1.0 - et:
                    if abs((px - ax) * ry - (py - ay) * rx) / lr <= eps:
                        splits[i].append((t, (px, py)))
            # endpoints of i touching the interior of j
            for px, py in ((ax, ay), (bx, by)):
                u = ((px - cx) * sx + (py - cy) * sy) / ss
                if eu < u < 1.0 - eu:
                    if abs((px - cx) * sy - (py - cy) * sx) / ls <= eps:
                        splits[j].append((u, (px, py)))

            den = rx * sy - ry * sx
            if abs(den) <= 1e-12 * lr * ls:
                continue
            qx, qy = cx - ax, cy - ay
            t = (qx * sy - qy * sx) / den
            u = (qx * ry - qy * rx) / den
            if et < t < 1.0 - et and eu < u < 1.0 - eu:
                p = (ax + rx * t, ay + ry * t)
                splits[i].append((t, p))
                splits[j].append((u, p))
    return splits


class _Bins:
    """Edges bucketed along one axis for fast ray-crossing queries."""

    def __init__(self, ux0, uy0, ux1, uy1, axis):
        n = len(ux0)
        lo_c = uy0 if axis == 0 else ux0
        hi_c = uy1 if axis == 0 else ux1
        self.lo = min(min(lo_c), min(hi_c))
        hi = max(max(lo_c), max(hi_c))
        self.k = max(1, min(4096, int(math.sqrt(n) * 2)))
        span = hi - self.lo
        self.inv = self.k / span if span > 0 else 0.0
        self.bins = [[] for _ in range(self.k)]
        for e in range(n):
            a, b = lo_c[e], hi_c[e]
            if a == b:
                continue
            if a > b:
                a, b = b, a
            for k in range(self._idx(a), self._idx(b) + 1):
                self.bins[k].append(e)

    def _idx(self, v):
        k = int((v - self.lo) * self.inv)
        return 0 if k < 0 else (self.k - 1 if k >= self.k else k)

    def query(self, v):
        return self.bins[self._idx(v)]


def overlay(loops, ngroups, predicate, eps=None):
    """Compute the boundary of the region selected by ``predicate``.

    ``loops`` is an iterable of ``(group, points, tags)``; each loop is closed
    implicitly and ``tags`` (optional) has one entry per edge.
    ``predicate(windings)`` receives a list with one winding number per group.

    Returns a list of loops; each loop is a list of ``(a, b, tag)`` directed
    edges with the selected region on the left.
    """
    edges = []
    for g, pts, tags in loops:
        n = len(pts)
        if n < 2:
            continue
        for i in range(n):
            a = pts[i]
            b = pts[(i + 1) % n]
            if a[0] == b[0] and a[1] == b[1]:
                continue
            edges.append((a[0], a[1], b[0], b[1], g, tags[i] if tags else None))
    if not edges:
        return []

    xs = [e[0] for e in edges] + [e[2] for e in edges]
    ys = [e[1] for e in edges] + [e[3] for e in edges]
    scale = max(max(xs) - min(xs), max(ys) - min(ys), 1e-12)
    if eps is None:
        eps = scale * 1e-9
    snap = eps * 4.0

    splits = _find_splits(edges, eps)
    vid, coords = _vertex_pool(snap)

    # unique undirected edges: key (lo, hi) -> [counts, tag]
    unique = {}
    for e, sp in zip(edges, splits):
        ax, ay, bx, by, g, tag = e
        pts = [(0.0, (ax, ay))]
        if sp:
            sp.sort(key=lambda s: s[0])
            pts.extend(sp)
        pts.append((1.0, (bx, by)))
        ids = [(t, vid(p[0], p[1])) for t, p in pts]
        for k in range(len(ids) - 1):
            f0, va = ids[k]
            f1, vb = ids[k + 1]
            if va == vb:
                continue
            if va < vb:
                key, sign = (va, vb), 1
            else:
                key, sign = (vb, va), -1
            entry = unique.get(key)
            if entry is None:
                entry = [[0] * ngroups, None]
                unique[key] = entry
            entry[0][g] += sign
            if entry[1] is None and tag is not None:
                src, t0, t1 = tag
                ta = t0 + (t1 - t0) * f0
                tb = t0 + (t1 - t0) * f1
                entry[1] = (src, ta, tb) if sign > 0 else (src, tb, ta)

    keys = [k for k, v in unique.items() if any(v[0])]
    if not keys:
        return []
    counts = [unique[k][0] for k in keys]
    ctags = [unique[k][1] for k in keys]
    ux0 = [coords[k[0]][0] for k in keys]
    uy0 = [coords[k[0]][1] for k in keys]
    ux1 = [coords[k[1]][0] for k in keys]
    uy1 = [coords[k[1]][1] for k in keys]

    ybins = _Bins(ux0, uy0, ux1, uy1, 0)
    xbins = _Bins(ux0, uy0, ux1, uy1, 1)
    groups = range(ngroups)

    out_edges = []
    for e in range(len(keys)):
        x0, y0, x1, y1 = ux0[e], uy0[e], ux1[e], uy1[e]
        mx, my = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        dx, dy = x1 - x0, y1 - y0
        w = [0] * ngroups
        if abs(dy) >= abs(dx):
            # horizontal ray towards +x
            for f in ybins.query(my):
                if f == e:
                    continue
                fy0, fy1 = uy0[f], uy1[f]
                if fy0 <= my < fy1:
                    s = 1
                elif fy1 <= my < fy0:
                    s = -1
                else:
                    continue
                fx0 = ux0[f]
                xi = fx0 + (my - fy0) * (ux1[f] - fx0) / (fy1 - fy0)
                if xi > mx:
                    c = counts[f]
                    for g in groups:
                        w[g] += s * c[g]
            plus_is_left = dy < 0
        else:
            # vertical ray towards +y
            for f in xbins.query(mx):
                if f == e:
                    continue
                fx0, fx1 = ux0[f], ux1[f]
                if fx1 <= mx < fx0:
                    s = 1
                elif fx0 <= mx < fx1:
                    s = -1
                else:
                    continue
                fy0 = uy0[f]
                yi = fy0 + (mx - fx0) * (uy1[f] - fy0) / (fx1 - fx0)
                if yi > my:
                    c = counts[f]
                    for g in groups:
                        w[g] += s * c[g]
            plus_is_left = dx > 0
        c = counts[e]
        if plus_is_left:
            wl = w
            wr = [w[g] - c[g] for g in groups]
        else:
            wr = w
            wl = [w[g] + c[g] for g in groups]
        inl = bool(predicate(wl))
        inr = bool(predicate(wr))
        if inl == inr:
            continue
        va, vb = keys[e]
        tag = ctags[e]
        if inl:
            out_edges.append((va, vb, tag))
        else:
            out_edges.append((vb, va, (tag[0], tag[2], tag[1]) if tag else None))

    return _chain(out_edges, coords, scale)


def _chain(out_edges, coords, scale):
    outgoing = {}
    for idx, (va, vb, _) in enumerate(out_edges):
        outgoing.setdefault(va, []).append(idx)
    used = [False] * len(out_edges)
    loops = []
    for start in range(len(out_edges)):
        if used[start]:
            continue
        loop = []
        cur = start
        start_v = out_edges[start][0]
        while True:
            used[cur] = True
            va, vb, tag = out_edges[cur]
            loop.append((coords[va], coords[vb], tag))
            if vb == start_v:
                break
            cands = [k for k in outgoing.get(vb, ()) if not used[k]]
            if not cands:
                loop = None
                break
            if len(cands) == 1:
                cur = cands[0]
                continue
            # face on the left: take the first edge clockwise from the reversed incoming direction
            ax, ay = coords[va]
            bx, by = coords[vb]
            ref = math.atan2(ay - by, ax - bx)
            best, best_ang = None, None
            for k in cands:
                cx, cy = coords[out_edges[k][1]]
                ang = (ref - math.atan2(cy - by, cx - bx)) % (2.0 * math.pi)
                if ang <= 1e-12:
                    ang += 2.0 * math.pi
                if best_ang is None or ang < best_ang:
                    best, best_ang = k, ang
            cur = best
        if loop and len(loop) >= 3:
            area = 0.0
            for a, b, _ in loop:
                area += a[0] * b[1] - b[0] * a[1]
            if abs(area) * 0.5 > (scale * 1e-7) ** 2:
                loops.append(loop)
    return loops


def even_odd(w):
    return w % 2 != 0


def nonzero(w):
    return w != 0
