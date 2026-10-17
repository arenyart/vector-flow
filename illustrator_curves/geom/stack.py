"""Order shapes into a vertical stack by footprint."""


def footprint(paths):
    """Area of the axis-aligned bounds of ``paths``, in the paths' own plane.

    A wider or taller shape ranks as larger. A path with no area, such as a
    straight line, ranks as the smallest.
    """
    xs = []
    ys = []
    for path in paths:
        if len(path.nodes) < 1:
            continue
        for pt in path.flatten(1e-4):
            xs.append(pt[0])
            ys.append(pt[1])
    if not xs:
        return 0.0
    return max(0.0, (max(xs) - min(xs)) * (max(ys) - min(ys)))


def stack_levels(sizes, step):
    """Z offsets that put the largest item on the bottom layer.

    ``sizes[i]`` is item ``i``'s footprint. The largest item gets offset 0, so
    its height can stay put. Each next-smaller item is one ``step`` higher.
    Equal footprints keep their original order, earlier items lower.
    """
    offsets = [0.0] * len(sizes)
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i], i))
    for rank, i in enumerate(order):
        offsets[i] = rank * float(step)
    return offsets
