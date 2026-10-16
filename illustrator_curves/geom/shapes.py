"""Primitive shapes centred on the origin, counter-clockwise."""

import math

from .fillet import fillet_path
from .path import Node, Path

KAPPA = 0.5522847498307936


def rectangle(width, height, corner_radius=0.0, corner_mode="ROUND"):
    w, h = width * 0.5, height * 0.5
    p = Path.from_polyline([(-w, -h), (w, -h), (w, h), (-w, h)], closed=True)
    if corner_radius > 0:
        p = fillet_path(p, corner_radius, corner_mode)
    return p


def ellipse(rx, ry):
    kx, ky = rx * KAPPA, ry * KAPPA
    nodes = [
        Node((rx, 0.0), (rx, -ky), (rx, ky)),
        Node((0.0, ry), (kx, ry), (-kx, ry)),
        Node((-rx, 0.0), (-rx, ky), (-rx, -ky)),
        Node((0.0, -ry), (-kx, -ry), (kx, -ry)),
    ]
    return Path(nodes, closed=True)


def polygon(sides, radius, corner_radius=0.0, corner_mode="ROUND"):
    sides = max(3, int(sides))
    pts = [(radius * math.cos(math.pi / 2 + 2 * math.pi * i / sides),
            radius * math.sin(math.pi / 2 + 2 * math.pi * i / sides)) for i in range(sides)]
    p = Path.from_polyline(pts, closed=True)
    if corner_radius > 0:
        p = fillet_path(p, corner_radius, corner_mode)
    return p


def star(points, outer_radius, inner_radius, corner_radius=0.0, corner_mode="ROUND"):
    points = max(2, int(points))
    pts = []
    for i in range(points * 2):
        r = outer_radius if i % 2 == 0 else inner_radius
        a = math.pi / 2 + math.pi * i / points
        pts.append((r * math.cos(a), r * math.sin(a)))
    p = Path.from_polyline(pts, closed=True)
    if corner_radius > 0:
        p = fillet_path(p, corner_radius, corner_mode)
    return p
