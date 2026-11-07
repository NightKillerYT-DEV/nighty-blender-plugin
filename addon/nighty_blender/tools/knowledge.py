# SPDX-License-Identifier: GPL-3.0-or-later
# Know-how: get_guide (the guides, for AI apps that don't read MCP resources) and search_examples (verified
# example scripts built with the nighty library, found by keywords).

import math
import os
import re

from . import ToolError, image, text, action

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # addon/nighty_blender


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def find_dir(kind):
    """guides / examples: inside the addon when installed, at the repository root while developing."""
    for d in (os.path.join(PKG, kind), os.path.join(PKG, os.pardir, os.pardir, kind)):
        if os.path.isdir(d):
            return os.path.normpath(d)
    return None


def guide_topics():
    """{topic: (title, summary)} from guides/*.md (the skill file is not a topic)."""
    d = find_dir("guides")
    out = {}
    if not d:
        return out
    for f in sorted(os.listdir(d)):
        if not f.endswith(".md") or f == "ai-skill.md":
            continue
        lines = _read(os.path.join(d, f)).splitlines()
        title = lines[0].lstrip("# ").strip() if lines else f
        summary = next((l.strip() for l in lines[1:] if l.strip() and not l.startswith("#")), "")
        out[f[:-3]] = (title, summary)
    return out


def guide_text(topic):
    d = find_dir("guides")
    if not d:
        return None
    path = os.path.join(d, topic + ".md")
    if not re.fullmatch(r"[a-z0-9-]+", topic or "") or not os.path.isfile(path):
        return None
    return _read(path)


@action("get_guide",
      "Nighty's modeling guides (the same as the MCP resources nighty-blender://guide/<topic>). Without a topic: "
      "the list. Read workflow first (library and the recipes only for a code build the person asked for).",
      {"type": "object", "properties": {"topic": {"type": "string", "description": "A topic from the list."}}},
      changes=False)
def get_guide(ctx, args):
    topics = guide_topics()
    topic = (args.get("topic") or "").strip().lower()
    if not topic or topic in ("list", "index"):
        return "Guides (blender_guide { topic }):\n" + "\n".join(f"- {k}: {t}. {s}" for k, (t, s) in topics.items())
    body = guide_text(topic)
    if body is None:
        raise ToolError(f"No guide {topic!r}. Topics: {', '.join(topics)}.")
    return body


# ---------- examples ----------

_INDEX = {"key": None, "docs": []}
_WORD = re.compile(r"[a-z0-9]+")


def _meta(script):
    """Title, tags and description from an example script's docstring."""
    m = re.match(r'\s*(?:#[^\n]*\n\s*)*"""(.*?)"""', script, re.S)
    doc = m.group(1).strip() if m else ""
    lines = doc.splitlines()
    title = lines[0].strip() if lines else ""
    tags, desc = [], []
    for l in lines[1:]:
        if l.lower().startswith("tags:"):
            tags = [t.strip() for t in l.split(":", 1)[1].split(",") if t.strip()]
        elif l.strip():
            desc.append(l.strip())
    return title, tags, " ".join(desc)


def _load_index():
    d = find_dir("examples")
    if not d:
        return []
    names = sorted(n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n, "script.py")))
    key = (d, tuple((n, os.path.getmtime(os.path.join(d, n, "script.py"))) for n in names))
    if _INDEX["key"] == key:
        return _INDEX["docs"]
    docs = []
    for n in names:
        script = _read(os.path.join(d, n, "script.py"))
        title, tags, desc = _meta(script)
        calls = re.findall(r"\bn\.([a-z_]+)\(", script)
        words = (_WORD.findall((title + " " + " ".join(tags)).lower()) * 3 + _WORD.findall(n.replace("_", " ")) * 2
                 + _WORD.findall(desc.lower()) + [c.replace("_", " ") for c in calls])
        tokens = []
        for w in words:
            tokens += w.split()
        verify = None
        vp = os.path.join(d, n, "verify.json")
        if os.path.isfile(vp):
            import json
            try:
                v = json.loads(_read(vp))
                verify = {"pass": v.get("pass"), "triangles": v.get("triangles"), "budget": v.get("budget")}
            except ValueError:
                verify = None
        low = [t.lower() for t in tags]
        style = "realistic" if "realistic" in low else "stylized" if "stylized" in low else None
        docs.append({"name": n, "title": title, "tags": tags, "desc": desc, "tokens": tokens, "verify": verify,
                     "style": style, "dir": os.path.join(d, n)})
    _INDEX.update(key=key, docs=docs)
    return docs


