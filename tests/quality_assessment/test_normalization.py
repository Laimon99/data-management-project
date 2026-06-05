from quality_assessment.normalization import (
    in_milan_area,
    is_missing,
    normalize_text,
    parse_float,
    parse_int,
)


def test_missing_markers_are_detected() -> None:
    assert is_missing(None)
    assert is_missing("NaN")
    assert is_missing(float("nan"))
    assert is_missing("")
    assert is_missing([])
    assert not is_missing("Milano")


def test_italian_numbers_are_parsed() -> None:
    assert parse_float("4,3") == 4.3
    assert parse_float("9.4") == 9.4
    assert parse_float("1.234,56") == 1234.56
    assert parse_float("1,234.56") == 1234.56
    assert parse_int("(1.088 recensioni)") == 1088
    assert parse_int("1,088 reviews") == 1088
    assert parse_int("-5 reviews") == -5


def test_text_normalization_folds_accents_and_punctuation() -> None:
    assert normalize_text("Ristorante Sant'Ambroeus!") == "ristorante sant ambroeus"


def test_milan_area_bounds() -> None:
    assert in_milan_area(45.4642, 9.19)
    assert not in_milan_area(41.9028, 12.4964)
