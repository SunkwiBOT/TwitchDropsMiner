"""Stub for PIL.ImageTk (headless web mode - never exercised)."""


class PhotoImage:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("PIL stub in headless web mode: no Tk image support")


class BitmapImage(PhotoImage):
    pass
