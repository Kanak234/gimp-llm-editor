"""
Operation catalog for the AI Editor plug-in.

Everything the model is allowed to do lives here. The model never writes
Python and never names a GEGL operation directly -- it picks an `op` from
this table and fills in named arguments. The executor does the rest.

Two kinds of op:

  kind = "gegl"   applied to a drawable through Gimp.DrawableFilter,
                  using the GEGL operation named in `gegl`.
                  `params` maps our argument name -> GEGL property name.

  kind = "image"  handled by a Python function in executor.py, because it
                  changes the image itself (size, rotation, layers) rather
                  than pixels in one drawable.

Ranges are advisory: they are shown to the model and used to clamp values
before anything touches the image.
"""

# ---------------------------------------------------------------- helpers

def _p(arg, prop, typ, lo=None, hi=None, default=None, note=""):
    return {
        "arg": arg, "prop": prop, "type": typ,
        "min": lo, "max": hi, "default": default, "note": note,
    }


# ------------------------------------------------------------- the table

OPS = {

    # ---------------------------------------------------- tone & exposure
    "brightness_contrast": {
        "kind": "gegl", "gegl": "gegl:brightness-contrast",
        "desc": "Lift or drop overall brightness and contrast.",
        "params": [
            _p("brightness", "brightness", float, -1.0, 1.0, 0.0,
               "0 = unchanged. 0.15 is a gentle lift."),
            _p("contrast", "contrast", float, 0.0, 2.0, 1.0,
               "1 = unchanged. 1.2 is a mild boost."),
        ],
    },
    "exposure": {
        "kind": "gegl", "gegl": "gegl:exposure",
        "desc": "Photographic exposure in stops. Better than brightness for photos.",
        "params": [
            _p("stops", "exposure", float, -4.0, 4.0, 0.0, "+1 doubles the light."),
            _p("offset", "offset", float, -0.5, 0.5, 0.0, "Black point nudge."),
            _p("gamma", "gamma", float, 0.1, 3.0, 1.0, ""),
        ],
    },
    "shadows_highlights": {
        "kind": "gegl", "gegl": "gegl:shadows-highlights",
        "desc": "Open up dark areas and pull back blown highlights.",
        "params": [
            _p("shadows", "shadows", float, -100.0, 100.0, 0.0, "Positive opens shadows."),
            _p("highlights", "highlights", float, -100.0, 100.0, 0.0,
               "Negative recovers highlights."),
            _p("radius", "radius", float, 0.1, 300.0, 100.0, ""),
        ],
    },
    "levels": {
        "kind": "gegl", "gegl": "gegl:levels",
        "desc": "Manual black/white point and output range.",
        "params": [
            _p("in_low", "in-low", float, 0.0, 1.0, 0.0, ""),
            _p("in_high", "in-high", float, 0.0, 1.0, 1.0, ""),
            _p("out_low", "out-low", float, 0.0, 1.0, 0.0, ""),
            _p("out_high", "out-high", float, 0.0, 1.0, 1.0, ""),
        ],
    },
    "auto_contrast": {
        "kind": "gegl", "gegl": "gegl:stretch-contrast",
        "desc": "Automatically stretch the histogram to full range.",
        "params": [
            _p("keep_colors", "keep-colors", bool, None, None, True,
               "True avoids a colour cast."),
        ],
    },

    # ----------------------------------------------------------- colour
    "saturation": {
        "kind": "gegl", "gegl": "gegl:saturation",
        "desc": "Make colours stronger or weaker.",
        "params": [
            _p("scale", "scale", float, 0.0, 3.0, 1.0,
               "1 = unchanged, 0 = grey, 1.4 = punchy."),
        ],
    },
    "hue_chroma": {
        "kind": "gegl", "gegl": "gegl:hue-chroma",
        "desc": "Shift hue, chroma and lightness.",
        "params": [
            _p("hue", "hue", float, -180.0, 180.0, 0.0, "Degrees."),
            _p("chroma", "chroma", float, -100.0, 100.0, 0.0, ""),
            _p("lightness", "lightness", float, -100.0, 100.0, 0.0, ""),
        ],
    },
    "color_temperature": {
        "kind": "gegl", "gegl": "gegl:color-temperature",
        "desc": "Warm the image up or cool it down.",
        "params": [
            _p("from_k", "original-temperature", float, 1000.0, 12000.0, 6500.0, ""),
            _p("to_k", "intended-temperature", float, 1000.0, 12000.0, 6500.0,
               "Lower than from_k = warmer."),
        ],
    },
    "grayscale": {
        "kind": "gegl", "gegl": "gegl:gray",
        "desc": "Convert to black and white.",
        "params": [],
    },
    "sepia": {
        "kind": "gegl", "gegl": "gegl:sepia",
        "desc": "Warm brown vintage tone.",
        "params": [_p("scale", "scale", float, 0.0, 1.0, 1.0, "Strength.")],
    },
    "invert": {
        "kind": "gegl", "gegl": "gegl:invert-gamma",
        "desc": "Invert the colours (negative).",
        "params": [],
    },
    "posterize": {
        "kind": "gegl", "gegl": "gegl:posterize",
        "desc": "Reduce to a small number of tonal steps.",
        "params": [_p("levels", "levels", int, 2, 64, 8, "")],
    },
    "threshold": {
        "kind": "gegl", "gegl": "gegl:threshold",
        "desc": "Hard black-and-white cutoff.",
        "params": [_p("value", "value", float, 0.0, 1.0, 0.5, "")],
    },

    # ------------------------------------------------- blur / sharpen / noise
    "blur": {
        "kind": "gegl", "gegl": "gegl:gaussian-blur",
        "desc": "Soft gaussian blur.",
        "params": [
            _p("radius", "std-dev-x", float, 0.0, 200.0, 5.0, "Pixels."),
            _p("radius_y", "std-dev-y", float, 0.0, 200.0, None,
               "Leave out to match radius."),
        ],
    },
    "motion_blur": {
        "kind": "gegl", "gegl": "gegl:motion-blur-linear",
        "desc": "Directional streak blur.",
        "params": [
            _p("length", "length", float, 0.0, 400.0, 20.0, ""),
            _p("angle", "angle", float, -180.0, 180.0, 0.0, "Degrees."),
        ],
    },
    "sharpen": {
        "kind": "gegl", "gegl": "gegl:unsharp-mask",
        "desc": "Unsharp mask. The normal way to sharpen a photo.",
        "params": [
            _p("radius", "std-dev", float, 0.0, 100.0, 3.0, ""),
            _p("amount", "scale", float, 0.0, 5.0, 0.5, "0.5 is subtle, 1.5 is strong."),
            _p("threshold", "threshold", float, 0.0, 1.0, 0.0, ""),
        ],
    },
    "denoise": {
        "kind": "gegl", "gegl": "gegl:noise-reduction",
        "desc": "Reduce sensor noise.",
        "params": [_p("iterations", "iterations", int, 1, 32, 4, "")],
    },
    "median_blur": {
        "kind": "gegl", "gegl": "gegl:median-blur",
        "desc": "Edge-preserving smoothing, good for skin and speckle.",
        "params": [
            _p("radius", "radius", int, -1, 100, 3, ""),
            _p("percentile", "percentile", float, 0.0, 100.0, 50.0, ""),
        ],
    },
    "pixelize": {
        "kind": "gegl", "gegl": "gegl:pixelize",
        "desc": "Chunky mosaic blocks. Use to hide faces or plates.",
        "params": [
            _p("size", "size-x", int, 1, 512, 16, ""),
            _p("size_y", "size-y", int, 1, 512, None, "Leave out to match size."),
        ],
    },

    # ------------------------------------------------------------ effects
    "vignette": {
        "kind": "gegl", "gegl": "gegl:vignette",
        "desc": "Darken the corners.",
        "params": [
            _p("radius", "radius", float, 0.0, 3.0, 1.5, ""),
            _p("softness", "softness", float, 0.0, 1.0, 0.8, ""),
            _p("squeeze", "squeeze", float, -1.0, 1.0, 0.0, ""),
        ],
    },
    "soft_glow": {
        "kind": "gegl", "gegl": "gegl:softglow",
        "desc": "Dreamy bloom on the highlights.",
        "params": [
            _p("radius", "glow-radius", float, 1.0, 50.0, 10.0, ""),
            _p("brightness", "brightness", float, 0.0, 1.0, 0.3, ""),
            _p("sharpness", "sharpness", float, 0.0, 1.0, 0.85, ""),
        ],
    },
    "oilify": {
        "kind": "gegl", "gegl": "gegl:oilify",
        "desc": "Oil-painting look.",
        "params": [
            _p("radius", "mask-radius", int, 1, 25, 4, ""),
            _p("exponent", "exponent", int, 1, 20, 8, ""),
        ],
    },
    "cartoon": {
        "kind": "gegl", "gegl": "gegl:cartoon",
        "desc": "Inked cartoon outlines.",
        "params": [
            _p("radius", "mask-radius", float, 1.0, 50.0, 7.0, ""),
            _p("black", "pct-black", float, 0.0, 1.0, 0.2, ""),
        ],
    },
    "emboss": {
        "kind": "gegl", "gegl": "gegl:emboss",
        "desc": "Raised metal relief.",
        "params": [
            _p("azimuth", "azimuth", float, 0.0, 360.0, 30.0, ""),
            _p("elevation", "elevation", float, 0.0, 180.0, 45.0, ""),
            _p("depth", "depth", int, 1, 100, 20, ""),
        ],
    },
    "edge_detect": {
        "kind": "gegl", "gegl": "gegl:edge",
        "desc": "Keep only the edges.",
        "params": [
            _p("amount", "amount", float, 1.0, 10.0, 2.0, ""),
        ],
    },

    # ---------------------------------------------------------- geometry
    "crop": {
        "kind": "image", "desc": "Crop to an exact rectangle in pixels.",
        "params": [
            _p("x", None, int, 0, None, 0, ""),
            _p("y", None, int, 0, None, 0, ""),
            _p("width", None, int, 1, None, None, ""),
            _p("height", None, int, 1, None, None, ""),
        ],
    },
    "crop_to_aspect": {
        "kind": "image",
        "desc": "Crop to an aspect ratio, keeping as much as possible.",
        "params": [
            _p("ratio", None, str, None, None, "1:1",
               "Like '1:1', '16:9', '4:5'."),
            _p("anchor", None, str, None, None, "center",
               "center, top, bottom, left or right."),
        ],
    },
    "autocrop": {
        "kind": "image", "desc": "Trim uniform borders automatically.",
        "params": [],
    },
    "resize": {
        "kind": "image",
        "desc": "Scale the whole image. Give width, height, or percent.",
        "params": [
            _p("width", None, int, 1, 30000, None, ""),
            _p("height", None, int, 1, 30000, None, ""),
            _p("percent", None, float, 1.0, 1000.0, None, "100 = unchanged."),
            _p("keep_aspect", None, bool, None, None, True, ""),
        ],
    },
    "rotate": {
        "kind": "image", "desc": "Rotate the image.",
        "params": [
            _p("degrees", None, float, -360.0, 360.0, 90.0,
               "90, 180 and 270 are lossless; anything else is interpolated."),
        ],
    },
    "flip": {
        "kind": "image", "desc": "Mirror the image.",
        "params": [
            _p("direction", None, str, None, None, "horizontal",
               "horizontal or vertical."),
        ],
    },
    "canvas_size": {
        "kind": "image",
        "desc": "Change the canvas without scaling the picture.",
        "params": [
            _p("width", None, int, 1, 30000, None, ""),
            _p("height", None, int, 1, 30000, None, ""),
            _p("offset_x", None, int, None, None, None, "Leave out to centre."),
            _p("offset_y", None, int, None, None, None, "Leave out to centre."),
        ],
    },
    "add_border": {
        "kind": "image", "desc": "Add a solid border around the image.",
        "params": [
            _p("size", None, int, 1, 2000, 40, "Pixels."),
            _p("color", None, str, None, None, "#ffffff", "Hex colour."),
        ],
    },

    # --------------------------------------------------------- segmentation
    "remove_background": {
        "kind": "image", "requires": "rembg",
        "desc": ("Cut the main subject out and drop the background. This is the "
                 "ONLY op that can tell subject from background, because it runs "
                 "a separate model that actually looks at the picture."),
        "params": [
            _p("background", None, str, None, None, "transparent",
               "'transparent', or a hex colour like #ffffff to fill behind."),
            _p("keep_original", None, bool, None, None, False,
               "True leaves the untouched layer underneath."),
        ],
    },

    # ------------------------------------------------------------- layers
    "flatten": {
        "kind": "image", "desc": "Merge every layer into one.",
        "params": [],
    },
    "duplicate_layer": {
        "kind": "image", "desc": "Copy the active layer.",
        "params": [],
    },
    "layer_opacity": {
        "kind": "image", "desc": "Set the active layer's opacity.",
        "params": [_p("percent", None, float, 0.0, 100.0, 100.0, "")],
    },
    "add_text": {
        "kind": "image", "desc": "Add a text layer.",
        "params": [
            _p("text", None, str, None, None, None, ""),
            _p("size", None, float, 4.0, 500.0, 48.0, "Points."),
            _p("color", None, str, None, None, "#ffffff", "Hex colour."),
            _p("font", None, str, None, None, "Sans-serif", ""),
            _p("x", None, int, None, None, None, "Leave out to centre."),
            _p("y", None, int, None, None, None, "Leave out to centre."),
        ],
    },

    # ------------------------------------------------------------- output
    "export": {
        "kind": "image", "desc": "Write the image to a file.",
        "params": [
            _p("path", None, str, None, None, None,
               "Absolute path. Extension decides the format."),
        ],
    },
}


# The GEGL operation an op needs in order to be usable at all.
def required_gegl_op(name):
    spec = OPS.get(name)
    if spec and spec["kind"] == "gegl":
        return spec["gegl"]
    return None


def describe_for_model(available):
    """Compact, token-cheap description of the ops the model may use.

    `available` is the set of op names that this GIMP build can actually run.
    """
    lines = []
    for name in sorted(available):
        spec = OPS[name]
        args = []
        for p in spec["params"]:
            bit = p["arg"]
            if p["min"] is not None or p["max"] is not None:
                lo = "" if p["min"] is None else p["min"]
                hi = "" if p["max"] is None else p["max"]
                bit += f"[{lo}..{hi}]"
            if p["default"] is not None:
                bit += f"={p['default']}"
            if p["note"]:
                bit += f" ({p['note']})"
            args.append(bit)
        lines.append(f"{name}: {spec['desc']}")
        if args:
            lines.append("    args: " + "; ".join(args))
    return "\n".join(lines)
