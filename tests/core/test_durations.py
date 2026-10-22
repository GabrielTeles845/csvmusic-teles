import pytest

from csvmusic.core.durations import parse_duration


@pytest.mark.parametrize("value, unit, expected", [
	("2:57", "auto", (177500, 1)),
	("02:57", "ms", (177500, 1)),
	("10:05", "auto", (605500, 1)),
	("1:02:57", "auto", (3777500, 1)),
	("177000", "ms", (177000, 0)),
	("177000", "auto", (177000, 0)),
	("177", "auto", (177000, 1)),
	("177", "s", (177000, 1)),
	("177.4", "s", (177400, 1)),
	("187400.0", "ms", (187400, 0)),
	("2.57", "auto", (177500, 1)),
	("2,57", "auto", (177500, 1)),
	("2.75", "auto", (2750, 1)),
	("", "auto", (0, None)),
	("nan", "auto", (0, None)),
	("abc", "auto", (0, None)),
	("2:75", "auto", (0, None)),
	("0:00", "auto", (0, None)),
	(None, "auto", (0, None)),
])
def test_parse_duration(value, unit, expected):
	assert parse_duration(value, unit) == expected
