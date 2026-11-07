# SPDX-License-Identifier: GPL-3.0-or-later
# The one place that turns the registry into tools.json text, so the generator script and the "is it up to date" test
# produce byte-for-byte the same thing. (Leading underscore: the tool loader skips this module.)

import json
import os

from .tools import specs


def render():
    """The exact text tools.json should hold: every tool's spec, sorted by name, pretty-printed, with a newline."""
    return json.dumps(specs(), indent=2, ensure_ascii=False) + "\n"


def path():
    return os.path.join(os.path.dirname(__file__), "tools.json")
