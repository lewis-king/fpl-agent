from fplagent_engine.top_player_audit import (
    _publication_synthesis_metrics,
    selected_role_watch_required,
)


def _row(*, consensus: str, p_play: float = 0.90, minutes: float = 70.0) -> dict:
    return {
        "participation_consensus": consensus,
        "position": "MID",
        "p_play": p_play,
        "expected_minutes": minutes,
    }


def test_positive_single_source_start_is_not_an_unresolved_role_watch() -> None:
    assert not selected_role_watch_required(
        _row(consensus="single_source_start", p_play=0.86, minutes=70.0)
    )


def test_negative_or_contradictory_lineup_evidence_is_always_watched() -> None:
    assert selected_role_watch_required(_row(consensus="single_source_bench"))
    assert selected_role_watch_required(_row(consensus="source_disagreement"))


def test_missing_coverage_only_watches_material_model_role_risk() -> None:
    assert not selected_role_watch_required(
        _row(consensus="not_covered", p_play=0.88, minutes=59.14)
    )
    assert selected_role_watch_required(_row(consensus="not_covered", p_play=0.84, minutes=59.14))


def test_omission_counterfactuals_exclude_synthesis_rows_barred_from_publication() -> None:
    metrics = _publication_synthesis_metrics(
        [
            {
                "candidate_id": "unsafe-leader",
                "synthesis_regret": 0.1,
                "publication_eligible": False,
            },
            {
                "candidate_id": "safe-winner",
                "synthesis_regret": 0.8,
                "publication_eligible": True,
            },
            {"candidate_id": "legacy-safe", "synthesis_regret": 1.0},
        ]
    )

    assert set(metrics) == {"safe-winner", "legacy-safe"}
