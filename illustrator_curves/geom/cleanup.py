"""Weld duplicate control points."""

from . import bezier as bz
from .path import Node, Path


def _average(nodes):
    n = len(nodes)
    return (sum(p.co[0] for p in nodes) / n, sum(p.co[1] for p in nodes) / n)


def _merge_run(nodes):
    """One point for a run. The incoming handle comes from the first point and the outgoing handle from the last."""
    if len(nodes) == 1:
        return nodes[0].copy()
    co = _average(nodes)
    first, last = nodes[0], nodes[-1]
    dl = (co[0] - first.co[0], co[1] - first.co[1])
    dr = (co[0] - last.co[0], co[1] - last.co[1])
    return Node(
        co,
        (first.hl[0] + dl[0], first.hl[1] + dl[1]),
        (last.hr[0] + dr[0], last.hr[1] + dr[1]),
        selected=any(n.selected for n in nodes),
        hl_type=first.hl_type,
        hr_type=last.hr_type,
    )


def _cluster(nodes, distance, can_merge):
    clusters = []
    for i, node in enumerate(nodes):
        if clusters and can_merge(clusters[-1][0], i) and bz.dist(clusters[-1][1][0].co, node.co) <= distance:
            clusters[-1][1].append(node)
        else:
            clusters.append((i, [node]))
    return clusters


def remove_doubles(path, distance, selected_only=False, weld_ends=True):
    """Merge neighboring control points that lie within ``distance`` of the first point in the run.

    On a closed path the seam is included, so a doubled start point is removed too.
    On an open path, ends within ``distance`` are welded and the path is closed
    when ``weld_ends`` is set. In selected-only mode a point merges only with
    other selected points.
    """
    nodes = path.nodes
    if len(nodes) < 2 or distance < 0:
        return path.copy()

    def can_merge(anchor_index, index):
        if not selected_only:
            return True
        return nodes[anchor_index].selected and nodes[index].selected

    clusters = _cluster(nodes, distance, can_merge)
    closed = path.closed
    if closed and len(clusters) > 1:
        last_i, last_run = clusters[-1]
        first_i, first_run = clusters[0]
        if can_merge(last_i, first_i) and bz.dist(last_run[0].co, first_run[0].co) <= distance:
            clusters[0] = (last_i, last_run + first_run)
            clusters.pop()

    merged = [_merge_run(run) for _, run in clusters]
    if not closed and weld_ends and len(merged) >= 2 and bz.dist(merged[0].co, merged[-1].co) <= distance:
        ends_ok = not selected_only or (nodes[0].selected and nodes[-1].selected)
        if ends_ok:
            merged = [_merge_run([merged[-1], merged[0]])] + merged[1:-1]
            closed = len(merged) >= 2
    if len(merged) < 2:
        closed = False
    result = Path(merged, closed, path.meta)
    return result
