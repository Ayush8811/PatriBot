import pytest

from patribot.planner.names import display_train_name

CODES = {"KOAA", "JAT", "HWH", "BKN", "NDLS", "RJPB", "MAU", "ANVT"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("RAJDHANI EXPRES", "Rajdhani Express"),
        (
            "KOAA JAT EXPRES",
            "KOAA JAT Express",
        ),  # JAT is not in CODES here, but 3-letter codes stay readable either way
        ("HWH BKN EXPRESS", "HWH BKN Express"),
        ("NDLS SHATABDI", "NDLS Shatabdi"),
        ("RJPB TEJAS RAJ", "RJPB Tejas Rajdhani"),
        ("MAU ANVT SF EXP", "MAU ANVT SF Express"),
        ("NDLS GARIB RATH", "NDLS Garib Rath"),
        ("Howrah Rajdhani", "Howrah Rajdhani"),
        ("", ""),
        (None, ""),
    ],
)
def test_display_train_name(raw, expected):
    assert display_train_name(raw, CODES) == expected
