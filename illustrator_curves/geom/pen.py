"""State machine behind the Pen tool, independent of Blender."""

import math

from .path import Node, Path


def constrain_45(origin, p):
    """Snap ``p`` so the direction from ``origin`` is a multiple of 45 degrees."""
    dx, dy = p[0] - origin[0], p[1] - origin[1]
    l = math.hypot(dx, dy)
    if l == 0:
        return p
    a = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
    return (origin[0] + l * math.cos(a), origin[1] + l * math.sin(a))


class PenState:
    """Click to add corner points, click-drag to pull symmetric handles,
    Alt-drag to pull only the outgoing handle (cusp)."""

    def __init__(self):
        self.nodes = []
        self.dragging = False

    def __len__(self):
        return len(self.nodes)

    def add(self, co):
        self.nodes.append(Node(co, co, co, hl_type="VECTOR", hr_type="VECTOR"))
        self.dragging = True

    def drag(self, handle, cusp=False, min_len=1e-9):
        if not self.nodes:
            return
        n = self.nodes[-1]
        if math.hypot(handle[0] - n.co[0], handle[1] - n.co[1]) <= min_len:
            return
        n.hr = (float(handle[0]), float(handle[1]))
        if cusp:
            n.hr_type = "FREE"
            if n.hl_type == "ALIGNED":
                n.hl_type = "FREE"
        else:
            n.hl = (2 * n.co[0] - n.hr[0], 2 * n.co[1] - n.hr[1])
            n.hl_type = n.hr_type = "ALIGNED"

    def release(self):
        self.dragging = False

    def pop(self):
        if self.nodes:
            self.nodes.pop()
        self.dragging = False

    def reset(self):
        self.nodes = []
        self.dragging = False

    def resolved(self, closed=False, cursor=None):
        """Nodes with VECTOR handles placed the way Blender places them.

        ``cursor`` appends a rubber-band preview point.
        """
        nodes = [n.copy() for n in self.nodes]
        if cursor is not None:
            nodes.append(Node(cursor, cursor, cursor, hl_type="VECTOR", hr_type="VECTOR"))
        k = len(nodes)
        for i, n in enumerate(nodes):
            prev = nodes[i - 1] if (closed or i > 0) and k > 1 else None
            nxt = nodes[(i + 1) % k] if (closed or i < k - 1) and k > 1 else None
            if n.hl_type == "VECTOR":
                n.hl = _third(n.co, prev.co) if prev else n.co
            if n.hr_type == "VECTOR":
                n.hr = _third(n.co, nxt.co) if nxt else n.co
        return nodes

    def to_path(self, closed=False):
        return Path(self.resolved(closed), closed)


def _third(a, b):
    return (a[0] + (b[0] - a[0]) / 3.0, a[1] + (b[1] - a[1]) / 3.0)
