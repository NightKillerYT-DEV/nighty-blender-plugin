# SPDX-License-Identifier: GPL-3.0-or-later
"""Engine presets ("Made for"): file format, scale, axes, normal-map format, channel packing, texture names.
Plain data, no bpy. Sources: Roblox texture specifications and 3D Importer docs (FBX / OBJ / glTF; SurfaceAppearance
takes color, OpenGL tangent normal, grayscale roughness / metalness / emissive mask; ~1024 px; 20,000 triangles per
mesh; 1 stud = 0.28 m), glTF 2.0 (meters, +Y up, occlusion R / roughness G / metallic B), Unreal (cm, DirectX
normals, ORM), Unity (meters, OpenGL normals, URP metallic+smoothness, HDRP mask map), Godot 4 (glTF)."""

STUD = 0.28  # meters per stud (Roblox's own unit page)

# texture recipes: name pattern -> (kind, what)
#   kind 'rgb' / 'rgba' / 'gray'; what: a map key or a packing spec
ENGINES = {
    "roblox": {
        "label": "Roblox", "format": "fbx", "unit": "studs", "meters_per_unit": STUD, "normal": "opengl",
        "max_size": 1024, "tri_limit": 20000, "join": True, "lods": False,
        # Roblox's Blender settings: Apply Scalings 'FBX Units Scale' with Scale 0.01 gives 1 Blender unit = 1 stud;
        # our meters become studs with 0.01 / 0.28.
        "fbx": {"apply_scale_options": "FBX_SCALE_UNITS", "global_scale": 0.01 / STUD, "axis_forward": "-Z",
                "axis_up": "Y", "path_mode": "COPY", "embed_textures": True},
        "obj": {"global_scale": 1.0 / STUD, "forward_axis": "NEGATIVE_Z", "up_axis": "Y"},
        "textures": [
            ("{n}_Color.png", "color_alpha", "ColorMap"),
            ("{n}_Normal.png", "normal", "NormalMap"),
            ("{n}_Roughness.png", "roughness", "RoughnessMap"),
            ("{n}_Metalness.png", "metallic", "MetalnessMap"),
            ("{n}_Emissive.png", "emissive_mask", "EmissiveMaskContent"),
        ],
    },
    "unity": {
        "label": "Unity", "format": "fbx", "unit": "m", "meters_per_unit": 1.0, "normal": "opengl",
        "max_size": 4096, "join": False, "lods": True,
        "fbx": {"apply_scale_options": "FBX_SCALE_ALL", "global_scale": 1.0, "axis_forward": "-Z", "axis_up": "Y",
                "bake_space_transform": True, "path_mode": "STRIP", "embed_textures": False},
        "textures": [
            ("{n}_BaseMap.png", "color_alpha", "Base Map"),
            ("{n}_Normal.png", "normal", "Normal Map"),
            ("{n}_MetallicSmoothness.png", "unity_metallic_smoothness", "URP Metallic Map (smoothness in alpha)"),
            ("{n}_MaskMap.png", "unity_mask", "HDRP Mask Map"),
            ("{n}_Occlusion.png", "ao", "Occlusion Map"),
            ("{n}_Emission.png", "emission", "Emission Map"),
        ],
    },
    "unreal": {
        "label": "Unreal", "format": "fbx", "unit": "cm", "meters_per_unit": 0.01, "normal": "directx",
        "max_size": 4096, "join": False, "lods": True, "prefix": "SM_",
        # the FBX says meters; Unreal converts to centimeters on import (1 m = 100 units)
        "fbx": {"apply_scale_options": "FBX_SCALE_NONE", "global_scale": 1.0, "axis_forward": "-Z", "axis_up": "Y",
                "path_mode": "STRIP", "embed_textures": False},
        "textures": [
            ("T_{n}_BC.png", "color_alpha", "Base Color"),
            ("T_{n}_N.png", "normal", "Normal (DirectX)"),
            ("T_{n}_ORM.png", "orm", "Occlusion R, Roughness G, Metallic B (sRGB off)"),
            ("T_{n}_E.png", "emission", "Emissive Color"),
        ],
    },
    "godot": {
        "label": "Godot", "format": "glb", "unit": "m", "meters_per_unit": 1.0, "normal": "opengl",
        "max_size": 4096, "join": False, "lods": True, "textures": [],
    },
    "gltf": {
        "label": "glTF", "format": "glb", "unit": "m", "meters_per_unit": 1.0, "normal": "opengl",
        "max_size": 4096, "join": False, "lods": True, "textures": [],
    },
    "blender": {
        "label": "Blender", "format": "blend", "unit": "m", "meters_per_unit": 1.0, "normal": "opengl",
        "max_size": 8192, "join": False, "lods": True, "textures": [],
    },
}

ALIASES = {"gltf2": "gltf", "glb": "gltf", "three": "gltf", "threejs": "gltf", "ue": "unreal", "ue5": "unreal",
           "unreal engine": "unreal", "unity3d": "unity", "urp": "unity", "hdrp": "unity", "rbx": "roblox",
           "roblox studio": "roblox", "just blender": "blender", "none": "blender"}


def resolve(name):
    if not isinstance(name, str):
        return None
    k = name.strip().lower()
    k = ALIASES.get(k, k)
    return k if k in ENGINES else None


def needs_maps(engine):
    return engine != "blender"
