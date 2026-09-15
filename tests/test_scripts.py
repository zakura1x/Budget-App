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


def test_env_fingerprint_matches_a_true_copy_and_names_what_differs(tmp_path, capsys):
    ef = load("env_fingerprint")
    key = base64.b64encode(b"k" * 32).decode()
    server, copy = tmp_path / "server.env", tmp_path / "copy.env"
    server.write_text(f"# the server\nBUDGET_MASTER_KEY={key}\nDB_PASSWORD=hunter2-Correct\nAPP_NAME=Budget App\n",
                      encoding="utf-8")
    copy.write_text(f"BUDGET_MASTER_KEY={key}\nDB_PASSWORD=hunter2-Correct\nAPP_NAME=Budget App\n", encoding="utf-8")
    assert ef.main([str(server), "--compare", str(copy)]) == 0

    copy.write_text(f"BUDGET_MASTER_KEY={key}\nDB_PASSWORD=an-old-password\n", encoding="utf-8")
    assert ef.main([str(server), "--compare", str(copy)]) == 2
    out = capsys.readouterr().out
    assert "DIFFERENT" in out and "only in first" in out
    assert "hunter2" not in out and "an-old-password" not in out and key not in out


def test_env_fingerprint_hashes_only_the_random_keys(tmp_path, capsys):
    ef = load("env_fingerprint")
    env = tmp_path / ".env"
    env.write_text("BUDGET_MASTER_KEY=zzz-a-key-zzz\nJWT_SECRET_KEY=\nDB_PASSWORD=zzz-secret-zzz\n", encoding="utf-8")
    assert ef.main([str(env)]) == 0
    out = capsys.readouterr().out
    assert "BUDGET_MASTER_KEY" in out and "(empty)" in out
    assert "DB_PASSWORD" not in out and "zzz" not in out


@pytest.mark.parametrize("name", ["BUDGET_MASTER_KEY", "BUDGET_BLIND_INDEX_PEPPER", "PIN_PEPPER"])
def test_generated_binary_keys_are_32_bytes(name):
    gk = load("generate_keys")
    assert len(base64.b64decode(gk.GENERATORS[name]())) == 32
