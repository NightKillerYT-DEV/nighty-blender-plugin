# Rig checks for `blender_run_python`

Read-only scripts behind the checks in SKILL.md. They change nothing and return a `result` dictionary. They use only what `blender_run_python` already provides (`bpy`, `bmesh`, `mathutils`, `math`), so they run at the "safe" level. Replace the names in CAPITALS and show the numbers to the creator before fixing anything.

## 1. Weights

```python
ARMATURE = "ARMATURE_NAME"
MESHES = []          # empty = every mesh with an Armature modifier pointing at ARMATURE
TINY = 0.01          # weights below this count as noise
ROOT_BONES = {"Root"}

arm = bpy.data.objects[ARMATURE]
bones = {b.name for b in arm.data.bones}
if not MESHES:
    MESHES = [o.name for o in bpy.data.objects if o.type == "MESH" and any(
        m.type == "ARMATURE" and m.object == arm for m in o.modifiers)]

report = {}
for name in MESHES:
    ob = bpy.data.objects[name]
    groups = {g.index: g.name for g in ob.vertex_groups}
    stray = sorted(n for n in groups.values() if n not in bones)
    xs = [(ob.matrix_world @ v.co).x for v in ob.data.vertices]
    half = 0.02 * ((max(xs) - min(xs)) if xs else 0)  # centre strip ignored for leaks
    unweighted = over4 = bad_sum = on_root = leaks = 0
    most = 0
    for v, x in zip(ob.data.vertices, xs):
        ws = [(groups.get(g.group, "?"), g.weight) for g in v.groups
              if g.weight >= TINY and groups.get(g.group) in bones]
        if not ws:
            unweighted += 1
            continue
        most = max(most, len(ws))
        over4 += len(ws) > 4
        bad_sum += abs(sum(w for _, w in ws) - 1.0) > 0.01
        on_root += any(n in ROOT_BONES for n, _ in ws)
        # Character faces -Y (Blender front view): its left side is +X.
        leaks += any((n.startswith("Left") and x < -half) or (n.startswith("Right") and x > half)
                     for n, _ in ws)
    report[name] = {"vertices": len(xs), "unweighted": unweighted, "max_influences": most,
                    "over_4": over4, "not_normalized": bad_sum, "on_root": on_root,
                    "left_right_leaks": leaks, "groups_without_bone": stray}
result = report
```

Pass: `unweighted`, `over_4`, `not_normalized`, `on_root` and `left_right_leaks` all 0, and `groups_without_bone` empty. The leak test assumes R15 names (`Left...`, `Right...`) and a character facing -Y; for a custom creature, rename or skip it.

## 2. Skeleton, transforms and R15 budgets

```python
ARMATURE = "ARMATURE_NAME"
PARTS = {
    "head": (["Head_Geo"], 4000),
    "torso": (["UpperTorso_Geo", "LowerTorso_Geo"], 1750),
    "left_arm": (["LeftUpperArm_Geo", "LeftLowerArm_Geo", "LeftHand_Geo"], 1248),
    "right_arm": (["RightUpperArm_Geo", "RightLowerArm_Geo", "RightHand_Geo"], 1248),
    "left_leg": (["LeftUpperLeg_Geo", "LeftLowerLeg_Geo", "LeftFoot_Geo"], 1248),
    "right_leg": (["RightUpperLeg_Geo", "RightLowerLeg_Geo", "RightFoot_Geo"], 1248),
}

def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)

def unapplied(ob):
    return any(abs(s - 1) > 1e-4 for s in ob.scale) or any(abs(r) > 1e-4 for r in ob.rotation_euler)

arm = bpy.data.objects[ARMATURE]
missing, budgets, total = [], {}, 0
for part, (names, limit) in PARTS.items():
    count = 0
    for n in names:
        ob = bpy.data.objects.get(n)
        if ob is None or ob.type != "MESH":
            missing.append(n)
        else:
            count += tris(ob)
    total += count
    budgets[part] = {"tris": count, "max": limit, "ok": count <= limit}

at_origin = {}
for b in ("Root", "LowerTorso"):
    bone = arm.data.bones.get(b)
    at_origin[b] = None if bone is None else round((arm.matrix_world @ bone.head_local).length, 4)

meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.parent == arm]
result = {
    "bones": len(arm.data.bones),
    "missing_geo": missing,
    "budgets": budgets,
    "total_tris": total, "total_ok": total <= 10742,
    "distance_from_origin_m": at_origin,
    "unapplied_transforms": [o.name for o in [arm] + meshes if unapplied(o)],
    "shape_keys_not_zero": [f"{o.name}:{k.name}" for o in meshes if o.data.shape_keys
                            for k in o.data.shape_keys.key_blocks[1:] if abs(k.value) > 1e-4],
}
```

Pass: `missing_geo` empty, every budget `ok`, `total_ok` true, Root and LowerTorso at 0 (a few tenths of a millimetre is noise), no unapplied transforms, no shape key left above 0. For a custom creature, drop `PARTS` and keep the transform and shape-key lines.

## 3. Dynamic head mapping

```python
HEAD, ARMATURE = "Head_Geo", "ARMATURE_NAME"
REQUIRED = {
    "LeftEyeClosed", "RightEyeClosed", "EyesLookDown", "JawDrop", "Pucker",
    "LeftLipCornerPuller", "RightLipCornerPuller", "ChinRaiser", "ChinRaiserUpperLip",
    "LeftCheekRaiser", "RightCheekRaiser", "LeftInnerBrowRaiser", "RightInnerBrowRaiser",
    "LeftLipCornerDown", "RightLipCornerDown", "LeftLowerLipDepressor", "RightLowerLipDepressor",
}
head = bpy.data.objects[HEAD]
arm = bpy.data.objects[ARMATURE]
props = {k: head[k] for k in head.keys() if isinstance(head[k], str)}
root_joint = props.get("RootFaceJoint")
poses = {v for k, v in props.items() if k != "RootFaceJoint"}
base = {p for pose in poses for p in pose.split("_")}
face_bones = []
if root_joint and root_joint in arm.data.bones:
    face_bones = [b.name for b in arm.data.bones[root_joint].children_recursive]
action = arm.animation_data.action if arm.animation_data else None
result = {
    "root_face_joint": root_joint,
    "root_joint_exists": bool(root_joint and root_joint in arm.data.bones),
    "face_joints": len(face_bones), "face_joints_ok": len(face_bones) < 50,
    "mapped_frames": len(poses),
    "action_frame_range": tuple(action.frame_range) if action else None,
    "missing_for_marketplace": sorted(REQUIRED - base),
}
```

Pass: the root face joint exists, fewer than 50 face joints, one mapped property per posed frame (compare `mapped_frames` with the action's last frame), and `missing_for_marketplace` empty for a head that will be sold. The property names and the frame-0 entry must follow Roblox's "create basic heads" guide exactly; this script checks the values, not the naming scheme.

<!-- SPDX-FileCopyrightText: 2026 NightyCode -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
