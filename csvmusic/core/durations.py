# tabs only
"""Parse song durations written by people and exports ("2:57", "1:02:57", "177", "177000")."""
import math
import re
from typing import Optional, Tuple

_CLOCK = re.compile(r"^(?:(\d{1,2}):)?(\d{1,3}):(\d{2})$")
_MINUTES_DOT = re.compile(r"^(\d{1,2})[.,](\d{2})$")
_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")

# Anything at or above one hour, written as a bare integer, is read as milliseconds
# unless the column says otherwise (a 3600 s song is rarer than a 3.6 s value in ms).
_SECONDS_LIMIT = 3600


def parse_duration(value: object, unit: str = "auto") -> Tuple[int, Optional[int]]:
	"""
	Return (duration_ms, precision_s) for one cell.

	unit: "ms" when the column says milliseconds, "s" for seconds, "auto" otherwise.
	- "m:ss" and "h:mm:ss" only say the whole second, so the value is the middle of
	  that second (+500 ms) with precision 1 s.
	- "2.57"/"2,57" is read as m:ss only when unit is "auto" (a duration column
	  without unit) and the seconds part is below 60.
	- Bare numbers: milliseconds when unit is "ms" or (in "auto") when >= 3600;
	  seconds otherwise.
	Empty or unreadable cells give (0, None).
	"""
	text = str(value if value is not None else "").strip().replace(" ", "")
	if not text or text.casefold() in {"nan", "none", "-", "--"}:
		return 0, None

	clock = _CLOCK.match(text)
	if clock:
		hours = int(clock.group(1) or 0)
		minutes = int(clock.group(2))
		seconds = int(clock.group(3))
		if seconds >= 60 or (clock.group(1) is not None and minutes >= 60):
			return 0, None
		total = hours * 3600 + minutes * 60 + seconds
		if total <= 0:
			return 0, None
		return total * 1000 + 500, 1

	if unit == "auto":
		dotted = _MINUTES_DOT.match(text)
		if dotted and int(dotted.group(2)) < 60:
			total = int(dotted.group(1)) * 60 + int(dotted.group(2))
			if total > 0:
				return total * 1000 + 500, 1

	if not _NUMBER.match(text):
		return 0, None
	number = float(text.replace(",", "."))
	if not math.isfinite(number) or number <= 0:
		return 0, None
	if unit == "ms" or (unit == "auto" and number >= _SECONDS_LIMIT):
		return int(round(number)), 0
	return int(round(number * 1000)), 1


# A column of bare numbers whose median is above this is in milliseconds (10 000 s would be a 2h46 song).
_COLUMN_MS_MEDIAN = 10000


def _bare_number(value: object) -> Optional[float]:
	"""The value of a cell written as a plain number (not "m:ss" nor "2.57" minutes), else None."""
	text = str(value if value is not None else "").strip().replace(" ", "")
	if not _NUMBER.match(text):
		return None
	dotted = _MINUTES_DOT.match(text)
	if dotted and int(dotted.group(2)) < 60:
		return None
	number = float(text.replace(",", "."))
	return number if math.isfinite(number) and number > 0 else None


def parse_duration_column(values: list, unit: str = "auto") -> list[Tuple[int, Optional[int]]]:
	"""parse_duration for a whole column, deciding seconds or milliseconds once for all its bare numbers.

	Value by value, a 1 h+ song written in seconds (3725) looked like milliseconds (3.7 s). Without a unit
	in the header, the median of the column's bare numbers decides: above 10 000 means milliseconds.
	Clock ("2:57") and "2.57" cells keep their own reading.
	"""
	if unit != "auto":
		return [parse_duration(value, unit) for value in values]
	numbers = sorted(number for number in (_bare_number(value) for value in values) if number is not None)
	if not numbers:
		return [parse_duration(value, unit) for value in values]
	middle = len(numbers) // 2
	median = numbers[middle] if len(numbers) % 2 else (numbers[middle - 1] + numbers[middle]) / 2
	number_unit = "ms" if median > _COLUMN_MS_MEDIAN else "s"
	return [
		parse_duration(value, number_unit if _bare_number(value) is not None else unit)
		for value in values
	]

