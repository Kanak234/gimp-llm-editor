import os
import subprocess
import sys
import pytest

import catalog
import executor
from executor import StepError
import planner
import rembg_helper
import ollama_client


def test_catalog_structure_and_operations():
    assert len(catalog.OPS) >= 25
    for name, spec in catalog.OPS.items():
        assert "kind" in spec
        assert spec["kind"] in ("gegl", "image")
        assert "desc" in spec
        assert "params" in spec
        for p in spec["params"]:
            assert "arg" in p
            assert "type" in p
            assert p["type"] in (float, int, bool, str)


def test_catalog_required_gegl_op():
    assert catalog.required_gegl_op("brightness_contrast") == "gegl:brightness-contrast"
    assert catalog.required_gegl_op("blur") == "gegl:gaussian-blur"
    assert catalog.required_gegl_op("motion_blur") == "gegl:motion-blur-linear"
    assert catalog.required_gegl_op("resize") is None  # image op
    assert catalog.required_gegl_op("export") is None  # image op
    assert catalog.required_gegl_op("nonexistent_op") is None


def test_catalog_describe_for_model():
    sample_ops = {"brightness_contrast", "exposure", "resize"}
    desc = catalog.describe_for_model(sample_ops)
    assert "brightness_contrast:" in desc
    assert "exposure:" in desc
    assert "resize:" in desc
    assert "args:" in desc


def test_executor_available_ops():
    ops = executor.available_ops()
    assert isinstance(ops, set)
    assert len(ops) > 0
    # Image operations are always available
    assert "resize" in ops
    assert "crop" in ops
    assert "export" in ops


def test_executor_coerce_types():
    param_float = {"arg": "brightness", "type": float, "min": -1.0, "max": 1.0, "default": 0.0}
    assert executor._coerce("0.5", param_float, "brightness_contrast") == 0.5
    assert executor._coerce("2.0", param_float, "brightness_contrast") == 1.0  # clamped to max
    assert executor._coerce("-3.0", param_float, "brightness_contrast") == -1.0  # clamped to min

    param_int = {"arg": "radius", "type": int, "min": 0, "max": 100, "default": 10}
    assert executor._coerce("15.7", param_int, "blur") == 16
    assert executor._coerce(200, param_int, "blur") == 100

    param_bool = {"arg": "keep_aspect", "type": bool, "min": None, "max": None, "default": True}
    assert executor._coerce("true", param_bool, "resize") is True
    assert executor._coerce("no", param_bool, "resize") is False
    assert executor._coerce(1, param_bool, "resize") is True

    with pytest.raises(StepError, match="needs a number"):
        executor._coerce("invalid_num", param_float, "brightness_contrast")


def test_executor_validate_success():
    step = {
        "op": "brightness_contrast",
        "args": {
            "brightness": 0.2,
            "contrast": 1.1,
            "unknown_arg": 999  # should be silently dropped
        }
    }
    op_name, clean_args = executor.validate(step)
    assert op_name == "brightness_contrast"
    assert clean_args["brightness"] == 0.2
    assert clean_args["contrast"] == 1.1
    assert "unknown_arg" not in clean_args


def test_executor_validate_defaults():
    step = {"op": "brightness_contrast", "args": {}}
    op_name, clean_args = executor.validate(step)
    assert op_name == "brightness_contrast"
    # default brightness is 0.0, default contrast is 1.0
    assert clean_args["brightness"] == 0.0
    assert clean_args["contrast"] == 1.0


def test_executor_validate_errors():
    with pytest.raises(StepError, match="Each step must be an object"):
        executor.validate("not a dict")

    with pytest.raises(StepError, match="Unknown op"):
        executor.validate({"op": "teleport_to_mars"})

    with pytest.raises(StepError, match="args must be an object"):
        executor.validate({"op": "brightness_contrast", "args": "invalid"})


def test_planner_build_prompts():
    system = planner.build_system()
    assert "You drive a photo editor" in system
    assert "Operations available:" in system

    info = {"width": 1920, "height": 1080, "layers": 2, "alpha": True}
    user = planner.build_user("Make colors warmer and boost contrast", info)
    assert "1920 x 1080 pixels" in user
    assert "has transparency" in user
    assert "Make colors warmer" in user


def test_planner_problems_detection():
    valid_steps = [
        {"op": "brightness_contrast", "args": {"brightness": 0.1}},
        {"op": "resize", "args": {"width": 800, "height": 600}}
    ]
    assert planner._problems(valid_steps) == []

    invalid_steps = [
        {"op": "nonexistent_op", "args": {}},
        "not-a-step"
    ]
    problems = planner._problems(invalid_steps)
    assert len(problems) == 2
    assert "step 1:" in problems[0]
    assert "step 2:" in problems[1]

    not_a_list = planner._problems("invalid")
    assert not_a_list == ["steps must be a list"]


def test_rembg_hex_to_rgba():
    assert rembg_helper.hex_to_rgba("#fff") == (255, 255, 255, 255)
    assert rembg_helper.hex_to_rgba("f00") == (255, 0, 0, 255)
    assert rembg_helper.hex_to_rgba("#00ff00") == (0, 255, 0, 255)
    assert rembg_helper.hex_to_rgba("#12345678") == (18, 52, 86, 120)

    with pytest.raises(ValueError, match="not a hex colour"):
        rembg_helper.hex_to_rgba("not-a-color")

    with pytest.raises(ValueError, match="not a hex colour"):
        rembg_helper.hex_to_rgba("#12345")


def test_ollama_client_defaults():
    assert ollama_client.DEFAULT_HOST == "http://127.0.0.1:11434"
    # Testing offline fallback for list_models when Ollama is not running
    models = ollama_client.list_models(host="http://127.0.0.1:54321", timeout=0.1)
    assert isinstance(models, list)
    assert models == []


def test_probe_script_execution():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    probe_script = os.path.join(repo_root, "probe.py")
    res = subprocess.run([sys.executable, probe_script], capture_output=True, text=True)
    assert res.returncode == 0
