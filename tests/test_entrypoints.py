from __future__ import annotations

import sys
from pathlib import Path

import pytest

from llm8g.cli import main


def test_cli_help_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "serve" in capsys.readouterr().out


def test_gateway_compatibility_entrypoint_imports() -> None:
    gateway_dir = Path(__file__).resolve().parents[1] / "gateway"
    sys.path.insert(0, str(gateway_dir))
    try:
        import gateway  # type: ignore[import-not-found]

        assert gateway.app is not None
        assert gateway.MODEL_NAME
    finally:
        sys.path.remove(str(gateway_dir))

def test_cli_unknown_command_exits() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["unknown"])
    assert exc.value.code != 0
