from fplagent_engine.cli import parser
from fplagent_engine.openfpl_benchmark import _candidate_specs


def test_openfpl_top_ten_is_selected_from_a_larger_public_method_grid() -> None:
    candidates = _candidate_specs(26_082)
    assert len(candidates) > 10
    assert {family for family, _ in candidates} == {"random_forest", "xgboost"}


def test_cli_exposes_matched_openfpl_benchmark() -> None:
    args = parser().parse_args(["benchmark-openfpl", "--rebuild", "--top-models", "10"])
    assert args.command == "benchmark-openfpl"
    assert args.rebuild is True
    assert args.top_models == 10
