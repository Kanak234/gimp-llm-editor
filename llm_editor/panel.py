"""
The panel that sits next to the canvas.

It stays open and modeless, so the brush, the mouse and every keyboard
shortcut keep working while it is up. GIMP runs plug-ins in their own
process, so this window never blocks the main application.

Threading rule that the whole file is built around: the network call to
Ollama happens on a worker thread, and every single GIMP call happens back
on the main thread via GLib.idle_add. Touching GIMP from the worker would
crash the plug-in.
"""

import threading

import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gimp, Gtk, Gdk, GLib, Pango

import executor
import planner
from ollama_client import list_models, DEFAULT_HOST

PREFERRED = ["qwen3-coder", "qwen2.5-coder", "deepseek-r1", "phi4-mini"]


class LLMPanel(Gtk.Window):

    def __init__(self, image):
        super().__init__(title="AI Editor")
        self.image = image
        self.busy = False

        self.set_default_size(420, 520)
        self.set_keep_above(True)
        try:
            self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        except Exception:
            pass
        self.connect("destroy", self._on_close)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_border_width(12)
        self.add(outer)

        # ---- model row -------------------------------------------------
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(Gtk.Label(label="Model", xalign=0), False, False, 0)
        self.model_combo = Gtk.ComboBoxText()
        row.pack_start(self.model_combo, True, True, 0)
        refresh = Gtk.Button(label="Reload")
        refresh.connect("clicked", lambda *_: self._load_models())
        row.pack_start(refresh, False, False, 0)
        outer.pack_start(row, False, False, 0)

        # ---- instruction ------------------------------------------------
        outer.pack_start(self._heading("What should I change?"), False, False, 0)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("brighten it a little and sharpen")
        self.entry.connect("activate", lambda *_: self._on_apply())
        outer.pack_start(self.entry, False, False, 0)

        hint = Gtk.Label(xalign=0)
        hint.set_markup(
            "<small>Plain language, English or Hindi. "
            "Press Enter to run.</small>")
        hint.get_style_context().add_class("dim-label")
        outer.pack_start(hint, False, False, 0)

        # ---- actions ----------------------------------------------------
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.apply_btn = Gtk.Button(label="Apply edit")
        self.apply_btn.get_style_context().add_class("suggested-action")
        self.apply_btn.connect("clicked", lambda *_: self._on_apply())
        actions.pack_start(self.apply_btn, True, True, 0)

        undo_btn = Gtk.Button(label="Undo last")
        undo_btn.connect("clicked", self._on_undo)
        actions.pack_start(undo_btn, False, False, 0)
        outer.pack_start(actions, False, False, 0)

        self.dry_run = Gtk.CheckButton(label="Show the plan without applying it")
        outer.pack_start(self.dry_run, False, False, 0)

        # ---- log --------------------------------------------------------
        outer.pack_start(self._heading("Activity"), False, False, 0)
        self.buffer = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self.buffer)
        view.set_editable(False)
        view.set_cursor_visible(False)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        try:
            view.override_font(Pango.FontDescription("Monospace 9"))
        except Exception:
            pass
        self.view = view
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(view)
        outer.pack_start(scroll, True, True, 0)

        self.status = Gtk.Label(xalign=0)
        self.status.get_style_context().add_class("dim-label")
        outer.pack_start(self.status, False, False, 0)

        # ---- start-up ----------------------------------------------------
        self._load_models()
        self._report_capabilities()
        self._place_beside_canvas()

    # ------------------------------------------------------------- chrome

    def _heading(self, text):
        label = Gtk.Label(xalign=0)
        label.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
        return label

    def _place_beside_canvas(self):
        try:
            screen = self.get_screen()
            width = screen.get_width()
            self.move(max(0, width - 460), 120)
        except Exception:
            pass

    def log(self, text):
        self.buffer.insert(self.buffer.get_end_iter(), text + "\n")
        # keep the newest line in view
        mark = self.buffer.create_mark(None, self.buffer.get_end_iter(), False)
        self.view.scroll_mark_onscreen(mark)
        self.buffer.delete_mark(mark)

    def set_status(self, text):
        self.status.set_text(text)

    # -------------------------------------------------------- model setup

    def _host(self):
        return DEFAULT_HOST

    def _load_models(self):
        self.model_combo.remove_all()
        names = list_models(self._host())
        if not names:
            self.model_combo.append_text("(no models found)")
            self.model_combo.set_active(0)
            self.log("Ollama is not answering. Start it with `ollama serve`, "
                     "then press Reload.")
            return

        def rank(name):
            for i, pref in enumerate(PREFERRED):
                if name.startswith(pref):
                    return i
            return len(PREFERRED)

        names.sort(key=lambda n: (rank(n), n))
        for name in names:
            self.model_combo.append_text(name)
        self.model_combo.set_active(0)
        self.log(f"Ollama ready. Using {names[0]}.")

    def _report_capabilities(self):
        missing = executor.missing_ops()
        total = len(executor.available_ops())
        self.log(f"{total} operations available in this GIMP build.")
        if missing:
            self.log("Not available here: " + ", ".join(missing))
        helper = executor.helper_python()
        if helper:
            self.log(f"Background removal ready via {helper}")
        else:
            self.log("Background removal off: no helper interpreter with rembg. "
                     "See the README.")

    # ------------------------------------------------------------ actions

    def _on_undo(self, *_):
        try:
            self.image.undo()
            Gimp.displays_flush()
            self.log("Undone.")
        except Exception as e:
            self.log(f"Nothing to undo ({e}).")

    def _on_apply(self, *_):
        if self.busy:
            return
        instruction = self.entry.get_text().strip()
        if not instruction:
            self.set_status("Type an instruction first.")
            return
        model = self.model_combo.get_active_text()
        if not model or model.startswith("("):
            self.set_status("No model selected. Press Reload.")
            return

        info = {
            "width": self.image.get_width(),
            "height": self.image.get_height(),
            "layers": len(self.image.get_layers()),
            "alpha": bool(self.image.get_layers()
                          and self.image.get_layers()[0].has_alpha()),
        }

        self._set_busy(True)
        self.log("")
        self.log(f"> {instruction}")
        self.set_status(f"Thinking with {model}…")

        thread = threading.Thread(
            target=self._worker,
            args=(instruction, info, model),
            daemon=True,
        )
        thread.start()

    def _set_busy(self, busy):
        self.busy = busy
        self.apply_btn.set_sensitive(not busy)
        self.entry.set_sensitive(not busy)

    # ------------------------------------------------------ worker thread

    def _worker(self, instruction, info, model):
        """Runs off the main thread. Must not touch GIMP or GTK directly."""
        collected = []
        try:
            summary, steps = planner.plan(
                instruction, info, model, self._host(),
                log=collected.append,
            )
            GLib.idle_add(self._on_plan_ready, summary, steps, collected)
        except Exception as e:
            GLib.idle_add(self._on_plan_failed, str(e), collected)

    # -------------------------------------------------- back on main thread

    def _on_plan_ready(self, summary, steps, notes):
        for note in notes:
            self.log(note)

        if summary:
            self.log(f"Plan: {summary}")
        if not steps:
            self.log("No steps to run. Try describing the change differently.")
            self.set_status("Nothing applied.")
            self._set_busy(False)
            return

        if self.dry_run.get_active():
            for i, step in enumerate(steps, 1):
                args = step.get("args") or {}
                pretty = ", ".join(f"{k}={v}" for k, v in args.items())
                self.log(f"  {i}. {step.get('op')}({pretty})")
            self.log("Dry run only. Untick the box to apply.")
            self.set_status("Plan shown, nothing changed.")
            self._set_busy(False)
            return

        applied, failed = executor.run_plan(self.image, steps, self.log)
        if failed:
            self.set_status(f"{applied} applied, {failed} skipped. Ctrl+Z undoes it all.")
        else:
            self.set_status(f"{applied} applied. Ctrl+Z undoes it all.")
        self._set_busy(False)
        return False

    def _on_plan_failed(self, message, notes):
        for note in notes:
            self.log(note)
        self.log(message)
        self.set_status("The model could not be reached.")
        self._set_busy(False)
        return False

    # -------------------------------------------------------------- close

    def _on_close(self, *_):
        Gtk.main_quit()
