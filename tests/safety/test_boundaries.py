from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SAFETY = Path(__file__).resolve().parents[2] / "src/backend/safety"
_FORBIDDEN = ("backend.agent", "pydantic_ai", "google", "httpx")


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


@pytest.mark.parametrize("path", sorted(_SAFETY.rglob("*.py")), ids=lambda p: p.name)
def test_safety_modules_avoid_model_and_network_imports(path: Path) -> None:
    bad = [
        name
        for name in _imports(path)
        if any(name == f or name.startswith(f + ".") for f in _FORBIDDEN)
    ]

    assert bad == [], f"{path.name} imports {bad}"


def test_the_check_detects_a_forbidden_import(tmp_path: Path) -> None:
    sample = tmp_path / "bad.py"
    sample.write_text("from backend.agent.memory import DIET_CHIPS\nimport httpx\n")

    assert _imports(sample) == ["backend.agent.memory", "httpx"]
