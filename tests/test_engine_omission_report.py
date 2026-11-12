from pathlib import Path

from fplagent_engine.cli import parser
from fplagent_engine.omission_report import build_top_player_omission_report


def test_omission_report_explains_premium_and_family_tradeoffs(tmp_path: Path) -> None:
    output = tmp_path / "omissions.html"

    result = build_top_player_omission_report(output_path=output)
    text = output.read_text(encoding="utf-8")

    assert result["candidate_id"] in text
    assert "Price opportunity cost, not minutes" in text
    assert "Wins one family, not the synthesis" in text
    assert "Haaland" in text
    assert "Calafiori" in text
    assert "5W regret" in text


def test_omission_report_has_cli_command() -> None:
    assert parser().parse_args(["build-omission-report"]).command == "build-omission-report"
