---
name: nighty-blender-rigging
description: Use when rigging or skinning a model in Blender for Roblox through Nighty Blender 2 - R15 avatars and bodies, dynamic heads with FACS face poses, creature or prop rigs, weight fixes, FBX export settings and testing in Studio.
metadata:
  author: NightyCode
  version: "2.0"
  origin: nighty-blender-v2
  as_of: 2026-11
  license: GPL-3.0-or-later
---

# Rigging and skinning for Roblox

Takes a finished, game-ready mesh to a rig Roblox accepts: the right skeleton, clean weights, face poses for dynamic heads, the right FBX settings, and a test in Studio. Every Roblox number here was read on create.roblox.com in Nov 2026: re-check the page before a Marketplace upload.

## Before you start

- The mesh is finished first: retopo, UVs and bake are done (nighty-blender-fix-model or nighty-blender-modeling). Rigging comes **last**; changing topology after skinning means skinning again.
- Animated meshes want quads and clean edge loops: **3 loops around every bending joint** (elbow, knee, knuckle, neck), cylinders with at least 6 sides (8 better). Triangles are fine where nothing bends.
- Nighty Blender 2 (the `blender_*` tools in Nighty Vault's MCP) has no rigging tool and no AI generation. Rigging is `blender_run_python` work **on the creator's request** (armature and pose operators are allowed at the "safe" level), or done by the creator in Blender while you check it with numbers. One logical change per call, so one `blender_undo` takes it back; set `blender_undo { checkpoint: "before-bind" }` before binding.
- **Rigs do not survive `blender_import`:** it brings a mesh in posed, without its armature, and says so in the triage report. Use it for the unrigged mesh. A rigged file or Roblox's R15 templates: the creator opens or imports them in Blender themselves (File > Open or File > Import), then you check with `blender_scene`.
- `blender_status` (paired, the safety level), `blender_scene`; with Nighty Vault, `context_pack` for the game's style and scale pages.
- Work on a saved copy: ask the creator to save first (skinning changes are hard to undo by hand).

## Pick the rig

| Need | Rig | Start from |
|---|---|---|
| Player avatar body, UGC body, R15 NPC that uses Roblox animations | **R15** (15 parts, fixed names) | Roblox's own R15 template files from the Creator Hub (the creator downloads them). Never invent or rename R15 bones |
| Avatar head with expressions | R15 head + **dynamic head** face joints and FACS poses | Roblox's dynamic head templates |
| Creature, monster, pet | Custom skeleton of `Bone`s, any names | A simple chain per limb; keep the bone count low |
| Door, chest, turret, prop with moving parts | No skin: separate parts joined by Motor6D or constraints in Studio | Split parts in Blender (`blender_mesh { op: "split_parts" }`), pivots at the hinge |

## R15 rules (create.roblox.com, character specifications)

**15 meshes with these exact names:** `Head_Geo`, `UpperTorso_Geo`, `LowerTorso_Geo`, `LeftUpperArm_Geo`, `LeftLowerArm_Geo`, `LeftHand_Geo`, `RightUpperArm_Geo`, `RightLowerArm_Geo`, `RightHand_Geo`, `LeftUpperLeg_Geo`, `LeftLowerLeg_Geo`, `LeftFoot_Geo`, `RightUpperLeg_Geo`, `RightLowerLeg_Geo`, `RightFoot_Geo`.

**Triangle budgets (maximum per body asset):**

| Asset | Parts | Max triangles |
|---|---|---|
| Dynamic head | Head_Geo | 4,000 |
| Torso | UpperTorso_Geo + LowerTorso_Geo | 1,750 |
| Each arm | UpperArm + LowerArm + Hand | 1,248 |
| Each leg | UpperLeg + LowerLeg + Foot | 1,248 |
| **Whole body** | all 15 | **10,742** (4,000 + 1,750 + 4 × 1,248) |

**Skeleton:**
- Hierarchy Root > HumanoidRootNode > LowerTorso > UpperTorso, with the head, arms and legs branching from their parents as in the template.
- **Root and LowerTorso sit at 0, 0, 0.**
- Export in I-pose, A-pose or T-pose; the upper arms may carry the rotation that makes the pose.
- Advanced R15 rigs may add up to 37 optional bones (fingers and more); each one used must keep its required name and parent, and its mesh must be skinned to it. Selling them needs HumanoidRigDescription (and a DigitsRigDescription per hand with finger bones), which is set up in Studio.

**Skinning:**
- **At most 4 bone influences per vertex.**
- **No weight on the Root bone.**
- Keep weights symmetric where the body is.
- Apply scale and rotation on the armature and every mesh (scale 1) before export.

## Dynamic heads (create.roblox.com, facial animation)

- Face joints sit under one **root face joint** (the templates call it `DynamicHead`) parented to the R15 head joint. Use **fewer than 50 face joints**.
- Poses are **joint poses on the timeline, not shape keys**:
  - **frame 0 is the neutral face**, every face joint at its rest value;
  - from **frame 1 on, one FACS pose per frame**; combination poses come after all base poses.
- Map every posed frame to its pose name or the head **fails import**: on `Head_Geo`, one **String custom property per frame** (property named after the frame, value the exact FACS pose name), plus a property `RootFaceJoint` whose value is the root face joint's name. Combination poses join base names with underscores (`Funneler_JawDrop_Pucker`). Follow the mapping table in Roblox's "create basic heads" guide exactly.
- Up to 50 base poses are possible. A head for your own game can use only what it needs (a simple character might use JawDrop, LeftEyeClosed and RightEyeClosed). **A head sold on the Marketplace needs these 17 base poses:**

| Eyes and brows | Mouth and jaw | Cheeks and chin |
|---|---|---|
| LeftEyeClosed | JawDrop | LeftCheekRaiser |
| RightEyeClosed | Pucker | RightCheekRaiser |
| EyesLookDown | LeftLipCornerPuller | ChinRaiser |
| LeftInnerBrowRaiser | RightLipCornerPuller | ChinRaiserUpperLip |
| RightInnerBrowRaiser | LeftLipCornerDown | |
| | RightLipCornerDown | |
| | LeftLowerLipDepressor | |
| | RightLowerLipDepressor | |

- "Left" and "Right" are the **character's own** left and right, not the viewer's.
- In Studio, play face poses as animation clips. Writing `FaceControls` values from a script gets overwritten by the animator on a dynamic head (reported from testing).

## Weight painting checks (numbers, not looks)

Run `references/rig-checks.md` script 1 after every binding or weight edit:

| Check | Pass |
|---|---|
| Vertices with no weight at all | 0 |
| Most influences on any vertex | 4 or fewer (after clean-up of tiny weights) |
| Weight on Root | none |
| Weights that do not sum to 1 | 0 (normalize all) |
| Left-side bones weighting right-side vertices (and the reverse) | 0 beyond the centre line strip |
| Vertex groups with no matching bone | 0 |

- **Automatic weights can fail without stopping the script.** The parent operator still reports success while Blender warns that bone heat weighting failed. Always count unweighted vertices afterwards. Usual causes: tiny scale (scale a copy up), duplicate or overlapping vertices, separate inner shells. Fix the mesh, then bind again.
- **Rigid parts** (eyes, teeth, armour plates, buckles, held props): weight every vertex 1.0 to one bone instead of painting gradients, or they bend like rubber.
- **Leaks across the centre:** armpits, crotch and inner thighs pick up the other side's bones. Remove them, then normalize.
- **Clean tiny weights** (under about 0.01) before limiting to 4 influences, then normalize.
- **Pre-bend** elbows and knees by 1 to 3 degrees in the rest pose so IK knows which way they bend.
- Modifier order on a skinned mesh: Mirror → Armature → (anything else). Apply Mirror before export.
- **Blender-only deformation does not export:** Preserve Volume, Corrective Smooth, B-bone curves and shape-key drivers do not reach Roblox. Judge the deformation with them off.
- Every shape key's value at 0 before export, or the mesh rests deformed.

**Range-of-motion test:** pose the rig at the extremes (arms up and forward, legs in a deep step and a high kick, head turned, fingers curled), `blender_look { mode: "matcap" }` from 4 views, and look for collapsing elbows, candy-wrapper wrists, and torso parts pulled by arm bones. Fix, then return to rest.

## Export to FBX

`blender_export` writes meshes only (no armature, no custom properties), so it suits the static parts and props of a Motor6D rig, not a skinned one. A skinned rig is exported with Blender's FBX exporter: by the creator, or with a short `blender_run_python` at the "full" safety level (file writes are off at "safe"; the level is the creator's to set). These settings:

