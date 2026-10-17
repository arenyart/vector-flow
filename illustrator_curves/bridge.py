"""Conversion between Blender curve data and :mod:`geom` paths."""

import bpy
from mathutils import Matrix, Vector

from .geom.path import Node, Path, assign_handle_types, paths_diagonal, world_plane_map


def is_curve(obj):
    return obj is not None and obj.type == "CURVE"


def selected_curves(context):
    return [o for o in context.selected_objects if is_curve(o)]


def ensure_object_mode(context):
    """Switch to object mode so edit-mode changes are flushed. Returns the previous mode."""
    prev = context.mode
    if prev != "OBJECT" and context.active_object is not None:
        bpy.ops.object.mode_set(mode="OBJECT")
    return prev


def restore_mode(prev):
    if prev == "EDIT_CURVE":
        bpy.ops.object.mode_set(mode="EDIT")


def _spline_meta(sp):
    return {
        "type": sp.type,
        "material_index": sp.material_index,
        "use_smooth": sp.use_smooth,
        "resolution_u": sp.resolution_u,
    }


def read_paths(obj, matrix=None):
    """Read all splines of a curve object as paths.

    ``matrix`` maps the object's local space into the working 2D space
    (only X and Y are used). Returns ``(paths, z, planar)`` where ``z`` is the
    mean depth and ``planar`` reports whether all points share it.
    """
    m = matrix if matrix is not None else Matrix.Identity(4)
    paths = []
    zs = []
    for sp in obj.data.splines:
        nodes = []
        if sp.type == "BEZIER":
            for bp in sp.bezier_points:
                co = m @ bp.co
                hl = m @ bp.handle_left
                hr = m @ bp.handle_right
                nodes.append(Node((co.x, co.y), (hl.x, hl.y), (hr.x, hr.y), bp.select_control_point,
                                  bp.handle_left_type, bp.handle_right_type))
                zs.append(co.z)
            if not nodes:
                continue
            path = Path(nodes, sp.use_cyclic_u, _spline_meta(sp))
        else:
            pts = []
            sel = []
            for p in sp.points:
                co = m @ p.co.xyz
                pts.append((co.x, co.y))
                sel.append(p.select)
                zs.append(co.z)
            if not pts:
                continue
            path = Path.from_polyline(pts, sp.use_cyclic_u, _spline_meta(sp))
            for node, s in zip(path.nodes, sel):
                node.selected = s
        paths.append(path)
    z = sum(zs) / len(zs) if zs else 0.0
    planar = all(abs(v - z) < 1e-4 * max(1.0, paths_diagonal(paths)) for v in zs)
    return paths, z, planar


def write_paths(curve, paths, z=0.0, clear=True, select=False):
    """Write paths into curve data as splines."""
    if clear:
        curve.splines.clear()
    for path in paths:
        if not path.nodes:
            continue
        meta = path.meta
        if meta.get("type") == "POLY" and not meta.get("modified"):
            sp = curve.splines.new("POLY")
            sp.points.add(len(path.nodes) - 1)
            for p, node in zip(sp.points, path.nodes):
                p.co = (node.co[0], node.co[1], z, 1.0)
                p.select = select or node.selected
        else:
            sp = curve.splines.new("BEZIER")
            sp.bezier_points.add(len(path.nodes) - 1)
            types = assign_handle_types(path)
            for bp, node in zip(sp.bezier_points, path.nodes):
                bp.handle_left_type = "FREE"
                bp.handle_right_type = "FREE"
                bp.co = (node.co[0], node.co[1], z)
                bp.handle_left = (node.hl[0], node.hl[1], z)
                bp.handle_right = (node.hr[0], node.hr[1], z)
            for bp, node, (lt, rt) in zip(sp.bezier_points, path.nodes, types):
                bp.handle_left_type = lt
                bp.handle_right_type = rt
                s = select or node.selected
                bp.select_control_point = s
                bp.select_left_handle = s
                bp.select_right_handle = s
        sp.use_cyclic_u = path.closed
        if "material_index" in meta:
            sp.material_index = meta["material_index"]
        if "use_smooth" in meta:
            sp.use_smooth = meta["use_smooth"]
        if "resolution_u" in meta:
            sp.resolution_u = meta["resolution_u"]
    curve.update_tag()


def new_curve_data(name):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "2D"
    curve.fill_mode = "BOTH"
    curve.resolution_u = 24
    return curve


def new_object_like(context, src, name):
    """New curve object sharing ``src``'s transform, settings, materials and collections.

    Location, rotation and scale are copied as channels (not via ``matrix_world``)
    so a scale other than 1 — including a negative scale or a parent — is the same
    on the result as on the source. Decomposing ``matrix_world`` can flip signs and
    drops shear from a non-uniform parent.
    """
    data = src.data.copy()
    data.splines.clear()
    data.name = name
    obj = bpy.data.objects.new(name, data)
    colls = src.users_collection or (context.collection,)
    for c in colls:
        c.objects.link(obj)
    obj.parent = src.parent
    obj.parent_type = src.parent_type
    obj.parent_bone = src.parent_bone
    obj.matrix_parent_inverse = src.matrix_parent_inverse.copy()
    obj.rotation_mode = src.rotation_mode
    obj.location = src.location
    obj.scale = src.scale
    obj.rotation_euler = src.rotation_euler
    obj.rotation_quaternion = src.rotation_quaternion
    obj.rotation_axis_angle = src.rotation_axis_angle
    obj.delta_location = src.delta_location
    obj.delta_rotation_euler = src.delta_rotation_euler
    obj.delta_rotation_quaternion = src.delta_rotation_quaternion
    obj.delta_scale = src.delta_scale
    return obj


def object_plane_maps(obj):
    """Local-XY ↔ world-unit maps for ``obj``'s plane. ``None`` if a scale axis is zero."""
    linear = obj.matrix_world.to_3x3()
    x = linear @ Vector((1.0, 0.0, 0.0))
    y = linear @ Vector((0.0, 1.0, 0.0))
    return world_plane_map((x.x, x.y, x.z), (y.x, y.y, y.z))


def remove_objects(objs):
    for o in objs:
        data = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if data is not None and data.users == 0:
            bpy.data.curves.remove(data)


def make_active(context, obj, deselect_others=True):
    if deselect_others:
        for o in context.selected_objects:
            o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def tolerance(paths, precision):
    """Absolute flattening tolerance derived from a relative precision."""
    return max(paths_diagonal(paths), 1e-6) * precision


def to_vec3(p, z=0.0):
    return Vector((p[0], p[1], z))
