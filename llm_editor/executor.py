"""
The deterministic half of the plug-in.

The model proposes steps. Nothing here trusts them. Every step is checked
against catalog.py, every value is clamped, unknown ops and unknown args
are rejected, and only then does anything touch the image.

No code from the model is ever executed. There is no eval, no exec, and no
shell. The model's entire influence is "which op name, and which numbers".
"""

import math
import os
import shutil
import subprocess
import tempfile
import time

try:
    import gi
    try:
        gi.require_version("Gimp", "3.0")
        gi.require_version("Gegl", "0.4")
    except (ValueError, AttributeError):
        pass
    from gi.repository import Gimp, Gegl, Gio, GLib
    _HAS_GIMP = True
except Exception:
    _HAS_GIMP = False
    Gimp = None
    Gegl = None
    Gio = None
    GLib = None

try:
    from catalog import OPS
except ImportError:
    from .catalog import OPS


class StepError(Exception):
    pass


# ------------------------------------------------------------ capabilities

_gegl_ops_cache = None


def _gegl_ops():
    global _gegl_ops_cache
    if _gegl_ops_cache is None:
        try:
            if Gegl is not None and hasattr(Gegl, "init"):
                try:
                    Gegl.init(None)
                except Exception:
                    pass
            _gegl_ops_cache = set(Gegl.list_operations()) if Gegl is not None else set()
        except Exception:
            _gegl_ops_cache = set()
    return _gegl_ops_cache


def available_ops():
    """Op names this GIMP build can actually run.

    GEGL operation names drift a little between releases, so rather than
    guessing we ask GEGL what it has and drop anything missing. Whatever
    survives is what the model gets told about.
    """
    ops = _gegl_ops()
    out = set()
    for name, spec in OPS.items():
        need = spec.get("requires")
        if need == "rembg" and not helper_python():
            continue
        if spec["kind"] == "image":
            out.add(name)
        elif not ops or spec["gegl"] in ops:
            out.add(name)
    return out


def missing_ops():
    return sorted(set(OPS) - available_ops())


# --------------------------------------------------- the outside interpreter
#
# GIMP ships its own Python and we are not allowed to install packages into
# it. Anything that needs a real ML stack therefore runs in a separate
# interpreter -- a plain virtualenv the user created -- and talks to us
# through files on disk. Nothing from that process is trusted either: we
# hand it two paths and read back a PNG.

HELPER_ENVS = (
    os.environ.get("GIMP_AI_PYTHON"),
    os.path.expanduser("~/.gimp-ai/bin/python"),
    os.path.expanduser("~/.venvs/gimp-ai/bin/python"),
)

_helper_cache = -1


def helper_python():
    """Path to an interpreter that has rembg, or None."""
    global _helper_cache
    if _helper_cache != -1:
        return _helper_cache

    _helper_cache = None
    for path in HELPER_ENVS:
        if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
            continue
        try:
            probe = subprocess.run(
                [path, "-c", "import rembg"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=60,
            )
        except Exception:
            continue
        if probe.returncode == 0:
            _helper_cache = path
            break
    return _helper_cache


def _pump():
    """Let the panel repaint while we wait on a slow subprocess.

    run_plan is on the main thread, so a blocking wait would freeze the
    window. The Apply button is already disabled while busy, so briefly
    turning the main loop here cannot start a second edit.
    """
    try:
        ctx = GLib.MainContext.default()
        for _ in range(20):
            if not ctx.pending():
                break
            ctx.iteration(False)
    except Exception:
        pass


def _run_helper(args, log, timeout=600):
    """Run the helper script and stream its progress into the log."""
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    started = time.time()
    tail = []
    while True:
        if proc.poll() is not None:
            break
        if time.time() - started > timeout:
            proc.kill()
            raise StepError("background removal timed out")
        _pump()
        time.sleep(0.05)

    out = proc.stdout.read() if proc.stdout else ""
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("::"):
            log("    " + line[2:].strip())
        elif line:
            tail.append(line)

    if proc.returncode != 0:
        detail = tail[-1] if tail else f"exit code {proc.returncode}"
        raise StepError(f"background removal failed: {detail}")


# -------------------------------------------------------------- validation

def _coerce(value, param, op_name):
    typ = param["type"]
    arg = param["arg"]

    if typ is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "1", "on")
        return bool(value)

    if typ is str:
        return str(value)

    try:
        value = float(value) if typ is float else int(round(float(value)))
    except (TypeError, ValueError):
        raise StepError(f"{op_name}.{arg} needs a number, got {value!r}")

    lo, hi = param["min"], param["max"]
    if lo is not None and value < lo:
        value = lo
    if hi is not None and value > hi:
        value = hi
    return value


