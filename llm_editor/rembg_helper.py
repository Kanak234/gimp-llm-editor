#!/usr/bin/env python3
"""Segmentation helper. Runs OUTSIDE GIMP, in the user's own virtualenv.

    rembg_helper.py <input.png> <output.png> <background>

`background` is either the word "transparent" or a hex colour like #ffffff.

This file must not import gi or anything GIMP-related. It is deliberately
a separate process: GIMP ships its own Python, which cannot have rembg
installed into it, and a 1 GB ONNX model has no business living inside the
plug-in process anyway.

Lines beginning with "::" are progress notes the plug-in shows in its log.
Anything else on stdout is treated as error detail.
"""

import sys


def hex_to_rgba(s):
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) == 6:
        s += "ff"
    if len(s) != 8 or any(ch not in "0123456789abcdefABCDEF" for ch in s):
        raise ValueError("%r is not a hex colour like #ffffff" % s)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4, 6))


def main(argv):
    if len(argv) != 4:
        print("usage: rembg_helper.py <in.png> <out.png> <background>")
        return 2

    src, dst, background = argv[1], argv[2], argv[3]

    try:
        from PIL import Image
    except ImportError:
        print("Pillow is not installed in this interpreter")
        return 3
    try:
        from rembg import remove
    except ImportError:
        print("rembg is not installed in this interpreter")
        return 3

    print("::loading image", flush=True)
    image = Image.open(src).convert("RGBA")

    print("::separating subject from background", flush=True)
    cut = remove(image)
    if cut.mode != "RGBA":
        cut = cut.convert("RGBA")

    if background not in ("transparent", "none", ""):
        print("::filling the background", flush=True)
        try:
            rgba = hex_to_rgba(background)
        except ValueError as e:
            print(str(e))
            return 4
        plate = Image.new("RGBA", cut.size, rgba)
        plate.alpha_composite(cut)
        cut = plate

    cut.save(dst, "PNG")
    print("::done", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as exc:            # last line becomes the error shown
        print("%s: %s" % (type(exc).__name__, exc))
        sys.exit(1)