| Setting | Value |
|---|---|
| Limit to | Selected objects (armature and its meshes, all unhidden) |
| Apply Scalings | FBX Unit Scale |
| Path Mode | Copy, with Embed Textures on |
| Armature: Add Leaf Bones | **Off** |
| Armature: Only Deform Bones | On (control bones stay in Blender) |
| Custom Properties | **On** (dynamic head mapping lives there) |
| Bake Animation | Off, unless the file carries animation; for a dynamic head: on, with NLA Strips, All Actions and Force Start/End Keying **off** |

Then read it back: `blender_check { what: "roundtrip", file: "<the .fbx>", format: "fbx" }` for sizes, triangles and maps, and script 5 of nighty-blender-fix-model `references/gate-scripts.md` (full level) for bones, one root, scale 1, the 15 names and the head's custom properties.

## Test in Studio

1. Import with the 3D Importer, rig type R15 (or the custom rig), Upload to Roblox off while testing.
2. Check through the Studio MCP (`execute_luau`, read-only): the 15 MeshParts by name, `Bone` count, a `FaceControls` instance under the head for a dynamic head, size about 5 studs tall for a standard body.
3. Studio's Avatar Setup tool (or the Studio MCP `auto_setup_avatar` when the creator asks) to preview animations, test clothing and accessories, and run validation. Fix every validation error in Blender, not in Studio.
4. Play the default walk, run, jump and a face animation; `screen_capture` from the front and side. Look for the same faults as the range-of-motion test.
5. Animations made for this rig are uploaded and owned by the experience owner, or they silently fail in live servers (nighty-roblox-characters).

Report: what passed, the triangle count per part, what was not checked (for example "Marketplace validation not run").

## Finishing

- With Nighty Vault: `add_lesson` for a rig mistake worth never repeating; `log_decision` for the skeleton choice.
- Scripting the character in game (Animator, Avatar Joint Upgrade, IK): nighty-roblox-characters. Importing other models: nighty-roblox-asset-import.

## Deeper

- `references/rig-checks.md`: read-only `blender_run_python` scripts for weights, the skeleton and part budgets, and the dynamic head mapping
- If you use Nighty Vault, see the Library pages "Nighty Blender for 3D models", "Rigging in Blender" and "Exporting and Validating Models for Roblox" (section "Hard limits")

<!-- SPDX-FileCopyrightText: 2026 NightyCode -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
