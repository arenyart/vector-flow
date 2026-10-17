"""Raised bevel: inset a filled shape, lift the inset, and loft the band between them."""

import math

from . import bezier as bz
from .boolean import DIFFERENCE, boolean
from .offset import offset_paths
from .path import polygon_area, paths_diagonal

LINEAR = "LINEAR"
CONVEX = "CONVEX"
CONCAVE = "CONCAVE"


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _contains(poly, p):
    inside = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if (y0 > p[1]) != (y1 > p[1]):
            x = x0 + (p[1] - y0) * (x1 - x0) / (y1 - y0)
            if p[0] < x:
                inside = not inside
    return inside


def _in_tri(p, a, b, c, eps):
    return _cross(a, b, p) > eps and _cross(b, c, p) > eps and _cross(c, a, p) > eps


def _proper_hit(a, b, c, d):
    c1, c2 = _cross(a, b, c), _cross(a, b, d)
    c3, c4 = _cross(c, d, a), _cross(c, d, b)
    if c1 == 0 or c2 == 0 or c3 == 0 or c4 == 0:
        return False
    return (c1 > 0) != (c2 > 0) and (c3 > 0) != (c4 > 0)


def _edges_of(poly):
    return list(zip(poly, poly[1:] + poly[:1]))


def _visible(outer, hole, h, o):
    a, b = hole[h], outer[o]
    for poly in (outer, hole):
        n = len(poly)
        for i in range(n):
            c, d = poly[i], poly[(i + 1) % n]
            if _proper_hit(a, b, c, d):
                return False
    mid = ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
    return _contains(outer, mid) and not _contains(hole, mid)


def _ear_clip(poly):
    """Triangles for a CCW polygon. Collinear ears are dropped rather than filled."""
    n = len(poly)
    if n < 3:
        return []
    scale = max(bz.dist(poly[i], poly[(i + 1) % n]) for i in range(n))
    eps = max(scale, 1.0) * 1e-12
    idx = list(range(n))
    tris = []
    guard = n * n
    while len(idx) > 3 and guard > 0:
        guard -= 1
        m = len(idx)
        clipped = False
        for t in range(m):
            i0, i1, i2 = idx[(t - 1) % m], idx[t], idx[(t + 1) % m]
            area = _cross(poly[i0], poly[i1], poly[i2])
            if area < -eps:
                continue
            if area <= eps:
                del idx[t]
                clipped = True
                break
            a, b, c = poly[i0], poly[i1], poly[i2]
            if any(_in_tri(poly[j], a, b, c, eps) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            del idx[t]
            clipped = True
            break
        if not clipped:
            break
    if len(idx) == 3 and _cross(poly[idx[0]], poly[idx[1]], poly[idx[2]]) > eps:
        tris.append(tuple(idx))
    return tris


def _triangulate_indexed(loops):
    offsets = []
    cursor = 0
    indexed = []
    for pts in loops:
        offsets.append(cursor)
        indexed.append(list(range(cursor, cursor + len(pts))))
        cursor += len(pts)
    flat = [p for pts in loops for p in pts]
    tris = []
    # Map a point's id back through oriented copies: work entirely in coordinates stored with indices.
    shells = []
    depth = []
    for i, pts in enumerate(loops):
        # A boundary vertex, not the centroid: a hole's centroid sits in the hole disk.
        sample = pts[0]
        depth.append(sum(1 for j, other in enumerate(loops) if i != j and _contains(other, sample)))
    for i, pts in enumerate(loops):
        if depth[i] % 2 == 0:
            ids = indexed[i] if polygon_area(pts) > 0 else list(reversed(indexed[i]))
            shells.append((ids, []))
    for i, pts in enumerate(loops):
        if depth[i] % 2 == 0:
            continue
        sample = pts[0]
        host = None
        host_area = None
        for shell in shells:
            if _contains([flat[k] for k in shell[0]], sample):
                area = abs(polygon_area([flat[k] for k in shell[0]]))
                if host is None or area < host_area:
                    host, host_area = shell, area
        if host is not None:
            ids = indexed[i] if polygon_area(pts) < 0 else list(reversed(indexed[i]))
            host[1].append(ids)
    for shell, holes in shells:
        poly = list(shell)
        for hole in holes:
            linked = _link_ids(flat, poly, hole)
            if linked is not None:
                poly = linked
        for a, b, c in _ear_clip([flat[k] for k in poly]):
            tris.append((poly[a], poly[b], poly[c]))
    return flat, tris


def _link_ids(flat, outer, hole):
    h = max(range(len(hole)), key=lambda i: (flat[hole[i]][0], flat[hole[i]][1]))
    outer_pts = [flat[i] for i in outer]
    hole_pts = [flat[i] for i in hole]
    order = sorted(range(len(outer)), key=lambda i: bz.dist(outer_pts[i], hole_pts[h]))
    o = next((i for i in order if _visible(outer_pts, hole_pts, h, i)), None)
    if o is None:
        return None
    cycle = hole[h:] + hole[:h]
    return outer[:o + 1] + cycle + [hole[h]] + outer[o:]


def _profile(kind, t):
    """Inset fraction and height fraction, both 0 at the original edge and 1 at the full inset."""
    t = min(1.0, max(0.0, t))
    if kind == CONVEX:
        a = t * math.pi * 0.5
        return 1.0 - math.cos(a), math.sin(a)
    if kind == CONCAVE:
        a = t * math.pi * 0.5
        return math.sin(a), 1.0 - math.cos(a)
    return t, t


def _boundaries(paths, tol):
    out = []
    for path in paths:
        if path.closed and len(path.nodes) >= 3:
            pts = path.flatten(tol)
            if len(pts) >= 3:
                out.append(pts)
    return out


def _dist_to(pt, loops):
    best = 1e300
    for poly in loops:
        for a, b in _edges_of(poly):
            best = min(best, bz._dist_point_segment(pt, a, b))
    return best


def _fill(verts, loops, z, upward):
    if not loops:
        return []
    _flat, tris = _triangulate_indexed(loops)
    base = len(verts)
    for pts in loops:
        for p in pts:
            verts.append((p[0], p[1], z))
    faces = []
    for a, b, c in tris:
        tri = (base + a, base + b, base + c)
        if not upward:
            tri = (tri[0], tri[2], tri[1])
        faces.append(tri)
    return faces


def _band(verts, band_paths, z0, z1, bound0, bound1, tol):
    loops = _boundaries(band_paths, tol)
    if not loops:
        return []
    _flat, tris = _triangulate_indexed(loops)
    base = len(verts)
    zs = []
    for pts in loops:
        for p in pts:
            d0 = _dist_to(p, bound0)
            d1 = _dist_to(p, bound1)
            zs.append(z0 if d0 <= d1 else z1)
            verts.append((p[0], p[1], zs[-1]))
    return [(base + a, base + b, base + c) for a, b, c in tris]


def _weld(verts, faces, eps):
    if eps <= 0:
        return verts, faces
    cells = {}
    remap = []
    merged = []

    def find(v):
        key = (int(math.floor(v[0] / eps)), int(math.floor(v[1] / eps)), int(math.floor(v[2] / eps)))
        for a in (-1, 0, 1):
            for b in (-1, 0, 1):
                for c in (-1, 0, 1):
                    for idx in cells.get((key[0] + a, key[1] + b, key[2] + c), ()):
                        q = merged[idx]
                        if (q[0] - v[0]) ** 2 + (q[1] - v[1]) ** 2 + (q[2] - v[2]) ** 2 <= eps * eps:
                            return idx
        return None

    for v in verts:
        idx = find(v)
        if idx is None:
            idx = len(merged)
            merged.append(v)
            key = (int(math.floor(v[0] / eps)), int(math.floor(v[1] / eps)), int(math.floor(v[2] / eps)))
            cells.setdefault(key, []).append(idx)
        remap.append(idx)
    out = []
    for face in faces:
        nf = []
        for i in face:
            j = remap[i]
            if not nf or j != nf[-1]:
                nf.append(j)
        if len(nf) >= 2 and nf[0] == nf[-1]:
            nf.pop()
        if len(set(nf)) >= 3:
            out.append(tuple(nf))
    return merged, out


def _volume(verts, faces):
    vol = 0.0
    for f in faces:
        for i in range(1, len(f) - 1):
            a, b, c = verts[f[0]], verts[f[i]], verts[f[i + 1]]
            vol += a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])
    return vol / 6.0


