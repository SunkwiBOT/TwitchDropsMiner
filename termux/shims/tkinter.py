"""Headless stub for tkinter, used only on Termux/Android where CPython has no
_tkinter built in. The web mode (docker_main.py) never creates a Tk window; it only
needs `import tkinter as tk` in utils.py to succeed, plus the `tk.Tk` name for the
`set_root_icon` type annotation. Anything that actually tries to open a GUI fails
loudly instead of silently doing nothing.
"""


class Tk:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("tkinter stub in headless web mode: no GUI available")


class TclError(Exception):
    pass


def _blocked(*args, **kwargs):
    raise RuntimeError("tkinter stub in headless web mode: no GUI available")


# Commonly touched names, all blocked.
mainloop = _blocked
update = _blocked
destroy = _blocked


class _ModuleStub:
    def __getattr__(self, name):
        return _blocked


image = _ModuleStub()
