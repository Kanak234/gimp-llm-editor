#!/usr/bin/env python3
"""
AI Editor — edit the open image by describing the change.

Filters ▸ AI Editor (local model)…

Installs as a normal GIMP 3 Python plug-in. The folder name and this file
name must match, which is why both are called llm_editor.
"""

import os
import sys

# GIMP does not put the plug-in folder on sys.path, so the sibling modules
# would not import without this.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi
gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gimp, GimpUi, Gtk, GLib  # noqa: E402

PROC_NAME = "kanak-ai-editor"


class AIEditor(Gimp.PlugIn):

    def do_query_procedures(self):
        return [PROC_NAME]

    def do_set_i18n(self, procname):
        return False

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None
        )
        procedure.set_image_types("*")
        procedure.set_sensitivity_mask(
            Gimp.ProcedureSensitivityMask.DRAWABLE
            | Gimp.ProcedureSensitivityMask.DRAWABLES
        )
        procedure.set_menu_label("AI Editor (local model)…")
        procedure.add_menu_path("<Image>/Filters/")
        procedure.set_documentation(
            "Edit the open image by describing the change",
            "Sends your instruction to a local Ollama model, which picks "
            "from a fixed catalogue of edits. The model never writes or runs "
            "code; the plug-in applies the edits itself.",
            name,
        )
        procedure.set_attribution("Kanak Prabhakar", "Kanak Prabhakar", "2026")
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        GimpUi.init(PROC_NAME)

        from panel import LLMPanel  # imported late so GIMP can register fast

        panel = LLMPanel(image)
        panel.show_all()
        Gtk.main()

        return procedure.new_return_values(
            Gimp.PDBStatusType.SUCCESS, GLib.Error()
        )


Gimp.main(AIEditor.__gtype__, sys.argv)
