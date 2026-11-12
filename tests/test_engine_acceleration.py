from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from fplagent_engine.acceleration import cuda_available
from fplagent_engine.semantic_hash import semantic_parquet_sha256
from fplagent_engine.tournament import (
    _autosub_weights,
    _score_candidates_cpu,
    _score_candidates_cuda,
)


def _candidate(
    candidate_id: str,
    starters: list[int],
    bench: list[int],
) -> dict:
    lineup = {
        "starters": starters,
        "bench_order": bench,
        "captain": 8,
        "vice_captain": 13,
        "formation": "test",
    }
    return {
        "candidate_id": candidate_id,
        "selected": list(range(1, 16)),
        "lineups": {"1": dict(lineup), "2": dict(lineup)},
    }


def test_cuda_candidate_scoring_is_exactly_equal_to_cpu() -> None:
    if not cuda_available():
        pytest.skip("CUDA is unavailable")
    positions = {
        1: "GK",
        2: "GK",
        **{element: "DEF" for element in range(3, 8)},
        **{element: "MID" for element in range(8, 13)},
        **{element: "FWD" for element in range(13, 16)},
    }
    meta = {element: {"position": position} for element, position in positions.items()}
    candidates = [
        _candidate(
            "four-four-two",
            [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
            [7, 12, 15, 2],
        ),
        _candidate(
            "three-five-two",
            [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14],
            [6, 7, 15, 2],
        ),
    ]
    rng = np.random.default_rng(20260816)
    points = rng.integers(-3, 121, size=(600, 2, 15), dtype=np.int8)
    played = rng.random((600, 2, 15)) < 0.88
    player_ids = list(range(1, 16))
    events = (1, 2)

    cpu = _score_candidates_cpu(candidates, player_ids, events, points, played, meta)
    gpu = _score_candidates_cuda(candidates, player_ids, events, points, played, meta)

    reference = np.zeros_like(cpu)
    powers = (1 << np.arange(15, dtype=np.uint16)).astype(np.uint16)
    for candidate_index, candidate in enumerate(candidates):
        squad = list(map(int, candidate["selected"]))
        squad_indices = np.asarray([element - 1 for element in squad], dtype=np.int32)
        for event_offset, event in enumerate(events):
            patterns = (
                played[:, event_offset, squad_indices].astype(np.uint16) @ powers
            ).astype(np.uint16)
            unique, inverse = np.unique(patterns, return_inverse=True)
            table = np.vstack(
                [_autosub_weights(candidate, event, int(pattern), meta) for pattern in unique]
            )
            weights = table[inverse]
            reference[:, candidate_index, event_offset] = np.sum(
                points[:, event_offset, squad_indices].astype(np.int16)
                * weights.astype(np.int16),
                axis=1,
            )

    np.testing.assert_array_equal(gpu, cpu)
    np.testing.assert_array_equal(cpu, reference)


def test_semantic_parquet_hash_ignores_only_declared_volatile_columns(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.parquet"
    timestamp_changed = tmp_path / "timestamp-changed.parquet"
    decision_changed = tmp_path / "decision-changed.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [{"event": 1, "element": 2, "expected_points": 5.4, "observed_at": "a"}]
        ),
        first,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [{"event": 1, "element": 2, "expected_points": 5.4, "observed_at": "b"}]
        ),
        timestamp_changed,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [{"event": 1, "element": 2, "expected_points": 5.5, "observed_at": "b"}]
        ),
        decision_changed,
    )
    kwargs = {
        "ignored_columns": {"observed_at"},
        "sort_columns": ("event", "element"),
    }

    baseline = semantic_parquet_sha256(first, **kwargs)

    assert semantic_parquet_sha256(timestamp_changed, **kwargs) == baseline
    assert semantic_parquet_sha256(decision_changed, **kwargs) != baseline
