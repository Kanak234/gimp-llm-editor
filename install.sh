#!/usr/bin/env bash
#
# Installs the AI Editor plug-in into every GIMP 3 profile it can find.
#
#   ./install.sh                 # auto-detect
#   ./install.sh ~/.config/GIMP/3.2/plug-ins   # or say where
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/llm_editor"

if [[ ! -f "$SRC/llm_editor.py" ]]; then
  echo "Cannot find $SRC/llm_editor.py — run this from inside the project folder."
  exit 1
fi

targets=()

if [[ $# -ge 1 ]]; then
  targets+=("$1")
else
  # Native install
  for d in "$HOME"/.config/GIMP/3.*; do
    [[ -d "$d" ]] && targets+=("$d/plug-ins")
  done
  # Flatpak
  for d in "$HOME"/.var/app/org.gimp.GIMP/config/GIMP/3.*; do
    [[ -d "$d" ]] && targets+=("$d/plug-ins")
  done
  # Snap
  for d in "$HOME"/snap/gimp/current/.config/GIMP/3.*; do
    [[ -d "$d" ]] && targets+=("$d/plug-ins")
  done
fi

if [[ ${#targets[@]} -eq 0 ]]; then
  echo "No GIMP 3 profile found."
  echo "Open GIMP once so it creates its config folder, then run this again."
  echo "Or pass the path yourself:  ./install.sh ~/.config/GIMP/3.2/plug-ins"
  exit 1
fi

for target in "${targets[@]}"; do
  mkdir -p "$target/llm_editor"
  cp "$SRC"/*.py "$target/llm_editor/"
  chmod +x "$target/llm_editor/llm_editor.py"
  echo "Installed to $target/llm_editor"
done

echo
echo "Now restart GIMP. The panel is at:  Filters ▸ AI Editor (local model)…"
echo "Make sure Ollama is running:        ollama serve"
