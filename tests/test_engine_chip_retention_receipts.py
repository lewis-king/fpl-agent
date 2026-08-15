import hashlib
import json
from pathlib import Path

from fplagent_engine.squad_chip_replay import load_squad_chip_retention_results
from fplagent_engine.team_chip_replay import load_team_chip_retention_results


def _receipt(tmp_path: Path) -> Path:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"retained-chip-evidence")
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "version": 1,
                "status": "shadow",
                "artifacts": {
                    "forecast": str(artifact),
                    "forecast_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                },
            }
        ),
        encoding="utf-8",
    )
    return receipt


def test_team_chip_loader_checks_string_artifact_paths(tmp_path: Path) -> None:
    result = load_team_chip_retention_results(_receipt(tmp_path))
    assert result["status"] == "shadow"


def test_squad_chip_loader_checks_string_artifact_paths(tmp_path: Path) -> None:
    result = load_squad_chip_retention_results(_receipt(tmp_path))
    assert result["status"] == "shadow"
