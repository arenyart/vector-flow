"""Redistribute a path's points evenly along its length."""

import math

from . import bezier as bz
from .fillet import corner_angles
from .fit import _chord_params, _generate, _reparam
from .path import Path

_MAX_POINTS = 10000


def _unit(v):
    l = math.hypot(v[0], v[1])
    return (v[0] / l, v[1] / l) if l > 1e-15 else (0.0, 0.0)


def _lengths(path):
    segs = path.segments()
    return segs, [bz.length(s) for s in segs]


def _locate(segs, lengths, s):
    """Segment index, parameter and point at arc length ``s`` (wraps on closed paths)."""
    total = sum(lengths)
    if total <= 1e-15:
        return 0, 0.0, segs[0][0]
    if s >= total and abs(s / total - round(s / total)) <= 1e-9:
        # An exact multiple of the length is the end of the last segment.
        # On a closed path that point is the same as the start.
        return len(segs) - 1, 1.0, segs[-1][3]
    s = s % total
    if s <= 1e-12:
        return 0, 0.0, segs[0][0]
    acc = 0.0
    for i, (seg, length) in enumerate(zip(segs, lengths)):
        if s <= acc + length or i == len(segs) - 1:
            local = min(length, max(0.0, s - acc))
            t = bz.t_at_length(seg, local) if length > 1e-15 else 0.0
            return i, t, bz.point(seg, t)
        acc += length
    return len(segs) - 1, 1.0, segs[-1][3]


def _tangent(seg, t):
    d = _unit(bz.deriv(seg, t))
    if d != (0.0, 0.0):
        return d
    return _unit(bz.tangent_end(seg) if t > 0.5 else bz.tangent_start(seg))


def _distribute(piece_lengths, intervals):
    """Share ``intervals`` gaps across pieces, at least one each."""
    m = len(piece_lengths)
    intervals = max(m, intervals)
    extra = intervals - m
    total = sum(piece_lengths)
    if extra == 0 or total <= 0:
        return [1] * m
    shares = [extra * length / total for length in piece_lengths]
    counts = [int(math.floor(share)) for share in shares]
    left = extra - sum(counts)
    order = sorted(range(m), key=lambda i: shares[i] - counts[i], reverse=True)
    for i in order[:left]:
        counts[i] += 1
    return [1 + c for c in counts]


def _pieces(path, segs, lengths, keep_corners, corner_angle):
    total = sum(lengths)
    corners = []
    if keep_corners:
        corners = sorted(corner_angles(path, corner_angle))
    if path.closed:
        if not corners:
            return [(0.0, total)]
        pos = [sum(lengths[:i]) for i in corners]
        return [(a, b) for a, b in zip(pos, pos[1:] + [pos[0] + total])]
    pos = [0.0]
    pos.extend(sum(lengths[:i]) for i in corners)
    pos.append(total)
    unique = []
    for s in pos:
        if not unique or s - unique[-1] > 1e-9 * max(total, 1.0):
            unique.append(s)
    if len(unique) < 2:
        return [(0.0, total)]
    return list(zip(unique, unique[1:]))


def _sample_lengths(path, pieces, intervals):
    samples = []
    for index, ((start, end), gaps) in enumerate(zip(pieces, intervals)):
        for k in range(gaps):
            samples.append(start + (end - start) * k / gaps)
        if not path.closed and index == len(pieces) - 1:
            samples.append(end)
    return samples


def _span_cubic(segs, lengths, s0, s1):
    span = s1 - s0
    steps = max(4, min(16, int(math.ceil(span / max(sum(lengths), 1e-9) * 64))))
    pts = [_locate(segs, lengths, s0 + span * k / steps)[2] for k in range(steps + 1)]
    i0, t0, _ = _locate(segs, lengths, s0)
    i1, t1, _ = _locate(segs, lengths, s1)
    forward = _tangent(segs[i0], t0)
    backward = _tangent(segs[i1], t1)
    chord = (pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
    if forward == (0.0, 0.0):
        forward = _unit(chord)
    if backward == (0.0, 0.0):
        backward = _unit(chord)
    inward_end = (-backward[0], -backward[1])
    u = _chord_params(pts, 0, len(pts) - 1)
    seg = _generate(pts, 0, len(pts) - 1, u, forward, inward_end)
    for _ in range(4):
        u = _reparam(pts, 0, len(pts) - 1, u, seg)
        seg = _generate(pts, 0, len(pts) - 1, u, forward, inward_end)
    return seg


def resample_path(path, count=None, spacing=None, smooth=True, keep_corners=True,
                  corner_angle=math.radians(35.0)):
    """Place points at even arc-length steps and rebuild the path through them.

    ``count`` is the number of points. ``spacing`` is the target distance between
    them; the actual distance is evened out so it divides the path length.
    Closed paths do not repeat the first point. Sharp corners are kept in place
    and the extra points are shared between the pieces on either side.
    """
    if len(path.nodes) < 2:
        return path.copy()
    segs, lengths = _lengths(path)
    total = sum(lengths)
    if not segs or total <= 1e-12:
        return path.copy()

    pieces = _pieces(path, segs, lengths, keep_corners, corner_angle)
    if spacing is not None and count is None:
        intervals = [max(1, int(round((end - start) / spacing))) if spacing > 0 else 1
                     for start, end in pieces]
    else:
        target = 8 if count is None else int(count)
        if path.closed:
            target = max(len(pieces), target, 3)
        else:
            target = max(len(pieces) + 1, target, 2)
        gaps = target if path.closed else target - 1
        intervals = _distribute([end - start for start, end in pieces], gaps)
    if sum(intervals) > _MAX_POINTS:
        scale = _MAX_POINTS / sum(intervals)
        intervals = [max(1, int(n * scale)) for n in intervals]

    samples = _sample_lengths(path, pieces, intervals)
    if len(samples) < (3 if path.closed else 2):
        return path.copy()

    if not smooth:
        points = [_locate(segs, lengths, s)[2] for s in samples]
        result = Path.from_polyline(points, path.closed, path.meta)
        return result

    order = samples + ([samples[0] + total] if path.closed else [])
    cubics = []
    for s0, s1 in zip(order, order[1:]):
        if s1 - s0 <= 1e-9 * max(total, 1.0):
            continue
        cubics.append(_span_cubic(segs, lengths, s0, s1))
    if not cubics:
        return path.copy()
    result = Path.from_segments(cubics, path.closed, path.meta)
    return result
