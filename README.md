# AI Editor — a GIMP 3 panel driven by a local model

Type what you want changed. A local Ollama model turns it into a list of
edits. The plug-in applies them to the open image, one at a time, so you
watch the picture change on the canvas.

Nothing leaves the machine. The model never writes or runs code.

---

## Install

```bash
cd gimp-llm-editor
chmod +x install.sh
./install.sh
```

Restart GIMP. The panel is at **Filters ▸ AI Editor (local model)…**

Ollama has to be up:

```bash
ollama serve          # if it isn't already running
ollama list           # qwen3-coder should be in here
```

If the installer cannot find your profile, pass the path:

```bash
./install.sh ~/.config/GIMP/3.2/plug-ins
```

---

## Using it

Open an image, open the panel, type an instruction, press Enter.

```
brighten it a little and sharpen
make it black and white with strong contrast
crop to 1:1 from the top
warm it up, this looks too blue
blur the background heavily
resize to 1080 wide and export to /home/kanak/out.jpg
थोड़ा और चमकदार करो और तेज़ करो
```

**Show the plan without applying it** prints the steps and stops. Useful
when you want to see what it decided before it touches the picture.

Everything from one instruction lands in a single undo group, so **Ctrl+Z
puts the image back exactly as it was** — not step by step, all at once.

The panel stays open and does not block GIMP. Keep painting, keep using
shortcuts, switch tools; the window just sits there.

---

## How it is built

Four pieces, and the split between them is the whole point.

| File | Job |
| --- | --- |
| `catalog.py` | Every edit that is allowed to exist, as data |
| `planner.py` | Builds the prompt, gets a plan, retries once if it is wrong |
| `executor.py` | Checks the plan and applies it with real GIMP calls |
| `panel.py` | The window |

**The model does not write code.** It picks an op name from the catalog and
fills in numbers. That is its entire surface area. There is no `eval`, no
`exec`, no shell, no generated Python. A 3-billion-parameter model
hallucinating a function name cannot do anything worse than get its step
rejected.

**Every value is clamped.** `catalog.py` carries a range for each argument.
If the model asks for a blur radius of 9000, it gets 200.

**The catalog checks itself against your build.** On startup the plug-in
asks GEGL which operations actually exist and drops the rest, then tells
the model about only the survivors. GEGL operation names shift a little
between GIMP releases, and this is what stops that from becoming your
problem.

**One thread rule.** The network call runs on a worker thread. Every GIMP
call comes back to the main thread through `GLib.idle_add`. Calling GIMP
from the worker would crash the plug-in, so all of that is kept in one
place at the bottom of `panel.py`.

---

## What it can do

Around 39 operations, in six groups:

- **Tone** — brightness/contrast, exposure, shadows/highlights, levels, auto contrast
- **Colour** — saturation, hue, colour temperature, grayscale, sepia, invert, posterize, threshold
- **Detail** — gaussian blur, motion blur, unsharp mask, denoise, median blur, pixelize
- **Effects** — vignette, soft glow, oilify, cartoon, emboss, edge detect
- **Geometry and layers** — crop, crop to aspect, autocrop, resize, rotate, flip, canvas size, border, flatten, duplicate layer, layer opacity, text, export
- **Segmentation** — remove background (optional, see below)

## Background removal

Every other operation applies to the whole layer, and the model is told
nothing about the picture beyond its size. So it cannot know where a
background *is*. Separating subject from background needs a model that
actually looks at pixels, which is a different kind of thing entirely.

That runs outside GIMP, in a virtualenv of your own, because GIMP ships its
own Python and you cannot install packages into it. One command sets it up:

```bash
python3 -m venv ~/.gimp-ai && ~/.gimp-ai/bin/pip install "rembg[cpu]" pillow
```

The first run downloads about 1 GB of model weights; after that it works
offline. Restart GIMP and the panel will log
`Background removal ready via /home/you/.gimp-ai/bin/python`. If it does not
find the venv, the op is hidden from the model entirely, so nothing can ask
for it and fail.

Other locations are searched too: `~/.venvs/gimp-ai/bin/python`, or whatever
`GIMP_AI_PYTHON` points at.

Try: *remove the background*, *cut out the subject and put it on white*,
*remove the background but keep the original layer*.

It takes a few seconds on CPU. The panel stays alive while it works, and the
whole thing is still one undo step.

## What it cannot do

Target part of an image, apart from the background case above. "Remove the
person on the left", "change only the sky", "blur just what is behind her",
"fix her skin" — the model has no way to see the image, and the operations
have no way to address a region. Those stay manual for now.

Adding one is easy though: put an entry in `catalog.py`, and if it needs a
Python handler, add it to `IMAGE_OPS` in `executor.py`. Nothing else
changes — the prompt rebuilds itself from the catalog.

---

## If something goes wrong

**The panel says Ollama is not answering.** Run `ollama serve` in a
terminal, then press Reload in the panel.

**A step is rejected as "not available in this GIMP build".** Your GEGL has
a different name for it. Run `probe.py` (instructions at the top of that
file) inside GIMP's Python-Fu console — it prints exactly which operations
are present and what their properties are called. Fix the name in
`catalog.py` and re-run `install.sh`.

**The plug-in does not appear in the Filters menu.** Check that
`llm_editor.py` is executable and that it sits in a folder of the same
name. GIMP is strict about this:

```
~/.config/GIMP/3.2/plug-ins/llm_editor/llm_editor.py
```

Then look at **Filters ▸ Development ▸ Python-Fu ▸ Console** or start GIMP
from a terminal — registration errors print there.

**The plan is silly.** Smaller models sometimes over-edit. Try
`qwen3-coder`, tick the dry-run box to see what it wants to do, and phrase
the instruction concretely: "increase brightness slightly" beats "make it
pop".

---

Built by Kanak Prabhakar.

**Background removal is off / the op is missing.** The panel logs which
interpreter it found on startup. Check the venv exists and has rembg:

```bash
~/.gimp-ai/bin/python -c "import rembg; print('ok')"
```

**Background removal fails partway.** The helper's last line of output is
shown in the panel log. Run it by hand to see everything:

```bash
~/.gimp-ai/bin/python ~/.config/GIMP/3.2/plug-ins/llm_editor/rembg_helper.py \
    in.png out.png transparent
```