def chisel_mesh(paths, width, height, tol=1e-3, join="MITER", miter_limit=4.0, divisions=1,
                profile=LINEAR):
    """Inset ``paths`` by ``width`` and loft the band up to ``height``.

    Returns ``(vertices, faces)`` in the paths' 2D plane, with Z added, or None when the
    inset eats the shape. ``divisions`` slices the bevel into steps. ``profile`` is
    LINEAR, CONVEX (quarter-round) or CONCAVE (cove). The original outline stays at
    Z = 0 and the innermost inset sits at Z = ``height``.
    """
    closed = [p for p in paths if p.closed and len(p.nodes) >= 3]
    if not closed or width <= 0:
        return None
    divisions = max(1, int(divisions))
    rings = [closed]
    levels = [0.0]
    for k in range(1, divisions + 1):
        inset_f, height_f = _profile(profile, k / divisions)
        inset = offset_paths(closed, -width * inset_f, join, miter_limit, tol)
        if not inset:
            break
        rings.append(inset)
        levels.append(height * height_f)
    if len(rings) < 2:
        return None

    verts = []
    faces = []
    faces.extend(_fill(verts, _boundaries(rings[0], tol), levels[0], upward=False))
    faces.extend(_fill(verts, _boundaries(rings[-1], tol), levels[-1], upward=True))
    for prev, nxt, z0, z1 in zip(rings, rings[1:], levels, levels[1:]):
        band = boolean([prev, nxt], DIFFERENCE, tol)
        if not band:
            continue
        faces.extend(_band(verts, band, z0, z1, _boundaries(prev, tol), _boundaries(nxt, tol), tol))
    if not faces:
        return None
    diag = max(paths_diagonal(closed), 1e-9)
    eps = min(width * 0.25, max(diag * 5e-5, 1e-8))
    verts, faces = _weld(verts, faces, eps)
    return verts, faces


def mesh_volume(verts, faces):
    return _volume(verts, faces)
