"""
Run this inside GIMP if something does not work.

  Filters ▸ Development ▸ Script-Fu ▸ Console  is Scheme, not Python.
  You want:  Filters ▸ Development ▸ Python-Fu ▸ Console

Paste the whole file in there and press Enter. It prints what your build
actually supports, which is the fastest way to find out why an operation
is missing.
"""

import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gegl

print("GIMP version:", Gimp.version())

ops = set(Gegl.list_operations())
print("GEGL operations installed:", len(ops))

wanted = [
    "gegl:brightness-contrast", "gegl:exposure", "gegl:shadows-highlights",
    "gegl:levels", "gegl:stretch-contrast", "gegl:saturation",
    "gegl:hue-chroma", "gegl:color-temperature", "gegl:gray", "gegl:sepia",
    "gegl:invert-gamma", "gegl:posterize", "gegl:threshold",
    "gegl:gaussian-blur", "gegl:motion-blur-linear", "gegl:unsharp-mask",
    "gegl:noise-reduction", "gegl:median-blur", "gegl:pixelize",
    "gegl:vignette", "gegl:softglow", "gegl:oilify", "gegl:cartoon",
    "gegl:emboss", "gegl:edge",
]

missing = [op for op in wanted if op not in ops]
print("missing:", missing if missing else "none")

print("has DrawableFilter:", hasattr(Gimp, "DrawableFilter"))
print("has TextLayer.new:", hasattr(getattr(Gimp, "TextLayer", None), "new"))
print("has plug-in-autocrop:",
      Gimp.get_pdb().lookup_procedure("plug-in-autocrop") is not None)

# Property names for one filter, so you can check the catalog matches.
try:
    img = Gimp.list_images()[0]
    drw = img.get_selected_drawables()[0]
    f = Gimp.DrawableFilter.new(drw, "gegl:unsharp-mask", "")
    cfg = f.get_config()
    print("unsharp-mask properties:",
          [p.name for p in cfg.list_properties()])
except Exception as e:
    print("open an image first to see filter properties:", e)
