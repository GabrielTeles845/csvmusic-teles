# tabs only
from typing import Dict, List, Optional, Tuple, Set, Literal
import re, time, unicodedata
from ytmusicapi import YTMusic

CONFIDENCE_MIN = 0.6
SEARCH_LIMIT = 12
ALT_SEARCH_LIMIT = 24
RATE_LIMIT_S = 0.35
DURATION_TOLERANCE_RATIO = 0.10
SHORT_TRACK_MAX_SECONDS = 45
SHORT_TRACK_TOLERANCE_SECONDS = 8
SEARCH_RETRY_COUNT = 2
SEARCH_RETRY_SLEEP_S = 0.9
EXACT_DURATION_BONUS = 0.05
# Lengths filled in later from another catalog may describe another version.
_UNRELIABLE_DURATION_SOURCES = {"deezer", "itunes", "musicbrainz", "estimated"}

_PENALTY_TERMS = {"cover","sped","slowed","nightcore","8d","reverb","mashup","karaoke","instrumental","demo","tribute","soundalike"}
_VERSION_PATTERNS = {
	"live": r"\blive\b",
	"acoustic": r"\bacoustic\b",
	"extended": r"\bextended\b|\blong version\b",
	# A bare "mix" is usually a mastering note ("2009 Mix", "Mono Mix",
	# "Stereo Mix"), not a remix; only club-style mixes count.
	"remix": r"\bremix(?:ed)?\b|\b(?:club|dub|dance|vocal)\s+mix\b",
	"edit": r"\bedit\b|\bradio version\b",
	"single": r"\bsingle version\b|\boriginal single\b|\bu\.?s\.? single\b",
	"remaster": r"\bremaster(?:ed)?\b",
	"album": r"\balbum version\b",
}
_CAST_PENALTY_TERMS = {"cast","original cast","tribute band","musical","orchestra"}
# A bracket counts as a guest credit only when it holds a whole credit word,
# so "(Defeated)" or "(Feather Mix)" stay part of the title.
_FEAT_BRACKET = re.compile(r"\s*[\(\[][^\)\]]*\b(?:feat|ft|featuring)\b[^\)\]]*[\)\]]", re.I)

def _norm_text(s: str) -> str:
	text = unicodedata.normalize("NFKC", (s or "").casefold())
	return re.sub(r"\s+", " ", text).strip()

def _toks(s: str) -> set:
	text = _norm_text(s)
	return {tok for tok in re.findall(r"\w+", text, flags=re.UNICODE) if any(ch.isalnum() for ch in tok)}

def _candidate_artist_text(cand: Dict) -> str:
	if cand.get("artists"):
		try:
			return ", ".join(a.get("name", "") for a in cand["artists"])
		except Exception:
			pass
	return cand.get("author", "") or ""

def _candidate_album_text(cand: Dict) -> str:
	# Works for requested tracks too: both carry "album" as text or a dict.
	album = cand.get("album")
	if isinstance(album, dict):
		return str(album.get("name") or album.get("title") or "").strip()
	if isinstance(album, str):
		return album.strip()
	return ""

def _candidate_version_markers(cand: Dict) -> Set[str]:
	# YouTube Music may hide a version in the song title while exposing it in
	# the album, such as a clean song title attached to the album "Live Evil".
	return _version_markers(" ".join((str(cand.get("title") or ""), _candidate_album_text(cand))))

def _artist_names(artists) -> List[str]:
	names: List[str] = []
	if not isinstance(artists, list):
		return names
	for artist in artists:
		if not isinstance(artist, dict):
			continue
		name = (artist.get("name") or "").strip()
		if name:
			names.append(name)
	return names

def _result_author(result: Dict, artists) -> str:
	for key in ("author", "channel", "uploader", "name"):
		value = result.get(key)
		if isinstance(value, str) and value.strip():
			return value.strip()
	artist_names = _artist_names(artists)
	if artist_names:
		return ", ".join(artist_names)
	return ""

