"""Run inside Blender: blender -b --factory-startup --python tests/blender_smoke.py"""

import math
import os
import sys
import traceback

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import illustrator_curves  # noqa: E402
from illustrator_curves import bridge  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (" " + detail if detail else ""))
    if not cond:
        failures.append(name)


def area(obj):
    paths, _, _ = bridge.read_paths(obj)
    return sum(p.area(1e-4) for p in paths)


def mesh_area(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    a = sum(p.area for p in me.polygons)
    ev.to_mesh_clear()
    return a


def select_only(*objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def run():
    illustrator_curves.register()
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)

    bpy.ops.curve.illu_add_rectangle(width=2, height=2, location=(0, 0, 0))
    a = bpy.context.active_object
    bpy.ops.curve.illu_add_ellipse(radius_x=1, radius_y=1, location=(1, 1, 0))
    b = bpy.context.active_object
    check("rectangle area", abs(area(a) - 4) < 1e-3, str(area(a)))
    check("ellipse area", abs(area(b) - math.pi) < 5e-3, str(area(b)))
    check("ellipse is filled 2D curve", b.data.dimensions == "2D" and b.data.fill_mode == "BOTH")

    lens = math.pi / 4  # quarter circle overlapping the square's corner
    expected = {"UNION": 4 + math.pi - lens, "INTERSECT": lens, "DIFFERENCE": 4 - lens,
                "EXCLUDE": 4 + math.pi - 2 * lens}
    for op, exp in expected.items():
        select_only(a, b)
        bpy.ops.curve.illu_boolean(operation=op, keep_originals=True)
        res = bpy.context.active_object
        check("boolean %s" % op, res not in (a, b) and abs(area(res) - exp) < 5e-3,
              "%.4f vs %.4f, %d splines" % (area(res), exp, len(res.data.splines)))
        bridge.remove_objects([res])

    # transformed operand
    b.location = (5, 5, 0)
    b.rotation_euler = (0, 0, 0.3)
    b.scale = (2, 2, 2)
    select_only(a, b)
    bpy.ops.curve.illu_boolean(operation="UNION", keep_originals=True)
    res = bpy.context.active_object
    check("union of disjoint transformed objects", abs(area(res) - (4 + 4 * math.pi)) < 2e-2,
          "%.4f, %d splines" % (area(res), len(res.data.splines)))
    bridge.remove_objects([res])

    # boolean replacing the inputs
    b.location = (1, 1, 0)
    b.rotation_euler = (0, 0, 0)
    b.scale = (1, 1, 1)
    select_only(a, b)
    bpy.ops.curve.illu_boolean(operation="UNION")
    res = bpy.context.active_object
    check("union removes originals", len(bpy.context.scene.objects) == 1)

    select_only(res)
    bpy.ops.curve.illu_offset(distance=0.25, join="ROUND")
    off = bpy.context.active_object
    check("offset creates new object", off is not res and area(off) > area(res))
    check("offset result is the only selection", list(bpy.context.selected_objects) == [off])
    bpy.ops.curve.illu_offset(distance=-0.25, join="MITER", keep_original=False)
    check("inward offset in place", bpy.context.active_object is off and abs(area(off) - area(res)) < 0.1,
          "%.4f vs %.4f" % (area(off), area(res)))

    bpy.ops.curve.illu_add_star(points=5, radius_outer=1, radius_inner=0.5, location=(6, 0, 0))
    star = bpy.context.active_object
    n0 = len(star.data.splines[0].bezier_points)
    bpy.ops.curve.illu_fillet(radius=0.1)
    check("fillet object mode doubles corners", len(star.data.splines[0].bezier_points) == 2 * n0,
          "%d -> %d" % (n0, len(star.data.splines[0].bezier_points)))

    bpy.ops.curve.illu_add_polygon(sides=6, radius=1, location=(0, 6, 0))
    hexa = bpy.context.active_object
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.curve.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    hexa.data.splines[0].bezier_points[0].select_control_point = True
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.curve.illu_fillet(radius=0.2, mode="CHAMFER")
    check("fillet edit mode stays in edit mode", bpy.context.mode == "EDIT_CURVE")
    bpy.ops.object.mode_set(mode="OBJECT")
    check("fillet edit mode affects selected only", len(hexa.data.splines[0].bezier_points) == 7,
          str(len(hexa.data.splines[0].bezier_points)))

    curve = bridge.new_curve_data("Wave")
    sp = curve.splines.new("POLY")
    sp.points.add(99)
    for i, p in enumerate(sp.points):
        x = i / 99 * 4
        p.co = (x, math.sin(x * math.pi), 0, 1)
    wave = bpy.data.objects.new("Wave", curve)
    bpy.context.collection.objects.link(wave)
    select_only(wave)
    bpy.ops.curve.illu_simplify(tolerance=2e-3)
    s = wave.data.splines[0]
    check("simplify polyline to bezier", s.type == "BEZIER" and len(s.bezier_points) < 20, str(len(s.bezier_points)))

    select_only(wave)
    bpy.ops.curve.illu_resample(mode="COUNT", count=9, smooth=False, keep_corners=False)
    check("resample to a point count", len(wave.data.splines[0].bezier_points) == 9,
          str(len(wave.data.splines[0].bezier_points)))

    doubles = bridge.new_curve_data("Doubles")
    sp = doubles.splines.new("POLY")
    sp.points.add(3)
    for p, co in zip(sp.points, ((0, 0), (1, 0), (1, 0), (2, 0))):
        p.co = (co[0], co[1], 0, 1)
    doubles_obj = bpy.data.objects.new("Doubles", doubles)
    bpy.context.collection.objects.link(doubles_obj)
    select_only(doubles_obj)
    bpy.ops.curve.illu_remove_doubles(distance=0.001)
    check("remove doubles", len(doubles_obj.data.splines[0].bezier_points) == 3,
          str(len(doubles_obj.data.splines[0].bezier_points)))

    select_only(wave)
    bpy.ops.curve.illu_outline_stroke(width=0.2, cap="ROUND", keep_original=True)
    out = bpy.context.active_object
    check("outline stroke of open wave", out is not wave and len(out.data.splines) >= 1 and area(out) > 0.5,
          "%.3f" % area(out))

    # spline-level booleans inside one object
    bpy.ops.curve.illu_add_rectangle(width=2, height=2, location=(10, 0, 0))
    single = bpy.context.active_object
    bpy.context.scene.cursor.location = (10, 0, 0)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.curve.illu_add_ellipse(radius_x=1, radius_y=1)
    bpy.ops.object.mode_set(mode="OBJECT")
    check("shape added into edit object", len(single.data.splines) == 2)
    select_only(single)
    bpy.ops.curve.illu_boolean(operation="UNION")
    check("union of splines in one object", abs(area(bpy.context.active_object) - 4) < 5e-3,
          "%.4f" % area(bpy.context.active_object))

    # touching results must still be filled correctly by Blender's 2D fill
    bpy.ops.curve.illu_add_rectangle(width=1, height=1, location=(20.5, 0.5, 0))
    t1 = bpy.context.active_object
    bpy.ops.curve.illu_add_rectangle(width=1, height=1, location=(21.5, 1.5, 0))
    t2 = bpy.context.active_object
    select_only(t1, t2)
    bpy.ops.curve.illu_boolean(operation="UNION")
    res = bpy.context.active_object
    check("corner-touching union filled by Blender", abs(mesh_area(res) - 2.0) < 1e-3,
          "mesh %.4f, %d splines" % (mesh_area(res), len(res.data.splines)))

    bpy.ops.curve.illu_add_star(points=5, radius_outer=1, radius_inner=0.45, location=(30, 0, 0))
    st = bpy.context.active_object
    bpy.ops.curve.illu_offset(distance=0.12, join="MITER")
    so = bpy.context.active_object
    bpy.context.scene.cursor.location = (30, 0, 0)
    bpy.ops.curve.illu_add_ellipse(radius_x=1, radius_y=1, location=(30, 0, 0))
    el = bpy.context.active_object
    select_only(el, st, so)
    bpy.ops.curve.illu_boolean(operation="EXCLUDE")
    res = bpy.context.active_object
    check("exclude with touching islands filled by Blender", abs(mesh_area(res) - area(res)) < 2e-3,
          "mesh %.4f vs path %.4f" % (mesh_area(res), area(res)))

    def world_size(obj):
        bmin = [math.inf, math.inf, math.inf]
        bmax = [-math.inf, -math.inf, -math.inf]
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        mw = ev.matrix_world
        for v in me.vertices:
            p = mw @ v.co
            for i in range(3):
                bmin[i] = min(bmin[i], p[i])
                bmax[i] = max(bmax[i], p[i])
        ev.to_mesh_clear()
        return tuple(bmax[i] - bmin[i] for i in range(3))

    bpy.ops.curve.illu_add_rectangle(width=2, height=1, location=(0, -8, 0))
    scaled = bpy.context.active_object
    scaled.scale = (4, 0.5, 1)
    select_only(scaled)
    bpy.ops.curve.illu_outline_stroke(width=0.2, join="MITER", cap="BUTT", keep_original=True)
    ol = bpy.context.active_object
    sx, sy, sz = world_size(ol)
    check("outline of a scaled curve stays the visual size",
          ol is not scaled and abs(sx - 8.2) < 0.03 and abs(sy - 0.7) < 0.03
          and abs(ol.scale.x - 4) < 1e-5 and abs(ol.scale.y - 0.5) < 1e-5,
          "size (%.4f %.4f %.4f) scale %s" % (sx, sy, sz, tuple(ol.scale)))

    bpy.ops.curve.illu_add_rectangle(width=2, height=2, location=(0, -12, 0))
    unit = bpy.context.active_object
    select_only(unit)
    bpy.ops.curve.illu_outline_stroke(width=0.2, join="MITER", cap="BUTT")
    ol1 = bpy.context.active_object
    sx, sy, _ = world_size(ol1)
    check("outline at scale 1", abs(sx - 2.2) < 0.03 and abs(sy - 2.2) < 0.03, "(%.4f %.4f)" % (sx, sy))

    bpy.ops.curve.illu_add_rectangle(width=2, height=1, location=(0, -16, 0))
    bv = bpy.context.active_object
    bv.scale = (3, 3, 3)
    bv.data.bevel_depth = 0.05
    bv.data.extrude = 0.02
    bv.data.dimensions = "3D"
    select_only(bv)
    bpy.ops.curve.illu_outline_stroke(width=0.2, join="MITER", keep_original=True)
    olb = bpy.context.active_object
    sx, sy, sz = world_size(olb)
    check("scaled outline is not thickened by the copied bevel",
          olb.data.bevel_depth == 0 and olb.data.extrude == 0
          and abs(sx - 6.2) < 0.04 and abs(sy - 3.2) < 0.04 and sz < 0.02,
          "size (%.4f %.4f %.4f) bevel %s extrude %s" % (sx, sy, sz, olb.data.bevel_depth, olb.data.extrude))

    bpy.ops.curve.illu_add_rectangle(width=2, height=1, location=(0, -20, 0))
    neg = bpy.context.active_object
    neg.scale = (-2, 1.5, 1)
    select_only(neg)
    bpy.ops.curve.illu_outline_stroke(width=0.2, join="MITER", cap="BUTT")
    oln = bpy.context.active_object
    sx, sy, _ = world_size(oln)
    check("negative scale keeps the outline the same size",
          abs(sx - 4.2) < 0.04 and abs(sy - 1.7) < 0.04
          and abs(oln.scale.x - (-2)) < 1e-5 and abs(oln.scale.y - 1.5) < 1e-5 and abs(oln.scale.z - 1) < 1e-5,
          "size (%.4f %.4f) scale %s" % (sx, sy, tuple(oln.scale)))

    bpy.ops.curve.illu_add_rectangle(width=2, height=2, location=(0, -24, 0))
    ofs = bpy.context.active_object
    ofs.scale = (2, 2, 2)
    select_only(ofs)
    bpy.ops.curve.illu_offset(distance=0.1, join="MITER")
    ofo = bpy.context.active_object
    sx, sy, _ = world_size(ofo)
    check("offset distance is in world units", abs(sx - 4.2) < 0.04 and abs(sy - 4.2) < 0.04, "(%.4f %.4f)" % (sx, sy))

    def plane_bounds(obj):
        maps = bridge.object_plane_maps(obj)
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        me = ev.to_mesh()
        a, b, c, d = maps[0]
        xs, ys = [], []
        for v in me.vertices:
            x, y = v.co.x, v.co.y
            xs.append(a * x + b * y)
            ys.append(c * x + d * y)
        ev.to_mesh_clear()
        return min(xs), min(ys), max(xs), max(ys)

    bpy.ops.curve.illu_add_rectangle(width=2, height=2, location=(0, 0, 0))
    turned = bpy.context.active_object
    turned.scale = (4, 0.5, 1)
    turned.rotation_euler = (0, 0, 0.7)
    select_only(turned)
    bpy.ops.curve.illu_outline_stroke(width=0.2, join="MITER", cap="BUTT")
    olt = bpy.context.active_object
    sb = plane_bounds(turned)
    ob = plane_bounds(olt)
    check("rotated non-uniform outline uses a uniform world width",
          abs(olt.scale.x - 4) < 1e-5 and abs(olt.rotation_euler.z - 0.7) < 1e-5
          and abs((ob[0] - sb[0]) + 0.1) < 0.03 and abs((ob[2] - sb[2]) - 0.1) < 0.03
          and abs((ob[1] - sb[1]) + 0.1) < 0.03 and abs((ob[3] - sb[3]) - 0.1) < 0.03,
          "src %s out %s scale %s" % (tuple(round(v, 4) for v in sb), tuple(round(v, 4) for v in ob), tuple(olt.scale)))

    parent = bpy.data.objects.new("ScaleParent", None)
    bpy.context.collection.objects.link(parent)
    parent.scale = (3, 0.5, 1)
    bpy.ops.curve.illu_add_rectangle(width=2, height=2, location=(0, 0, 0))
    child = bpy.context.active_object
    child.parent = parent
    child.location = (1, 2, 0)
    select_only(child)
    bpy.ops.curve.illu_outline_stroke(width=0.2, join="MITER", cap="BUTT")
    olc = bpy.context.active_object
    sb = plane_bounds(child)
    ob = plane_bounds(olc)
    check("parented outline keeps the parent and the world width",
          olc.parent == parent and abs(olc.scale.x - 1) < 1e-5 and abs(olc.location.x - 1) < 1e-5
          and abs((ob[0] - sb[0]) + 0.1) < 0.03 and abs((ob[2] - sb[2]) - 0.1) < 0.03
          and abs((ob[1] - sb[1]) + 0.1) < 0.03 and abs((ob[3] - sb[3]) - 0.1) < 0.03,
          "parent %s scale %s src %s out %s" % (olc.parent, tuple(olc.scale),
                                                tuple(round(v, 4) for v in sb), tuple(round(v, 4) for v in ob)))

    check("pen tool registered", hasattr(bpy.types, "CURVE_OT_illu_pen") or "curve.illu_pen" in dir(bpy.ops.curve))
    illustrator_curves.unregister()
    check("unregister clean", not hasattr(bpy.types.Scene, "illu_settings"))


try:
    run()
except Exception:
    traceback.print_exc()
    failures.append("exception")

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