def validate(step):
    """Return (op_name, clean_args). Raises StepError on anything suspect."""
    if not isinstance(step, dict):
        raise StepError(f"Each step must be an object, got {type(step).__name__}")

    name = step.get("op")
    if name not in OPS:
        raise StepError(f"Unknown op {name!r}")
    if name not in available_ops():
        raise StepError(f"{name} is not available in this GIMP build")

    spec = OPS[name]
    by_arg = {p["arg"]: p for p in spec["params"]}
    raw = step.get("args") or {}
    if not isinstance(raw, dict):
        raise StepError(f"{name}: args must be an object")

    clean = {}
    for key, value in raw.items():
        if key not in by_arg:
            continue  # silently drop invented arguments
        if value is None:
            continue
        clean[key] = _coerce(value, by_arg[key], name)

    for arg, param in by_arg.items():
        if arg not in clean and param["default"] is not None:
            clean[arg] = param["default"]

    return name, clean


# ------------------------------------------------------------- GEGL filters

def _apply_gegl(image, drawable, spec, args, log):
    op = spec["gegl"]
    try:
        filt = Gimp.DrawableFilter.new(drawable, op, "")
    except Exception as e:
        raise StepError(f"GIMP would not create the {op} filter: {e}")

    config = filt.get_config()
    by_arg = {p["arg"]: p for p in spec["params"]}

    # blur/pixelize let you give one value for both axes
    if op == "gegl:gaussian-blur" and "radius_y" not in args and "radius" in args:
        args["radius_y"] = args["radius"]
    if op == "gegl:pixelize" and "size_y" not in args and "size" in args:
        args["size_y"] = args["size"]

    for arg, value in args.items():
        prop = by_arg[arg]["prop"]
        if not prop:
            continue
        try:
            config.set_property(prop, value)
        except Exception as e:
            log(f"    note: {op} ignored {prop}={value} ({e})")

    filt.update()
    drawable.merge_filter(filt)


# ------------------------------------------------------- image-level helpers

def _drawable(image):
    drawables = image.get_selected_drawables()
    if drawables:
        return drawables[0]
    layers = image.get_layers()
    if not layers:
        raise StepError("This image has no layers to work on.")
    return layers[0]


def _color(hex_string):
    c = Gegl.Color.new("black")
    try:
        c.set_rgba(*_hex_to_rgba(hex_string))
    except Exception:
        pass
    return c


def _hex_to_rgba(s):
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) == 6:
        s += "ff"
    if len(s) != 8 or any(ch not in "0123456789abcdefABCDEF" for ch in s):
        raise StepError(f"{s!r} is not a hex colour like #ffffff")
    r, g, b, a = (int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4, 6))
    return r, g, b, a


def _run_pdb(name, **kwargs):
    pdb = Gimp.get_pdb()
    proc = pdb.lookup_procedure(name)
    if proc is None:
        raise StepError(f"This GIMP build has no procedure called {name}")
    config = proc.create_config()
    for key, value in kwargs.items():
        config.set_property(key.replace("_", "-"), value)
    result = proc.run(config)
    status = result.index(0)
    if status != Gimp.PDBStatusType.SUCCESS:
        raise StepError(f"{name} failed with status {status}")
    return result


# ---------------------------------------------------------- image-level ops

def _op_crop(image, args, log):
    w = args.get("width") or image.get_width()
    h = args.get("height") or image.get_height()
    x, y = args.get("x", 0), args.get("y", 0)
    w = min(w, image.get_width() - x)
    h = min(h, image.get_height() - y)
    if w < 1 or h < 1:
        raise StepError("That crop rectangle falls outside the image.")
    image.crop(w, h, x, y)


