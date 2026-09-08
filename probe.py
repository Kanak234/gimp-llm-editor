"""
Run this inside GIMP if something does not work.

  Filters ▸ Development ▸ Script-Fu ▸ Console  is Scheme, not Python.
  You want:  Filters ▸ Development ▸ Python-Fu ▸ Console

Paste the whole file in there and press Enter. It prints what your build
actually supports, which is the fastest way to find out why an operation
is missing.
"""

try:
    import gi
    try:
        gi.require_version("Gimp", "3.0")
        gi.require_version("Gegl", "0.4")
    except (ValueError, AttributeError):
        pass
    from gi.repository import Gimp, Gegl
    _HAS_GIMP = True
except Exception:
    _HAS_GIMP = False
    Gimp = None
    Gegl = None

if not _HAS_GIMP:
    print("GIMP 3.0 / GEGL Python bindings are not available in this environment.")
    print("Run this script inside GIMP: Filters ▸ Development ▸ Python-Fu ▸ Console")
else:
    if Gegl is not None and hasattr(Gegl, "init"):
        try:
            Gegl.init(None)
        except Exception:
            pass
    if hasattr(Gimp, "version") and hasattr(Gimp, "is_initialized") and Gimp.is_initialized():
        print("GIMP version:", Gimp.version())
    else:
        print("GIMP: Running standalone probe (outside GIMP GUI session)")

    ops = set(Gegl.list_operations()) if Gegl is not None else set()
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
    has_autocrop = False
    try:
        if hasattr(Gimp, "is_initialized") and Gimp.is_initialized():
            pdb = Gimp.get_pdb() if hasattr(Gimp, "get_pdb") else None
            if pdb is not None and hasattr(pdb, "lookup_procedure"):
                has_autocrop = pdb.lookup_procedure("plug-in-autocrop") is not None
    except Exception:
        pass
    print("has plug-in-autocrop:", has_autocrop)

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