def _has_term(text: str, term: str) -> bool:
	# Whole words only: "Demons" is not a demo, "Discover" is not a cover and
	# "Castle" is not a cast.
	pattern = r"\b" + r"\s+".join(re.escape(part) for part in term.split()) + r"\b"
	return re.search(pattern, text, flags=re.I) is not None

def _overlap_ratio(needle: set, haystack: set) -> float:
	return len(needle & haystack) / max(1, len(needle))


def _contains_non_latin_letters(value: str) -> bool:
	for char in value or "":
		if not char.isalpha():
			continue
		name = unicodedata.name(char, "")
		if "LATIN" not in name:
			return True
	return False


def _version_markers(value: str) -> Set[str]:
	text = _norm_text(value)
	return {marker for marker, pattern in _VERSION_PATTERNS.items() if re.search(pattern, text, flags=re.I)}

# Spotify appends release qualifiers after " - " ("Country House - 2012
# Remaster", "Song - Live at Leeds"). They describe the version, not the
# title, so they leave the title core and survive only as version markers.
_QUALIFIER = (
	r"(?:\d{4}\s+)?(?:digital(?:ly)?\s+)?re-?master(?:ed)?(?:\s+\d{4})?(?:\s+(?:version|edition))?"
	r"|radio\s+(?:edit|version)|single\s+version|album\s+version|original\s+(?:single\s+)?version"
	r"|(?:u\.?s\.?\s+)?single\s+version|(?:mono|stereo)(?:\s+(?:version|mix))?|(?:\d{4}\s+)?(?:stereo\s+|mono\s+)?mix"
	r"|live(?:\s+.*)?|acoustic(?:\s+.*)?|from\s+.*|edit|extended(?:\s+.*)?|bonus\s+track|demo(?:\s+version)?"
)
_DASH_SUFFIX = re.compile(r"\s+[-–—]\s+(?:" + _QUALIFIER + r")\s*$", re.I)
_QUALIFIER_BRACKET = re.compile(r"\s*[\(\[]\s*(?:" + _QUALIFIER + r")\s*[\)\]]", re.I)
_GUEST_BRACKET = re.compile(r"[\(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s+([^\)\]]+)[\)\]]", re.I)
_GUEST_SPLIT = re.compile(r"\s*(?:,|&|\band\b|\bx\b)\s*", re.I)


def split_title(title: str) -> Tuple[str, Set[str], List[str]]:
	"""Split a catalog title into (title core, version markers, guest artists).

	"Country House - 2012 Remaster" -> ("Country House", {"remaster"}, []).
	"Song (feat. A & B)" -> ("Song", set(), ["A", "B"]).
	"""
	raw = title or ""
	markers = _version_markers(raw)
	guests: List[str] = []
	for match in _GUEST_BRACKET.finditer(raw):
		for name in _GUEST_SPLIT.split(match.group(1)):
			name = name.strip()
			if name and name not in guests:
				guests.append(name)
	core = _GUEST_BRACKET.sub(" ", raw)
	core = _FEAT_BRACKET.sub(" ", core)
	core = _DASH_SUFFIX.sub("", core.rstrip())
	core = _QUALIFIER_BRACKET.sub(" ", core)
	core = re.sub(r"\s+", " ", core).strip()
	return (core or raw.strip()), markers, guests

def _duration_s(d: Optional[int | str]) -> int:
	try:
		if d is None:
			return 0
		if isinstance(d, str):
			text = d.strip()
			if not text:
				return 0
			if ":" in text:
				total = 0
				for part in text.split(":"):
					total = total * 60 + int(part)
				return total
			return int(float(text))
		return int(d)
	except Exception:
		return 0

def _track_duration_s(track: Dict) -> int:
	try:
		return int(round((track.get("duration_ms") or 0) / 1000))
	except Exception:
		return 0

def _duration_precision_s(track: Dict) -> float:
	# "m:ss" from a spreadsheet or the Spotify page is only exact to 1 s.
	try:
		return max(0.0, float(track.get("duration_precision_s") or 0))
	except Exception:
		return 0.0