def _op_crop_to_aspect(image, args, log):
    ratio = str(args.get("ratio", "1:1")).replace("x", ":").replace("/", ":")
    try:
        rw, rh = (float(part) for part in ratio.split(":", 1))
        target = rw / rh
    except Exception:
        raise StepError(f"{ratio!r} is not a ratio like 16:9")

    W, H = image.get_width(), image.get_height()
    if W / H > target:
        w, h = int(round(H * target)), H
    else:
        w, h = W, int(round(W / target))

    anchor = str(args.get("anchor", "center")).lower()
    x = (W - w) // 2
    y = (H - h) // 2
    if anchor == "left":
        x = 0
    elif anchor == "right":
        x = W - w
    elif anchor == "top":
        y = 0
    elif anchor == "bottom":
        y = H - h
    image.crop(w, h, x, y)


def _op_autocrop(image, args, log):
    _run_pdb("plug-in-autocrop",
             run_mode=Gimp.RunMode.NONINTERACTIVE,
             image=image,
             drawable=_drawable(image))


def _op_resize(image, args, log):
    W, H = image.get_width(), image.get_height()
    percent = args.get("percent")
    w, h = args.get("width"), args.get("height")

    if percent:
        w = int(round(W * percent / 100.0))
        h = int(round(H * percent / 100.0))
    elif args.get("keep_aspect", True):
        if w and not h:
            h = int(round(H * w / W))
        elif h and not w:
            w = int(round(W * h / H))
        elif w and h:
            scale = min(w / W, h / H)
            w, h = int(round(W * scale)), int(round(H * scale))

    if not w or not h:
        raise StepError("resize needs a width, a height or a percent.")
    image.scale(max(1, w), max(1, h))


def _op_rotate(image, args, log):
    deg = float(args.get("degrees", 90)) % 360
    simple = {90: Gimp.RotationType.DEGREES90,
              180: Gimp.RotationType.DEGREES180,
              270: Gimp.RotationType.DEGREES270}
    if int(deg) in simple and abs(deg - int(deg)) < 1e-6:
        image.rotate(simple[int(deg)])
        return

    # arbitrary angle: rotate every layer about the canvas centre
    cx, cy = image.get_width() / 2.0, image.get_height() / 2.0
    rad = math.radians(deg)
    for layer in image.get_layers():
        layer.transform_rotate(rad, False, cx, cy)


def _op_flip(image, args, log):
    direction = str(args.get("direction", "horizontal")).lower()
    if direction.startswith("v"):
        image.flip(Gimp.OrientationType.VERTICAL)
    else:
        image.flip(Gimp.OrientationType.HORIZONTAL)


def _op_canvas_size(image, args, log):
    w = args.get("width") or image.get_width()
    h = args.get("height") or image.get_height()
    ox = args.get("offset_x")
    oy = args.get("offset_y")
    if ox is None:
        ox = (w - image.get_width()) // 2
    if oy is None:
        oy = (h - image.get_height()) // 2
    image.resize(w, h, ox, oy)


def _op_add_border(image, args, log):
    size = int(args.get("size", 40))
    W, H = image.get_width(), image.get_height()
    image.resize(W + size * 2, H + size * 2, size, size)
    image.flatten()
    layer = _drawable(image)
    layer.resize_to_image_size()

    Gimp.context_push()
    try:
        Gimp.context_set_foreground(_color(args.get("color", "#ffffff")))
        image.select_rectangle(Gimp.ChannelOps.REPLACE, 0, 0,
                               image.get_width(), image.get_height())
        image.select_rectangle(Gimp.ChannelOps.SUBTRACT, size, size, W, H)
        layer.edit_fill(Gimp.FillType.FOREGROUND)
        image.select_none()
    finally:
        Gimp.context_pop()


def _op_flatten(image, args, log):
    image.flatten()


def _op_duplicate_layer(image, args, log):
    layer = _drawable(image)
    copy = layer.copy()
    image.insert_layer(copy, None, 0)


def _op_layer_opacity(image, args, log):
    _drawable(image).set_opacity(float(args.get("percent", 100.0)))


