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


def test_duration_column_in_seconds_keeps_songs_of_an_hour_or_more():
	from csvmusic.core.durations import parse_duration_column

	parsed = parse_duration_column(["245", "3725", "180", ""])
	assert [ms for ms, _ in parsed] == [245000, 3725000, 180000, 0]


def test_duration_column_in_milliseconds_is_still_read_as_milliseconds():
	from csvmusic.core.durations import parse_duration_column

	parsed = parse_duration_column(["245000", "3725", "180000", "2:57", "2.57"])
	assert [ms for ms, _ in parsed] == [245000, 3725, 180000, 177500, 177500]


def test_duration_column_unit_from_header_wins():
	from csvmusic.core.durations import parse_duration_column

	assert parse_duration_column(["245000", "3725"], "s") == [(245000000, 1), (3725000, 1)]


def test_csv_duration_column_without_unit_decides_by_the_whole_column(tmp_path):
	import pandas as pd

	from csvmusic.core.csv_import import load_csv, tracks_from_csv

	path = tmp_path / "lista.csv"
	pd.DataFrame([
		{"Track name": "Curta", "Artist name": "A", "Duration": 245},
		{"Track name": "Longa", "Artist name": "B", "Duration": 3725},
	]).to_csv(path, index=False)
	tracks = tracks_from_csv(load_csv(path))
	assert [track["duration_ms"] for track in tracks] == [245000, 3725000]
