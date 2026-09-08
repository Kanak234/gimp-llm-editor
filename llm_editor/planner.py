"""
Turns a plain-language instruction into a checked list of steps.

The model's only job is to choose op names and numbers. It never writes
code. If it returns something the catalog rejects, it gets one chance to
fix it with the error handed back to it.
"""

try:
    from catalog import describe_for_model
    from executor import available_ops, validate, StepError
    from ollama_client import chat_json
except ImportError:
    from .catalog import describe_for_model
    from .executor import available_ops, validate, StepError
    from .ollama_client import chat_json

SYSTEM = """You drive a photo editor. You are given a list of operations \
and the user's instruction. You reply with a plan and nothing else.

Reply with a JSON object in exactly this shape:

{"summary": "one short sentence describing what you are about to do",
 "steps": [{"op": "<name from the list>", "args": {...}}]}

Rules:
- Use only op names from the list below. Never invent an op or an argument.
- Order matters. remove_background first of all if it is used, then geometry
  (crop, rotate, resize), then tone, then colour, then sharpening, and
  add_text or export last.
- Prefer few steps. Two good steps beat six timid ones.
- Stay gentle unless the user asks for something dramatic. A photo edit
  should look like a better photograph, not like a filter.
- If the instruction is vague ("make it nicer", "fix this"), interpret it
  as a light general correction: auto_contrast, a small saturation lift,
  and mild sharpening.
- The summary must describe only the steps you actually chose. Never repeat
  a request back as if you had done it. If part of the instruction cannot be
  done, say which part you skipped and why, then describe the rest.
- You cannot see the image. Every op except remove_background applies to the
  whole layer, not to a chosen area.
- remove_background is the one exception: it runs a model that does look at
  the picture, so it can separate subject from background. Use it whenever
  the user asks to remove, delete, cut out or replace a background, or to
  isolate the subject. It is slow, so use it only when actually asked for.
  If it is not in the list below, this machine has no helper installed and
  the request cannot be done.
- Nothing else can target part of the image. Changing only the sky, recolouring
  one object, blurring just the background, retouching a face -- none of that
  is possible. Skip that part, say so in the summary, and do the rest.
- If nothing in the instruction can be done, return an empty steps list and
  explain why in the summary.
- Sizes and positions are in pixels, and the image dimensions are given to
  you. Never use a coordinate that falls outside the image.

Operations available:

%s
"""


def build_system():
    return SYSTEM % describe_for_model(available_ops())


def build_user(instruction, info):
    return (
        f"Image: {info['width']} x {info['height']} pixels, "
        f"{info['layers']} layer(s), "
        f"{'has transparency' if info['alpha'] else 'no transparency'}.\n\n"
        f"Instruction: {instruction}"
    )


def plan(instruction, info, model, host, log, timeout=180):
    """Return (summary, steps). Raises OllamaError if the model is unreachable."""
    system = build_system()
    user = build_user(instruction, info)

    reply = chat_json(model, system, user, host=host, timeout=timeout)
    steps = reply.get("steps") or []
    summary = reply.get("summary") or ""

    problems = _problems(steps)
    if problems:
        log("  plan had problems, asking the model to fix them:")
        for p in problems:
            log(f"    - {p}")
        repair = (
            user
            + "\n\nYour previous answer was rejected:\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n\nReturn a corrected plan using only the listed ops and args."
        )
        reply = chat_json(model, system, repair, host=host, timeout=timeout)
        steps = reply.get("steps") or []
        summary = reply.get("summary") or summary

    return summary, steps


def _problems(steps):
    out = []
    if not isinstance(steps, list):
        return ["steps must be a list"]
    for i, step in enumerate(steps, 1):
        try:
            validate(step)
        except StepError as e:
            out.append(f"step {i}: {e}")
    return out
