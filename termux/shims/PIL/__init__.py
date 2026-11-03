"""Headless stub package for PIL on Termux.

utils.py does `from PIL.ImageTk import PhotoImage` and `from PIL import Image`
at module level, but both are only used by set_root_icon(), which the web mode
never calls. Pillow itself is not needed by the miner (avatars are rendered by
the browser straight from Twitch URLs), so we stub it instead of compiling it on
the phone. Any real image work raises loudly.
"""

__version__ = "0.0.0-stub"
__all__ = ["Image", "ImageTk"]


def _blocked(*args, **kwargs):
    raise RuntimeError("PIL stub in headless web mode: image handling unavailable")