def _duration_delta_s(track: Dict, cand: Dict) -> Optional[float]:
	"""Length difference in seconds, minus the requested length's precision."""
	track_s = _track_duration_s(track)
	cand_s = _duration_s(cand.get("duration_seconds"))
	if track_s <= 0 or cand_s <= 0:
		return None
	return max(0.0, abs(track_s - cand_s) - _duration_precision_s(track))

def _duration_is_reliable(track: Dict) -> bool:
	"""True when the length came from the playlist itself (spreadsheet, Spotify...).

	Lengths guessed later from another catalog may belong to another version,
	so they keep the lenient score table.
	"""
	if _track_duration_s(track) <= 0:
		return False
	source = str(track.get("duration_source") or "").strip().casefold()
	return source not in _UNRELIABLE_DURATION_SOURCES

def _duration_score(track: Dict, cand: Dict) -> Tuple[float, float]:
	"""Return (d_score, exact-length bonus) for a candidate."""
	delta = _duration_delta_s(track, cand)
	if delta is None:
		return 0.7, 0.0  # neutral baseline when no duration available
	if _duration_is_reliable(track):
		# A trusted length separates live, extended, radio edit, sped-up and
		# music-video uploads on its own, so the table is steeper.
		for limit, value in ((2, 1.0), (6, 0.95), (12, 0.8), (20, 0.6), (30, 0.4)):
			if delta <= limit:
				return value, (EXACT_DURATION_BONUS if limit == 2 else 0.0)
		return 0.2, 0.0
	for limit, value in ((6, 1.0), (12, 0.9), (20, 0.78), (30, 0.62)):
		if delta <= limit:
			return value, 0.0
	return 0.45, 0.0

def _duration_within_tolerance(track: Dict, cand: Dict) -> bool:
	track_s = _track_duration_s(track)
	delta = _duration_delta_s(track, cand)
	if delta is None:
		return True
	if track_s <= SHORT_TRACK_MAX_SECONDS:
		return delta <= SHORT_TRACK_TOLERANCE_SECONDS
	return delta <= max(1.0, track_s * DURATION_TOLERANCE_RATIO)

