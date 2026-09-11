"""scripts/ - the parts that can be tested without a database."""

import base64
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generate_keys_fill_never_overwrites_an_existing_value(tmp_path):
    gk = load("generate_keys")
    env = tmp_path / ".env"
    env.write_text(
        "BUDGET_MASTER_KEY=EXISTING-KEY-MUST-SURVIVE\n"
        "BUDGET_BLIND_INDEX_PEPPER=\n"
        "JWT_SECRET_KEY=   \n"
        "DB_PASSWORD=\n",
        encoding="utf-8",
    )
    filled = gk.fill_env(env)
    text = env.read_text(encoding="utf-8")
    assert "BUDGET_MASTER_KEY=EXISTING-KEY-MUST-SURVIVE" in text
    assert set(filled) == {"BUDGET_BLIND_INDEX_PEPPER", "JWT_SECRET_KEY"}
    assert "DB_PASSWORD=\n" in text  # not a generated secret; left alone
    pepper = next(line for line in text.splitlines() if line.startswith("BUDGET_BLIND_INDEX_PEPPER="))
    assert len(base64.b64decode(pepper.split("=", 1)[1])) == 32
    assert gk.fill_env(env) == []  # a second run changes nothing


@pytest.mark.parametrize("name", ["BUDGET_MASTER_KEY", "BUDGET_BLIND_INDEX_PEPPER", "PIN_PEPPER"])
def test_generated_binary_keys_are_32_bytes(name):
    gk = load("generate_keys")
    assert len(base64.b64decode(gk.GENERATORS[name]())) == 32
