# SPDX-License-Identifier: GPL-3.0-or-later
# The single live Session for this Blender run. __init__.register() makes it; the panel and operators read it through
# get_session(). Kept in its own tiny module so nothing has to import __init__.

_SESSION = None


def get_session():
    return _SESSION


def set_session(session):
    global _SESSION
    _SESSION = session