def _score(track: Dict, cand: Dict) -> float:
	# Score title and artist separately so "tribute to ARTIST" in the title
	# does not masquerade as an actual artist match.
	# Compare title cores: Spotify suffixes such as " - 2012 Remaster" and
	# guest credits are not part of the song name on YouTube Music.
	track_core, _track_markers, track_guests = split_title(track.get("title") or "")
	_cand_core, _cand_markers, cand_guests = split_title(cand.get("title") or "")
	track_title_tokens = _toks(track_core)
	track_artist_tokens = _toks(" ".join([track.get("artists") or ""] + track_guests))
	cand_title = cand.get("title") or ""
	cand_art = _candidate_artist_text(cand)
	cand_title_tokens = _toks(cand_title)
	cand_artist_tokens = _toks(" ".join([cand_art] + cand_guests))
	title_overlap = _overlap_ratio(track_title_tokens, cand_title_tokens)
	artist_overlap = _overlap_ratio(track_artist_tokens, cand_artist_tokens)

	# duration (CSV may not have; cand might)
	sp_s = _track_duration_s(track)
	yt_s = _duration_s(cand.get("duration_seconds"))
	d_score, exact_length_bonus = _duration_score(track, cand)

	# channel boost
	channel = _norm_text(cand.get("author") or "")
	ch_boost = 0.15 if ("topic" in channel or "official" in channel) else 0.0

	# penalties
	titleblob = _norm_text(cand_title + " " + cand_art)
	# Read markers from the requested album too, mirroring the candidate side,
	# so a track from "Live at Leeds" is not steered to the studio version.
	requested_title_versions = _version_markers(track.get("title") or "")
	requested_album_versions = _version_markers(_candidate_album_text(track)) - requested_title_versions
	requested_versions = requested_title_versions | requested_album_versions
	candidate_versions = _candidate_version_markers(cand)
	p_pen = 0.0
	for t in _PENALTY_TERMS:
		if _has_term(titleblob, t):
			p_pen += 0.10
	if requested_versions:
		for marker in requested_versions - candidate_versions:
			# A remaster is the same recording; its absence is not a penalty.
			# Album names are weaker evidence ("Live Through This" is a studio
			# album), so a marker only the album carries costs less.
			if marker == "remaster":
				continue
			p_pen += 0.34 if marker in requested_title_versions else 0.10
		for marker in candidate_versions - requested_versions:
			p_pen += 0.03 if marker == "remaster" else 0.26
	else:
		# Prefer the ordinary studio/catalog version when Spotify did not ask
		# for a particular variant. Remasters are usually equivalent releases.
		p_pen += 0.30 * len(candidate_versions - {"remaster"})
	if artist_overlap == 0.0:
		for t in _CAST_PENALTY_TERMS:
			if _has_term(titleblob, t):
				p_pen += 0.18
	if _has_term(titleblob, "tribute") and artist_overlap < 0.5:
		p_pen += 0.25
	version_boost = 0.14 if requested_versions and requested_versions == candidate_versions else 0.0
	total = max(0.0, d_score * 0.35 + title_overlap * 0.35 + artist_overlap * 0.25 + ch_boost + version_boost + exact_length_bonus - p_pen)
	# YouTube Music frequently returns an official translated title for Japanese
	# and other non-Latin catalog entries. Exact duration, a catalog-song result,
	# and compatible version markers are stronger evidence than token overlap in
	# that case, because the two titles may legitimately share no characters.
	translated_catalog_match = (
		_contains_non_latin_letters(track.get("title") or "")
		and cand.get("source") == "music"
		and sp_s > 0
		and yt_s > 0
		and abs(sp_s - yt_s) <= 3
		and requested_versions == candidate_versions
		and not any(_has_term(titleblob, term) for term in _PENALTY_TERMS)
	)
	if translated_catalog_match:
		total = max(total, 0.68)
	return min(total, 0.99)

def _clean_title_artist(title: str, artists: str) -> str:
	# Basic collapse of whitespace and stray separators for searching
	q = f"{title} {artists}".strip()
	q = re.sub(r"\s+", " ", q)
	q = q.replace(" - ", " ")
	q = q.replace("–", " ").replace("—", " ")
	return q.strip()

def _strip_noise(title: str) -> str:
	# Remove common bracketed qualifiers that hurt search recall
	# e.g., (feat. ...), [Official Video], (Live), etc.
	s = _FEAT_BRACKET.sub(" ", title)
	s = re.sub(r"[\(\[][Oo]fficial[^\)\]]*[\)\]]", " ", s)
	s = re.sub(r"[\(\[][Ll]ive[^\)\]]*[\)\]]", " ", s)
	s = re.sub(r"[\(\[][Rr]emix[^\)\]]*[\)\]]", " ", s)
	# Remove any empty brackets left behind
	s = re.sub(r"[\(\)\[\]]", " ", s)
	return re.sub(r"\s+", " ", s).strip()

def _query_variants(track: Dict) -> List[str]:
	"""
	Generate a small set of search queries to improve recall across
	"&" vs "and", hyphens, and bracketed noise.
	Order variants from most specific to broader fallbacks.
	"""
	title = track.get("title", "") or ""
	artists = track.get("artists", "") or ""
	isrc = track.get("isrc")

	base_title = title
	core_title, _markers, _guests = split_title(base_title)
	clean_title = _strip_noise(base_title)
	core = _clean_title_artist(core_title, artists)
	base = _clean_title_artist(base_title, artists)
	clean = _clean_title_artist(clean_title, artists)

	variants: List[str] = []
	if isrc:
		variants.append(f"{isrc} {core}")

	# The title core comes first: Spotify suffixes like " - 2012 Remaster"
	# only add noise to the YouTube Music search.
	variants.append(core)
	variants.append(base)
	if clean != base:
		variants.append(clean)

	# Swap common conjunction styles
	if "&" in base:
		variants.append(base.replace("&", "and"))
	if re.search(r"\band\b", base, flags=re.I):
		variants.append(re.sub(r"\band\b", "&", base, flags=re.I))

	# Hyphen to space (already mostly handled in _clean_title_artist)
	if "-" in base:
		variants.append(base.replace("-", " "))

	# Deduplicate while preserving order
	seen: Set[str] = set()
	out: List[str] = []
	for q in variants:
		qq = re.sub(r"\s+", " ", q).strip()
		if qq and qq not in seen:
			seen.add(qq)
			out.append(qq)
	return out

