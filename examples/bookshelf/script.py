# SPDX-License-Identifier: GPL-3.0-or-later
"""Bookshelf with books: a walnut carcass with a face frame, stepped crown, recessed kick plinth and a shiplap
back, five shelves of cloth and leather books (standing, leaning, stacked), gold bands on the leather spines.
tags: bookshelf, shelf, books, bookcase, furniture, library, interior, wood, storage, walnut, realistic
0.9 x 0.34 x 1.86 m; books are beveled boxes walked along each shelf with a fixed seed (same shelf every run).
budget: 7500 (a furniture prop full of small parts)
"""
import random

import nighty as n

random.seed(7)
n.settings(detail="low", size=1.85, collection="Bookshelf")
walnut_z = n.surface("Shelf Walnut Z", "wood", color="#5e3c22", grain="Z", wear=0.15, dirt=0.3, size=0.8)
walnut_x = n.surface("Shelf Walnut X", "wood", color="#5e3c22", grain="X", wear=0.15, dirt=0.3, size=0.8)
back_wood = n.surface("Shelf Back", "wood", color="#3c2615", grain="X", wear=0.0, dirt=0.3, size=0.8)
gold = n.surface("Book Gold", "gold", wear=0.3, dirt=0.3, size=0.3)
cloth = [n.surface(f"Book Cloth {i}", "fabric", color=c, wear=0.15, dirt=0.25, size=0.3)
         for i, c in enumerate(("#58221e", "#243249", "#273e30", "#7a5f31", "#9c937d", "#2a2d31"))]   # muted cloth
leather = [n.surface(f"Book Leather {i}", "leather", color=c, wear=0.25, dirt=0.25, size=0.3)
           for i, c in enumerate(("#5a2a1a", "#3b2414", "#1f3324"))]

W, D, H, T = 0.9, 0.32, 1.8, 0.022        # carcass outer width, depth, height (to the crown), board thickness
PLINTH = 0.08
carcass = [n.box((T, D, H - PLINTH), at=(sx * (W / 2 - T / 2), 0, PLINTH + (H - PLINTH) / 2), bevel=0.002)
           for sx in (-1, 1)]
carcass.append(n.box((W - 2 * T, D, T), at=(0, 0, H - T / 2), bevel=0.002))      # top board
carcass = n.merge_parts(carcass, name="Carcass", weld=False)
n.paint(carcass, walnut_z)

# face frame on the front: two stiles and a top rail, 1 cm proud of the carcass
FF = 0.045
stiles = [n.box((FF, 0.02, H - PLINTH), at=(sx * (W / 2 - FF / 2 + 0.003), -D / 2 - 0.009, PLINTH + (H - PLINTH) / 2),
                bevel=0.003) for sx in (-1, 1)]
stiles = n.merge_parts(stiles, name="Stiles", weld=False)
n.paint(stiles, walnut_z)
top_rail = n.box((W - 2 * FF + 0.012, 0.018, 0.07), at=(0, -D / 2 - 0.009, H - 0.035), bevel=0.003, name="TopRail")
n.paint(top_rail, walnut_x)

# stepped crown on top, recessed kick plinth below
crown = n.merge_parts([n.box((W + 0.03, D + 0.03, 0.025), at=(0, -0.015, H + 0.0125), bevel=0.004),
                       n.box((W + 0.07, D + 0.05, 0.03), at=(0, -0.025, H + 0.04), bevel=0.006)],
                      name="Crown", weld=False)
n.paint(crown, walnut_x)
plinth = n.box((W - 0.02, D - 0.01, PLINTH), at=(0, 0.005, PLINTH / 2), name="Plinth")
n.chamfer(plinth, 0.006)
n.paint(plinth, walnut_x)

# shiplap back: horizontal boards with small gaps, just inside the carcass
back = n.planks((W - 2 * T, H - PLINTH - T), count=9, thickness=0.01, gap=0.003, plane="XZ",
                at=(0, D / 2 - 0.006, PLINTH + (H - PLINTH - T) / 2), seed=3, name="Back")
n.paint(back, back_wood)

# shelves (the lowest sits on the plinth)
shelf_z = [PLINTH, 0.43, 0.78, 1.13, 1.47]
shelves = [n.box((W - 2 * T, D - 0.018, 0.025), at=(0, -0.006, z + 0.0125), bevel=0.003) for z in shelf_z]
shelves = n.merge_parts(shelves, name="Shelves", weld=False)
n.paint(shelves, walnut_x)

# books: walk along each shelf, mostly standing, now and then a flat stack, a leaning one at the end
books = {}


def book(size, at, rot=None):
    """One book; leather ones get two gold bands across the spine (the spine faces -Y)."""
    is_leather = random.random() < 0.3
    m = random.choice(leather if is_leather else cloth)
    b = n.box(size, at=at, rot=rot, bevel=0.0018)       # a one-segment edge: ~90 books stay light
    books.setdefault(m.name, (m, []))[1].append(b)
    standing = rot is None and size[2] > size[0]
    if is_leather and standing:
        for dz in (-0.3, 0.32):
            band = n.box((size[0] + 0.002, 0.002, 0.007), at=(at[0], at[1] - size[1] / 2 - 0.0003,
                                                                at[2] + dz * size[2]))
            books.setdefault(gold.name, (gold, []))[1].append(band)


for z0 in shelf_z:
    base = z0 + 0.025
    x = -W / 2 + T + 0.008
    end = W / 2 - T - 0.015
    while x < end - 0.14:
        if random.random() < 0.12 and end - x > 0.26:          # a flat stack of 3-4 books
            w = random.uniform(0.17, 0.21)
            zz = base
            for _ in range(random.randint(3, 4)):
                th = random.uniform(0.025, 0.04)
                book((w, random.uniform(0.17, 0.21), th), (x + w / 2, -0.02, zz + th / 2 + 0.0005))
                zz += th + 0.0005
            x += w + 0.015
            continue
        th = random.uniform(0.022, 0.048)
        h = random.uniform(0.2, 0.3)
        book((th, random.uniform(0.18, 0.23), h), (x + th / 2, -0.035, base + h / 2 + 0.0005))
        x += th + random.uniform(0.0008, 0.003)
    if end - x > 0.12:                                          # the last gap: one book leaning on its neighbour
        book((0.03, 0.2, 0.24), (x + 0.055, -0.035, base + 0.12 * 0.94), rot=(0, -22, 0))
    elif end - x > 0.025:
        th, h = min(0.045, end - x - 0.002), random.uniform(0.2, 0.27)
        book((th, 0.2, h), (x + th / 2, -0.035, base + h / 2 + 0.0005))
book_parts = []
for name, (m, objs) in sorted(books.items()):
    part = n.merge_parts(objs, name=name.replace(" ", ""), weld=False)
    n.paint(part, m)
    book_parts.append(part)

parts = [carcass, stiles, top_rail, crown, plinth, back, shelves] + book_parts
n.ground(parts)
n.center(parts, "XY")
