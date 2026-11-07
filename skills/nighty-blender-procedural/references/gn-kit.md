# Geometry Nodes helper kit (tested)

The shared helper code for the procedural recipes: build a node group from Python, set modifier inputs on any Blender from 4.2 LTS to 5.x, bake to a mesh, and read the gate numbers. Tested headless on Blender 5.2.3 LTS (Nov 2026); the 4.2 paths follow the 4.2 API docs but were not run on 4.2.

## How to use it

- **Live, through Nighty Blender:** one `blender_run_python` call = this kit + one recipe from `recipes.md` + a few lines that build, attach, bake and return the report:

```python
ng = fence()                      # from recipes.md
obj, md = attach("PRP_fence", ng, {"Length": 16.0, "Height": 4.0, "Seed": 3})
bake_to_mesh(obj)                 # skip this while the creator is still tuning settings
result = report(obj)              # size in studs, tris, n-gons, open edges, islands, floating, min_z
```

  Put the object in a new collection first (pass `collection=`). On the `safe` level, delete the `import` line: `bpy`, `bmesh` and `math` are already loaded.
- **Headless test** (only the creator's own Blender install, never their config): save this block as `gn_kit.py` and the recipes as `recipes.py` (with `import bpy` and `from gn_kit import Tree, sock` on top) in a temp folder, then run the harness at the bottom with `blender.exe -b --factory-startup --python-exit-code 1 --python run_tests.py`. Point `BLENDER_USER_CONFIG`, `BLENDER_USER_SCRIPTS` and `BLENDER_USER_DATAFILES` at the temp folder too.

`report` is a quick in-Blender check for the loop. The real gates are still `blender_measure`, `blender_check { what: "mesh" }` and `blender_look` (see SKILL.md). Its floating test compares part bounding boxes (touching = within 0.2% of the diagonal), so it can miss a part that floats inside another part's box; `blender_check { what: "mesh" }` gives the real answer.

## The kit

```python
# Nighty procedural kit: small helpers to build Geometry Nodes trees from Python.
# Works on Blender 4.2 LTS to 5.x. Everything is built in STUDS; one Transform at the end scales to metres.
import bpy, bmesh, math

STUD = 0.28  # metres per stud


def avail(s):
    return getattr(s, "enabled", True) and not getattr(s, "is_unavailable", False)


def sock(coll, key):
    """Socket by index, or by name preferring an available one (Random Value, Math have duplicates)."""
    if isinstance(key, int):
        return coll[key]
    hits = [s for s in coll if key in (s.name, s.identifier, getattr(s, "label", ""))]
    if not hits:
        raise KeyError(f"no socket {key!r}; have {[s.name for s in coll]}")
    good = [s for s in hits if avail(s)]
    return (good or hits)[0]


def set_enum(node, name, value):
    """Enum lives as a node property (4.2) or a menu input socket (newer nodes in 5.x). Try both."""
    prop = name.lower().replace(" ", "_")
    if hasattr(node, prop):
        setattr(node, prop, value)
        return
    s = sock(node.inputs, name)
    s.default_value = value


class Tree:
    def __init__(self, name):
        old = bpy.data.node_groups.get(name)
        if old:  # rebuild in place, keep users
            self.ng = old
            old.nodes.clear()
            old.interface.clear()
        else:
            self.ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
        if hasattr(self.ng, "is_modifier"):
            self.ng.is_modifier = True
        self.nodes, self.links = self.ng.nodes, self.ng.links
        self.gin = self.nodes.new("NodeGroupInput")
        self.gout = self.nodes.new("NodeGroupOutput")
        self.ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    def inp(self, name, kind, default, lo=None, hi=None, desc=""):
        it = self.ng.interface.new_socket(name=name, in_out="INPUT",
                                          socket_type={"float": "NodeSocketFloat", "int": "NodeSocketInt"}[kind],
                                          description=desc)
        it.default_value = default
        if lo is not None:
            it.min_value = lo
        if hi is not None:
            it.max_value = hi
        return name

    def g(self, name):
        return sock(self.gin.outputs, name)

    def node(self, idname, props=None, ins=None):
        n = self.nodes.new(idname)
        for k, v in (props or {}).items():
            set_enum(n, k, v)
        for k, v in (ins or {}).items():
            s = sock(n.inputs, k)
            if isinstance(v, bpy.types.NodeSocket):
                self.link(v, s)
            else:
                s.default_value = v
        return n

    def link(self, a, b):
        lk = self.links.new(a, b)
        if lk is None or not lk.is_valid:
            raise RuntimeError(f"bad link {a.node.name}.{a.name} -> {b.node.name}.{b.name}")
        return lk

    def math(self, op, a, b=0.0, c=0.0):
        n = self.node("ShaderNodeMath", {"operation": op})
        for i, v in enumerate((a, b, c)):
            if isinstance(v, bpy.types.NodeSocket):
                self.link(v, n.inputs[i])
            else:
                n.inputs[i].default_value = v
        return n.outputs[0]

    def xyz(self, x=0.0, y=0.0, z=0.0):
        return self.node("ShaderNodeCombineXYZ", ins={"X": x, "Y": y, "Z": z}).outputs[0]

    def ground(self, geo):
        """Move geometry so its lowest point sits on z = 0 (random lean or noise can dip below)."""
        bb = self.node("GeometryNodeBoundBox", ins={"Geometry": geo})
        mn = self.node("ShaderNodeSeparateXYZ")
        self.link(sock(bb.outputs, "Min"), mn.inputs[0])
        lift = self.xyz(0.0, 0.0, self.math("MULTIPLY", mn.outputs[2], -1.0))
        return self.node("GeometryNodeTransform", ins={"Geometry": geo, "Translation": lift}).outputs[0]

    def finish(self, geo, triangulate=True):
        if triangulate:
            geo = self.node("GeometryNodeTriangulate", ins={"Mesh": geo}).outputs[0]
        geo = self.node("GeometryNodeTransform", ins={"Geometry": geo, "Scale": (STUD, STUD, STUD)}).outputs[0]
        self.link(geo, sock(self.gout.inputs, "Geometry"))
        return self.ng


def input_id(ng, name):
    return next(i.identifier for i in ng.interface.items_tree
                if getattr(i, "item_type", "") == "SOCKET" and i.in_out == "INPUT" and i.name == name)


def set_input(obj, md, name, value):
    """4.2 to 5.1: md[identifier]. 5.2+: md.properties.inputs.<identifier>.value."""
    ident = input_id(md.node_group, name)
    props = getattr(md, "properties", None)
    if props is not None and hasattr(props, "inputs"):
        setattr(getattr(props.inputs, ident), "value", value)
    else:
        md[ident] = value
    obj.update_tag()


def attach(name, ng, inputs=None, collection=None):
    me = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, me)
    (collection or bpy.context.scene.collection).objects.link(obj)
    md = obj.modifiers.new("Procedural", "NODES")
    md.node_group = ng
    for k, v in (inputs or {}).items():
        set_input(obj, md, k, v)
    return obj, md


def bake_to_mesh(obj):
    """Apply the GN modifier without operators: evaluated mesh (instances realized) becomes the object's data."""
    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    obj.modifiers.clear()
    obj.data = me
    return obj


def report(obj):
    """Numbers for the gates: size in studs, triangles, islands, floating islands, ground contact, n-gons."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    xs = [v.co for v in bm.verts]
    lo = [min(c[i] for c in xs) for i in range(3)]
    hi = [max(c[i] for c in xs) for i in range(3)]
    size = [(hi[i] - lo[i]) / STUD for i in range(3)]
    diag = math.dist(lo, hi)
    tris = sum(len(f.verts) - 2 for f in bm.faces)
    ngons = sum(1 for f in bm.faces if len(f.verts) > 4)
    open_edges = sum(1 for e in bm.edges if len(e.link_faces) != 2)  # 0 = closed (watertight) surface
    # islands by connected faces
    seen, islands = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, isl = [f], []
        seen.add(f.index)
        while stack:
            cur = stack.pop()
            isl.append(cur)
            for e in cur.edges:
                for nf in e.link_faces:
                    if nf.index not in seen:
                        seen.add(nf.index)
                        stack.append(nf)
        vs = {v for ff in isl for v in ff.verts}
        islands.append(([min(v.co[i] for v in vs) for i in range(3)], [max(v.co[i] for v in vs) for i in range(3)]))
    tol = 0.002 * diag  # within 0.2% of D counts as touching

    def gap(a, b):
        return math.sqrt(sum(max(0.0, a[0][i] - b[1][i], b[0][i] - a[1][i]) ** 2 for i in range(3)))
    # connectivity graph: every island must reach every other through touching boxes
    n = len(islands)
    adj = {i: [j for j in range(n) if j != i and gap(islands[i], islands[j]) <= tol] for i in range(n)}
    reach, stack = {0}, [0]
    while stack:
        for j in adj[stack.pop()]:
            if j not in reach:
                reach.add(j)
                stack.append(j)
    floating = n - len(reach) if n else 0
    bm.free()
    return {"size_studs": [round(s, 2) for s in size], "tris": tris, "ngons": ngons, "open_edges": open_edges,
            "islands": n, "floating": floating, "min_z": round(lo[2], 4)}
```

## What each helper is for

| Helper | Does |
|---|---|
| `sock(coll, key)` | Socket by index, name, identifier or label; prefers an available (enabled) one |
| `set_enum(node, name, value)` | Sets a node property if it exists, else the menu input socket of that name |
| `Tree(name)` | Creates or rebuilds `NB_...` in place, `is_modifier = True`, adds the Geometry output |
| `Tree.inp(name, kind, default, lo, hi, desc)` | Adds an exposed float or int input with limits |
| `Tree.node(idname, props, ins)` | Adds a node: enum properties first, then inputs (constants or links) |
| `Tree.link(a, b)` | Links and raises on a missing or invalid link |
| `Tree.math / xyz` | Math node and Combine XYZ shortcuts |
| `Tree.ground(geo)` | Moves the lowest point to z = 0 |
| `Tree.finish(geo)` | Triangulate, scale studs to metres (0.28), connect to the output |
| `set_input(obj, md, name, value)` | 5.2+: `md.properties.inputs`; older: `md[identifier]`; then `update_tag` |
| `attach(name, ng, inputs)` | New mesh object with the GN modifier and inputs set |
| `bake_to_mesh(obj)` | Evaluated mesh (instances realized) becomes the object's data; modifier removed |
| `report(obj)` | Size in studs, triangles, n-gons, open edges, islands, floating islands, lowest z |

## Headless test harness

Runs every recipe with its spec, sweeps seeds 0 to 5 on the random ones, and checks that changing an input on a live modifier changes the mesh. Last run: 22 of 22 passed on Blender 5.2.3 LTS.

```python
import sys, os, traceback, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
import gn_kit, recipes

print("BLENDER", bpy.app.version_string)

# name: (builder, inputs, expected size in studs (None = skip axis), tolerance fraction, tri ceiling)
CASES = {
    "fence":  (recipes.fence,  {"Length": 16.0, "Height": 4.0}, (16.6, None, 4.0), 0.05, 300),
    "stairs": (recipes.stairs, {"Steps": 8, "Width": 6.0}, (6.0, 12.0, 8.0), 0.05, 300),
    "rock":   (recipes.rock,   {"Size X": 4.0, "Size Y": 3.0, "Size Z": 2.5}, (4.0, 3.0, 2.5), 0.05, 400),
    "wall":   (recipes.wall,   {"Windows": 2}, (16.0, 1.0, 12.0), 0.05, 800),
    "tree":   (recipes.tree,   {}, (None, None, 14.0), 0.05, 2000),
    "barrel": (recipes.barrel, {}, (None, None, 3.0), 0.05, 600),
}
SEEDED = {"fence", "rock", "tree"}
results = {}
for name, (build, inputs, want, tol, ceiling) in CASES.items():
    ng = build()
    for seed in (range(6) if name in SEEDED else [None]):
        key = name if seed is None else f"{name}[seed {seed}]"
        try:
            ins = dict(inputs)
            if seed is not None:
                ins["Seed"] = seed
            obj, md = gn_kit.attach("PRP_" + key, ng, ins)
            gn_kit.bake_to_mesh(obj)
            r = gn_kit.report(obj)
            size_ok = all(w is None or abs(s - w) <= tol * w for s, w in zip(r["size_studs"], want))
            ok = (size_ok and r["tris"] <= ceiling and r["floating"] == 0 and r["ngons"] == 0
                  and r["open_edges"] == 0 and abs(r["min_z"]) < 1e-3)
            r.update(want=want, ceiling=ceiling, size_ok=size_ok, PASS=ok)
            results[key] = r
        except Exception:
            results[key] = {"PASS": False, "error": traceback.format_exc()}

# input path check: change a seed on a live modifier and confirm the mesh changes
try:
    ng = bpy.data.node_groups["NB_Rock"]
    o, md = gn_kit.attach("PRP_rock_seed", ng, {"Seed": 1})
    dg = bpy.context.evaluated_depsgraph_get(); dg.update()
    a = [v.co.copy() for v in o.evaluated_get(dg).data.vertices][:5]
    gn_kit.set_input(o, md, "Seed", 9)
    dg.update()
    b = [v.co.copy() for v in o.evaluated_get(dg).data.vertices][:5]
    results["set_input_changes_mesh"] = {"PASS": a != b, "has_properties": getattr(md, "properties", None) is not None}
except Exception:
    results["set_input_changes_mesh"] = {"PASS": False, "error": traceback.format_exc()}

for k, v in results.items():
    print("RES", k, "PASS" if v.get("PASS") else "FAIL", {x: y for x, y in v.items() if x not in ("PASS", "want", "ceiling")})
print("SUMMARY", sum(1 for v in results.values() if v.get("PASS")), "/", len(results))
```

<!-- SPDX-FileCopyrightText: 2026 NightyCode -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