SearchSource = Literal["music", "videos", "all"]


def _search_filter(yt: YTMusic, q: str, search_filter: str, limit: int) -> List[Dict]:
	res = yt.search(q, filter=search_filter, limit=limit) or []
	cands: List[Dict] = []
	source = "music" if search_filter == "songs" else "videos"
	for r in res:
		vid = r.get("videoId")
		if not vid:
			continue
		artists = r.get("artists")
		author = _result_author(r, artists)
		cands.append({
			"videoId": vid,
			"title": r.get("title"),
			"artists": artists if search_filter == "songs" else None,
			"author": author,
			"channel": author,
			"duration_seconds": _duration_s(r.get("duration_seconds") or r.get("duration")),
			"album": r.get("album"),
			"source": source,
		})
	return cands


def _search(yt: YTMusic, q: str, limit: int = SEARCH_LIMIT, source_mode: SearchSource = "all") -> List[Dict]:
	cands: List[Dict] = []
	if source_mode in ("music", "all"):
		cands.extend(_search_filter(yt, q, "songs", limit))
	if source_mode in ("videos", "all"):
		cands.extend(_search_filter(yt, q, "videos", limit))
	return cands


def _rank_candidates(
	yt: YTMusic,
	track: Dict,
	limit: int = SEARCH_LIMIT,
	source_mode: SearchSource = "all",
	*,
	enforce_duration: bool = True,
) -> List[Dict]:
	seen_vids: Set[str] = set()
	all_cands: List[Dict] = []
	for q in _query_variants(track):
		cands = _search(yt, q, limit, source_mode)
		for cand in cands:
			vid = cand.get("videoId")
			if not vid or vid in seen_vids:
				continue
			seen_vids.add(vid)
			all_cands.append(cand)

	scored: List[Dict] = []
	for cand in all_cands:
		s = _score(track, cand)
		item = dict(cand)
		item["score"] = s
		item["version_markers"] = sorted(_candidate_version_markers(cand))
		# Results outside the duration tolerance stay visible as options, but
		# flagged: they are never picked automatically and they do not make
		# the search look empty (which would trigger retries and abort a batch).
		item["duration_mismatch"] = not _duration_within_tolerance(track, cand)
		scored.append(item)

	def priority(candidate: Dict) -> tuple[int, int, int, float, int]:
		score = float(candidate.get("score", 0.0) or 0.0)
		is_music = 1 if candidate.get("source") == "music" else 0
		fits = 0 if enforce_duration and candidate.get("duration_mismatch") else 1
		# Prefer a confidently matching YouTube Music song over a regular
		# YouTube video. Below the confidence threshold, relevance still wins
		# so a poor music result cannot displace a usable video fallback.
		return (fits, 1 if score >= CONFIDENCE_MIN else 0, is_music if score >= CONFIDENCE_MIN else 0, score, is_music)

	return sorted(scored, key=priority, reverse=True)


def _best_option(options: List[Dict]) -> Tuple[Optional[Dict], float]:
	"""Best automatic pick: the top option within the duration tolerance."""
	for option in options:
		if option.get("duration_mismatch"):
			continue
		score = float(option.get("score", 0.0) or 0.0)
		return (option if score >= CONFIDENCE_MIN else None), score
	return None, 0.0