def _op_add_text(image, args, log):
    text = args.get("text")
    if not text:
        raise StepError("add_text needs some text.")
    size = float(args.get("size", 48))
    font = args.get("font", "Sans-serif")

    layer = Gimp.TextLayer.new(image, text, Gimp.Font.get_by_name(font)
                               or Gimp.context_get_font(), size, Gimp.Unit.pixel())
    layer.set_color(_color(args.get("color", "#ffffff")))
    image.insert_layer(layer, None, 0)

    x = args.get("x")
    y = args.get("y")
    if x is None:
        x = (image.get_width() - layer.get_width()) // 2
    if y is None:
        y = (image.get_height() - layer.get_height()) // 2
    layer.set_offsets(int(x), int(y))


def _op_remove_background(image, args, log):
    py = helper_python()
    if not py:
        raise StepError(
            "no helper interpreter with rembg was found "
            "(expected ~/.gimp-ai/bin/python)")

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "rembg_helper.py")
    if not os.path.isfile(script):
        raise StepError("rembg_helper.py is missing from the plug-in folder")

    background = str(args.get("background", "transparent")).strip().lower()
    if background not in ("transparent", "none", ""):
        _hex_to_rgba(background)          # validate before doing slow work
    else:
        background = "transparent"

    workdir = tempfile.mkdtemp(prefix="gimp-ai-")
    src = os.path.join(workdir, "in.png")
    dst = os.path.join(workdir, "out.png")

    try:
        flat = image.duplicate()
        flat.flatten()
        try:
            Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, flat,
                           Gio.File.new_for_path(src), None)
        except TypeError:
            Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, flat,
                           Gio.File.new_for_path(src))
        finally:
            flat.delete()

        log("    running the segmentation model, this takes a few seconds…")
        _run_helper([py, script, src, dst, background], log)

        if not os.path.isfile(dst):
            raise StepError("the helper produced no image")

        old = list(image.get_layers())
        cut = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image,
                                   Gio.File.new_for_path(dst))
        cut.set_name("Subject" if background == "transparent" else "Subject on colour")
        image.insert_layer(cut, None, 0)
        if not cut.has_alpha():
            cut.add_alpha()

        if not args.get("keep_original", False):
            for layer in old:
                try:
                    image.remove_layer(layer)
                except Exception:
                    pass
        log("    background removed")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _op_export(image, args, log):
    path = args.get("path")
    if not path:
        raise StepError("export needs a path.")
    dup = image.duplicate()
    dup.flatten()
    gfile = Gio.File.new_for_path(path)
    try:
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup, gfile, None)
    except TypeError:
        Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, dup, gfile)
    finally:
        dup.delete()
    log(f"    saved to {path}")


IMAGE_OPS = {
    "crop": _op_crop,
    "crop_to_aspect": _op_crop_to_aspect,
    "autocrop": _op_autocrop,
    "resize": _op_resize,
    "rotate": _op_rotate,
    "flip": _op_flip,
    "canvas_size": _op_canvas_size,
    "add_border": _op_add_border,
    "remove_background": _op_remove_background,
    "flatten": _op_flatten,
    "duplicate_layer": _op_duplicate_layer,
    "layer_opacity": _op_layer_opacity,
    "add_text": _op_add_text,
    "export": _op_export,
}


# ------------------------------------------------------------------ driver

def run_plan(image, steps, log, undo_label="AI Editor"):
    """Apply a validated plan. Returns (applied, failed).

    Everything lands inside one undo group, so a single Ctrl+Z puts the
    image back exactly as it was.
    """
    checked = []
    for i, step in enumerate(steps, 1):
        try:
            checked.append(validate(step))
        except StepError as e:
            log(f"  step {i} rejected: {e}")

    if not checked:
        return 0, len(steps)

    applied = 0
    failed = len(steps) - len(checked)

    image.undo_group_start()
    try:
        for i, (name, args) in enumerate(checked, 1):
            spec = OPS[name]
            pretty = ", ".join(f"{k}={v}" for k, v in args.items())
            log(f"  {i}. {name}({pretty})")
            try:
                if spec["kind"] == "gegl":
                    _apply_gegl(image, _drawable(image), spec, args, log)
                else:
                    IMAGE_OPS[name](image, args, log)
                applied += 1
            except Exception as e:
                failed += 1
                log(f"    failed: {e}")
            # repaint after every step so the change is visible as it happens
            Gimp.displays_flush()
    finally:
        image.undo_group_end()
        Gimp.displays_flush()

    return applied, failed