def _stem(w):
    for suffix in ("ies", "es", "s"):
        if len(w) > 4 and w.endswith(suffix):
            return w[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return w


def search(query, limit=3, style=None):
    """BM25 over the examples' titles, tags, descriptions and the library calls they use; style keeps only
    "realistic" or "stylized" examples."""
    docs = _load_index()
    if style:
        docs = [d for d in docs if d["style"] == style] or docs
    if not docs:
        return []
    q = [_stem(w) for w in _WORD.findall(str(query).lower())]
    if not q:
        return []
    k1, b = 1.2, 0.75
    toks = [[_stem(t) for t in d["tokens"]] for d in docs]
    avg = sum(len(t) for t in toks) / float(len(toks))
    n = len(docs)
    scores = []
    for d, t in zip(docs, toks):
        s = 0.0
        for w in set(q):
            df = sum(1 for tt in toks if w in tt)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            f = t.count(w)
            s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(t) / avg))
        scores.append(s)
    order = sorted(range(n), key=lambda i: -scores[i])
    return [(docs[i], round(scores[i], 2)) for i in order[:limit] if scores[i] > 0]


@action("search_examples",
      "Only when the person asked you to build a model in code: finds verified example scripts (nighty library, "
      "within a game triangle budget) by keywords, e.g. \"pistol\", \"wooden crate\"; style: realistic or stylized. "
      "Returns their code to adapt; image: true adds the best match's render. Models otherwise come from the "
      "person (import).",
      {"type": "object", "properties": {
          "query": {"type": "string"},
          "style": {"type": "string", "enum": ["realistic", "stylized"],
                    "description": "Only realistic or only stylized examples."},
          "limit": {"type": "integer", "description": "1-5 (default 2)."},
          "code": {"type": "boolean", "description": "Include the scripts (default true)."},
          "image": {"type": "boolean", "description": "Add the best match's render."}},
       "required": ["query"]},
      changes=False)
def search_examples(ctx, args):
    query = (args.get("query") or "").strip()
    if not query:
        raise ToolError("query: a few words about what you want to make.")
    limit = max(1, min(5, int(args.get("limit") or 2)))
    style = args.get("style")
    if style not in (None, "", "realistic", "stylized"):
        raise ToolError('style: "realistic" or "stylized".')
    hits = search(query, limit, style or None)
    if not hits:
        names = [d["name"] for d in _load_index()]
        return {"results": [], "examples": names, "hint": "No match; these exist."}
    with_code = args.get("code", True)
    rows = []
    for d, score in hits:
        row = {"name": d["name"], "title": d["title"], "style": d["style"], "tags": d["tags"], "score": score,
               "verify": d["verify"]}
        if d["desc"]:
            row["about"] = d["desc"]
        if with_code:
            row["code"] = _read(os.path.join(d["dir"], "script.py"))
        rows.append(row)
    out = [text({"results": rows, "use": "adapt the code in run_python (import nighty as n); then check "
                                         "{what: mesh}, look, measure"})]
    if args.get("image"):
        # the installed extension ships a 512 px render.jpg; a repo checkout also has the full render.png
        for picture, mime in (("render.jpg", "image/jpeg"), ("render.png", "image/png")):
            path = os.path.join(hits[0][0]["dir"], picture)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    out.append(image(f.read(), mime))
                break
    return out