def find_best(yt: YTMusic, track: Dict) -> Tuple[Optional[Dict], float, List[Dict]]:
	options = _rank_candidates(yt, track)
	if not options:
		last_exc: Exception | None = None
		for _ in range(SEARCH_RETRY_COUNT):
			time.sleep(SEARCH_RETRY_SLEEP_S)
			try:
				fresh = YTMusic()
				options = _rank_candidates(fresh, track)
			except Exception as exc:
				last_exc = exc
				continue
			if options:
				break
		if not options and last_exc is not None:
			raise last_exc
	if not options:
		return None, 0.0, []
	best, score = _best_option(options)
	return best, score, options

def _format_seconds(seconds: int) -> str:
	if seconds <= 0:
		return "?"
	return f"{seconds // 60}:{seconds % 60:02d}"


def _describe_option(option: Dict) -> str:
	title = option.get("title") or ""
	author = _candidate_artist_text(option)
	length = _format_seconds(_duration_s(option.get("duration_seconds")))
	score = float(option.get("score", 0.0) or 0.0)
	flags = [str(option.get("source") or "?"), length, f"score {score:.2f}"]
	if option.get("duration_mismatch"):
		flags.append("duration_mismatch")
	return f"'{title}' by '{author}' ({option.get('videoId')}; {', '.join(flags)})"


def skip_log_line(track: Dict, confidence: float, options: List[Dict], error: str | None = None) -> str:
	"""Describe a skipped track with the queries actually sent and the best candidate."""
	title = track.get("title") or ""
	artists = track.get("artists") or ""
	length = _format_seconds(_track_duration_s(track))
	if error:
		reason = f"error={error}"
	elif not options:
		reason = "no search results"
	elif all(option.get("duration_mismatch") for option in options):
		reason = "every result has the wrong length"
	else:
		reason = f"no candidate >= {CONFIDENCE_MIN:.2f} (confidence={confidence:.2f})"
	parts = [
		f"match skip: '{title}' by '{artists}' (length {length}): {reason}",
		f"queries={_query_variants(track)!r}",
	]
	fitting = [option for option in options if not option.get("duration_mismatch")]
	if fitting:
		parts.append(f"best={_describe_option(fitting[0])}")
	mismatched = [option for option in options if option.get("duration_mismatch")]
	if mismatched:
		parts.append(f"best_wrong_length={_describe_option(mismatched[0])}")
	return " | ".join(parts)


def more_candidates(track: Dict, exclude_ids: Set[str] | None = None, limit: int = ALT_SEARCH_LIMIT, source_mode: SearchSource = "all") -> List[Dict]:
	exclude = set(exclude_ids or [])
	yt = YTMusic()
	# Alternatives are explicitly user-selected. Keep duration-mismatched results
	# visible (flagged) while duration scoring still ranks likely versions first.
	options = _rank_candidates(yt, track, limit, source_mode, enforce_duration=False)
	visible = [opt for opt in options if opt.get("videoId") not in exclude]
	# Keep score order within each source, but make the manual browser's source
	# order predictable: YouTube Music first, regular YouTube second.
	return sorted(visible, key=lambda opt: 0 if opt.get("source") == "music" else 1)

def batch_match(tracks: List[Dict]) -> List[Dict]:
	"""
	Input: list of track dicts (from csv_import.tracks_from_csv)
	Output: list of results with either 'match' or 'skipped': True
	"""
	yt = YTMusic()  # anonymous client; should work for public search endpoints
	results = []
	for t in tracks:
		res = {"track": t, "skipped": False, "match": None, "confidence": 0.0, "options": []}
		try:
			match, conf, options = find_best(yt, t)
			res["confidence"] = conf
			res["options"] = options
			if match is None:
				res["skipped"] = True
			else:
				res["match"] = match
		except Exception as e:
			res["skipped"] = True
			res["error"] = str(e)
		results.append(res)
		time.sleep(RATE_LIMIT_S)
	return results
