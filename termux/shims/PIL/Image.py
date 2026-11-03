"""Stub for PIL.Image (headless web mode - never exercised)."""


def _blocked(*args, **kwargs):
    raise RuntimeError("PIL stub in headless web mode: image handling unavailable")


open = new = _blocked


class UnidentifiedImageError(OSError):
    pass


class Resampling:
    LANCZOS = 1
    NEAREST = 0
    BICUBIC = 2
    BILINEAR = 3
    BOX = 4
    HAMMING = 5


class Image:
    pass
