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

