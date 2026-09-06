"""
Minimal Ollama client.

Deliberately stdlib-only: GIMP ships its own bundled Python and you cannot
assume `requests` is importable there.
"""

import json
import urllib.request
import urllib.error

DEFAULT_HOST = "http://127.0.0.1:11434"


class OllamaError(Exception):
    pass


def _post(host, path, payload, timeout):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        host.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise OllamaError(
            f"Could not reach Ollama at {host}. Is it running? "
            f"Try `ollama serve` in a terminal. ({e})"
        )
    except json.JSONDecodeError as e:
        raise OllamaError(f"Ollama sent back something that isn't JSON: {e}")


def list_models(host=DEFAULT_HOST, timeout=5):
    """Return the installed model names, newest first-ish."""
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
        return [m["name"] for m in body.get("models", [])]
    except Exception:
        return []


def chat_json(model, system, user, host=DEFAULT_HOST, timeout=180, temperature=0.1):
    """Ask the model for a JSON object and return it parsed.

    `format: json` makes Ollama constrain the output to valid JSON, which
    removes most of the "the model wrapped it in ```json" pain. The fence
    stripping below is belt and braces for older builds.
    """
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {"temperature": temperature},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    body = _post(host, "/api/chat", payload, timeout)
    content = (body.get("message") or {}).get("content", "").strip()
    if not content:
        raise OllamaError("The model returned an empty reply.")

    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:]
        content = content.strip()

    # Some small models still prepend a sentence. Take the outermost object.
    if not content.startswith("{"):
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1:
            raise OllamaError(f"No JSON object in the reply:\n{content[:400]}")
        content = content[start:end + 1]

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise OllamaError(f"The reply was not valid JSON ({e}):\n{content[:400]}")
