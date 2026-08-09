from fplagent_data.veterans import _category, _normalise_header, _season_from_timestamp


def test_season_inference() -> None:
    assert _season_from_timestamp("2026-05-24T21:16:36+00:00") == "2025-26"
    assert _season_from_timestamp("2025-08-20T12:00:00+00:00") == "2025-26"


def test_header_normalisation() -> None:
    assert _normalise_header("Vet WC ownership %", 1) == "vet_wc_ownership_percent"


def test_table_category() -> None:
    assert _category("MainTrades", ["from", "to", "freq"]) == "transfer_pairs"
    assert _category("Captains", ["player", "vet_percent"]) == "captaincy"

