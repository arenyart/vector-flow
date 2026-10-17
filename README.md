# Illustrator Curves for Blender

A Blender add-on that brings Adobe Illustrator–style vector tools to Blender curve objects:

| Illustrator | Here |
| --- | --- |
| Pen tool | **Pen** in the toolbar and sidebar. Click for corner points, drag for smooth points, Alt-drag to break handles, Shift for 45° steps, click the first point to close |
| Pathfinder: Unite, Minus Front, Intersect, Exclude | **Pathfinder** panel. Works on several selected curve objects (the active one is the base) or on the splines of one object |
| Object › Path › Offset Path | **Offset Path** with miter, round or bevel joins and a miter limit. Negative values shrink the shape |
| Object › Path › Outline Stroke | **Outline Stroke** with width, joins and butt, round or projecting caps. It can use the curve's bevel depth as the width |
| Live corners: Round, Inverted Round, Chamfer | **Round Corners** / **Chamfer Corners**. In Edit Mode it only affects the selected points |
| Object › Path › Simplify | **Simplify Path** refits curves with fewer points and keeps sharp corners |
| Resample (even points by count or distance) | **Resample Path** redistributes points evenly along the curve, keeping sharp corners |
| Merge by Distance | **Remove Doubles** welds neighboring points closer than a distance, and can close a path whose ends meet |
| Rectangle, Ellipse, Polygon, Star tools | **Add › Curve** and sidebar shape buttons, with optional corner radius |

All operators support Blender's *Adjust Last Operation* panel, so you can drag the offset distance, fillet radius and similar values and see the result live.

## Install

Requires Blender **4.2 or newer** (tested on 4.5 LTS).

1. Download the prebuilt [`releases/illustrator_curves-1.2.2.zip`](releases/illustrator_curves-1.2.2.zip), or build it yourself:
   ```bash
   blender --command extension build --source-dir illustrator_curves --output-dir dist
   ```
   You can also zip the `illustrator_curves/` folder yourself.
2. In Blender, go to *Edit › Preferences › Get Extensions*, open the ▾ menu, choose **Install from Disk…** and pick `dist/illustrator_curves-1.2.2.zip`.

For development, symlink the package into your extensions folder so edits are picked up on restart:

```bash
ln -s "$PWD/illustrator_curves" ~/.config/blender/4.5/extensions/user_default/illustrator_curves
```

## Use

Open the **Illustrator** tab in the 3D viewport sidebar (`N`).

To see every tool at once, run `blender --python examples/showcase.py`. It builds a demo scene with all the Pathfinder operations, an offset, an outline stroke and two corner styles.

### Pen tool

Start it from the toolbar (the **Pen** tool in Object Mode) or with the *Pen Tool* button.

- **Click**: add a corner point. **Click-drag**: add a smooth point and pull symmetric handles.
- **Alt-drag**: pull only the outgoing handle (cusp). **Shift**: constrain to 45°.
- **Click the first point** or press **C** to close the path. **Enter / Space** finishes an open path and starts the next one.
- **Backspace** removes the last point. **Esc / Right-click** finishes and exits.
- Navigation (middle mouse, wheel, numpad) keeps working while drawing.

*Target* chooses whether each path becomes its own object (best for Pathfinder) or is added to the active curve. *Plane* picks the drawing plane; *Auto* uses the active curve's plane or the current ortho view, otherwise the ground plane through the 3D cursor. Started from Edit Mode, the pen always adds to the edited curve.

### Pathfinder

Select two or more curve objects and click an operation. **Minus Front** subtracts every other selected object from the **active** one. With a single object selected, its splines are combined with each other.

The result keeps the original Bezier segments. Booleans cut the source curves at the intersections instead of turning them into polygons, so circles stay circles. Holes come out as nested splines, which Blender's 2D fill renders correctly. Shapes are projected onto the active object's local XY plane.

### Offset, Outline, Corners, Simplify

- **Offset Path** adds a new object by default (*Keep Original*). Positive distances grow the shape and negative ones shrink it. Open paths are outlined when growing. The distance is in scene units on the curve as it appears, so an object scale other than 1 does not change the result's size.
- **Outline Stroke** converts open or closed paths to filled outlines. Self-intersecting strokes are merged cleanly. The width is in scene units on the curve as it appears: a scaled, rotated or parented curve keeps that size, and the new object keeps the same scale. A bevel or extrude on the source is not copied onto the outline, so it is not thickened a second time.
- **Round Corners** detects corners by the angle between handle tangents, so smooth points are left alone. Radii are clamped so neighbouring fillets never overlap.
- **Simplify Path** also converts poly splines (for example, from Grease Pencil or the Draw tool) into clean Bezier curves.
- **Resample Path** spaces points evenly by arc length. *Count* sets how many points each path gets; *Length* targets a distance between them. *Smooth* fits a curve through the new points, and turning it off leaves straight segments. Sharp corners stay put.
- **Remove Doubles** welds neighboring control points closer than *Distance*. *Weld Ends* closes an open path when its first and last points fall inside that distance. In Edit Mode only selected points are merged.

## How it works

`illustrator_curves/geom/` is a self-contained, pure-Python 2D geometry library with no `bpy` imports:

- `planar.py` builds a planar overlay of polygon loops. It splits all edges at their intersections, merges coincident edges, then computes the winding number of every operand on both sides of each edge. A predicate (union, intersection, difference, XOR, nonzero, …) selects the boundary. Each edge carries a `(segment, t0, t1)` tag through the splits.
- `boolean.py` flattens curves adaptively, runs the overlay, then uses the tags to rebuild exact sub-segments of the original Beziers using de Casteljau splitting.
- `offset.py` builds offsets and outlines as unions of edge rectangles, join wedges and caps (a Minkowski-style approach). This avoids the self-intersection problems of naive offset curves. The result is refit with `fit.py`, a Schneider least-squares fitter with corner detection.
- `fillet.py` trims segments by arc length and inserts tangent circular arcs. Handle lengths use the standard `4/3·tan(θ/4)` cubic approximation.

The Blender layer (`bridge.py`, `ops_*.py`, `ui.py`) converts splines to and from this model.

## Tests

```bash
python3 -m pytest tests                                                 # geometry, no Blender needed
blender -b --factory-startup --python tests/blender_smoke.py            # operators inside Blender
```

## Known limitations

- Booleans and offsets treat each operand with the even-odd rule (like Blender's 2D fill) and work in the active object's XY plane. 3D curves are projected onto that plane.
- Offset and outline results are refit curves (within the *Precision* setting), not exact offsets. Exact offsets of Beziers are not themselves Beziers.
- NURBS splines are read through their control polygon.
- The pen draws in Object Mode. Started from Edit Mode, it temporarily switches out of Edit Mode and back again.
