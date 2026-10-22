# tabs only
import csv
import io
import pathlib
import re
import unicodedata
from typing import Union, List, Dict, Optional
import pandas as pd

from csvmusic.core.log import log

# Canonical column names we expect. Keys are compared after _norm_header():
# lowercase, accents removed (NFKD), punctuation dropped, spaces collapsed.
# Includes the names used by TuneMyMusic, Exportify and Portuguese/Spanish exports.
_CANON = {
	"track name": "Track name",
	"track": "Track name",
	"track title": "Track name",
	"title": "Track name",
	"song": "Track name",
	"song name": "Track name",
	"song title": "Track name",
	"faixa": "Track name",
	"nome da faixa": "Track name",
	"musica": "Track name",
	"nome da musica": "Track name",
	"titulo": "Track name",
	"titulo da musica": "Track name",
	"cancion": "Track name",
	"nombre de la cancion": "Track name",
	"titulo de la cancion": "Track name",
	"pista": "Track name",
	"nombre de la pista": "Track name",
	"tema": "Track name",
	"artist name": "Artist name",
	"artist names": "Artist name",
	"artist": "Artist name",
	"artists": "Artist name",
	"artista": "Artist name",
	"artistas": "Artist name",
	"nome do artista": "Artist name",
	"nombre del artista": "Artist name",
	"interprete": "Artist name",
	"album": "Album",
	"album name": "Album",
	"nome do album": "Album",
	"nombre del album": "Album",
	"playlist name": "Playlist name",
	"playlist": "Playlist name",
	"nome da playlist": "Playlist name",
	"nombre de la playlist": "Playlist name",
	"nombre de la lista": "Playlist name",
	"isrc": "ISRC",
	"spotify id": "Spotify - id",
	"track uri": "Spotify - id",
	"spotify uri": "Spotify - id",
	"link": "Link",
	"url": "Link",
	"track url": "Link",
	"spotify url": "Link",
	"spotify link": "Link",
	"enlace": "Link",
	"release date": "Release date",
	"data de lancamento": "Release date",
	"lancamento": "Release date",
	"fecha de lanzamiento": "Release date",
	"cover url": "Cover URL",
	"artwork url": "Cover URL",
	"capa": "Cover URL",
	# Optional/ignored if missing:
	"type": "Type",
	"duration ms": "Duration (ms)",
	"track number": "Track number",
	"track no": "Track number",
	"numero da faixa": "Track number",
	"disc number": "Disc number",
	"disc no": "Disc number",
	"numero do disco": "Disc number",
}

# Minimum set required to build track entries. External IDs and ISRC are useful
# hints when present, but downloads only need title/artist/playlist metadata.
_REQUIRED = ["Track name", "Artist name", "Playlist name"]
_OPTIONAL_TEXT = ["Album", "ISRC", "Spotify - id", "Link", "Release date", "Cover URL"]
_DELIMITERS = [",", ";", "\t", "|"]
_ENCODINGS = ["utf-8-sig", "cp1252", "latin-1"]
_SPOTIFY_TRACK_URL = re.compile(r"open\.spotify\.com/(?:intl-[a-z-]+/)?track/([A-Za-z0-9]{16,32})", re.IGNORECASE)


def _norm_header(value: object) -> str:
	"""Header key for matching: no accents, lowercase, alphanumerics and single spaces."""
	text = unicodedata.normalize("NFKD", str(value or "")).replace("\ufeff", "")
	text = "".join(ch for ch in text if not unicodedata.combining(ch) and ch not in "()[]'.")
	text = "".join(ch if ch.isalnum() else " " for ch in text.strip().lower())
	return " ".join(text.split())


_CANON_BY_KEY = {_norm_header(k): v for k, v in _CANON.items()}


def _decode(raw: bytes) -> str:
	for encoding in _ENCODINGS:
		try:
			return raw.decode(encoding)
		except UnicodeDecodeError:
			continue
	return raw.decode("utf-8", errors="replace")


def _recognized_columns(columns) -> int:
	return len({_CANON_BY_KEY[_norm_header(c)] for c in columns if _norm_header(c) in _CANON_BY_KEY})


def _read_csv_robust(path: pathlib.Path) -> pd.DataFrame:
	"""
	Read the CSV trying every common separator and keep the reading that
	recognizes the most known columns (a wrong separator still "works" but
	returns one big column). Handles BOM and Windows/Latin-1 encodings.
	"""
	text = _decode(path.read_bytes())
	sample = "\n".join(text.splitlines()[:50])
	order = list(_DELIMITERS)
	try:
		sniffed = csv.Sniffer().sniff(sample, delimiters="".join(_DELIMITERS)).delimiter
		order.remove(sniffed)
		order.insert(0, sniffed)
	except (csv.Error, ValueError):
		pass

	best: Optional[pd.DataFrame] = None
	best_key = (-1, -1)
	errs = []
	for sep in order:
		try:
			df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False, skipinitialspace=True)
		except Exception as e:
			errs.append(f"sep={sep!r}: {e}")
			continue
		key = (_recognized_columns(df.columns), len(df.columns))
		if key > best_key:
			best, best_key = df, key
	if best is None:
		raise ValueError("Failed to read CSV with multiple strategies:\n" + "\n".join(errs))
	return best

def _normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
	"""
	Return a copy of df with standardized column names per _CANON.
	Matches ignoring case, accents and punctuation. When two columns map to the
	same canonical name, the first one wins and the other keeps its own name.
	"""
	renames = {}
	taken = set()
	for col in df.columns:
		canon = _CANON_BY_KEY.get(_norm_header(col))
		if canon and canon not in taken:
			renames[col] = canon
			taken.add(canon)
	# apply
	out = df.copy()
	if renames:
		out = out.rename(columns=renames)
	return out

def load_csv(path: Union[str, pathlib.Path]) -> pd.DataFrame:
	"""
	Load the CSV and normalize headers.
	Raises FileNotFoundError or ValueError on problems.
	"""
	p = pathlib.Path(path)
	if not p.exists():
		raise FileNotFoundError(str(p))
	df = _read_csv_robust(p)
	df = _normalize_headers(df)
	if "Playlist name" not in df.columns:
		df["Playlist name"] = p.stem
	else:
		df["Playlist name"] = df["Playlist name"].fillna("").astype(str)
		playlist_names = df["Playlist name"].str.strip()
		df.loc[playlist_names == "", "Playlist name"] = p.stem

	# Check required columns (we intentionally do NOT require "Type")
	missing = [c for c in _REQUIRED if c not in df.columns]
	if missing:
		found = ", ".join(str(c) for c in df.columns)
		log(f"CSV import missing columns path={p.name} missing={missing} found=[{found}]")
		raise ValueError(
			f"CSV missing required columns: {missing}. Columns found: {found}. "
			"Accepted names include Track Name/Faixa/Música/Canción and Artist Name/Artista."
		)

	# Normalize key columns to strings (avoid NaN weirdness later)
	for c in _REQUIRED:
		df[c] = df[c].fillna("").astype(str).str.strip()
	for c in _OPTIONAL_TEXT:
		if c in df.columns:
			df[c] = df[c].fillna("").astype(str).str.strip()

	# If present, normalize optional columns
	if "Type" in df.columns:
		df["Type"] = df["Type"].astype(str).fillna("").str.strip().str.lower()
	if "Duration (ms)" in df.columns:
		# Best-effort numeric
		df["Duration (ms)"] = pd.to_numeric(df["Duration (ms)"], errors="coerce").fillna(0).astype(int)
	for column in ("Track number", "Disc number"):
		if column in df.columns:
			df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0).astype(int)

	playlists = list_playlists(df)
	if len(playlists) > 1:
		raise ValueError(
			f"CSV contains multiple playlists ({len(playlists)} found). "
			"Export one playlist at a time from TuneMyMusic and try again."
		)

	return df


def _spotify_track_id(value: object) -> str | None:
	text = str(value or "").strip()
	if not text or text.casefold() == "nan":
		return None
	if text.casefold().startswith("spotify:track:"):
		return text.rsplit(":", 1)[-1] or None
	match = _SPOTIFY_TRACK_URL.search(text)
	if match:
		return match.group(1)
	if "://" in text or "/" in text:
		# A link to some other site is not a Spotify id.
		return None
	return text


def _release_year(value: object) -> int | None:
	text = str(value or "").strip()
	if not text or text.casefold() == "nan":
		return None
	try:
		year = int(text[:4])
	except (TypeError, ValueError):
		return None
	return year if 1000 <= year <= 9999 else None

def list_playlists(df: pd.DataFrame) -> List[str]:
	"""
	Return sorted unique playlist names (non-empty only).
	"""
	if "Playlist name" not in df.columns:
		return []
	pls = df["Playlist name"].dropna().astype(str).map(str.strip)
	return sorted([p for p in pls.unique().tolist() if p != ""])

def _is_valid_track_row(row: pd.Series) -> bool:
	"""
	Heuristic: treat as a track if there's a non-empty Track name.
	We do not rely on source-specific IDs or 'Type' because exports vary.
	"""
	title = str(row.get("Track name", "")).strip()
	return len(title) > 0

def tracks_from_csv(df: pd.DataFrame, playlist: Optional[str] = None) -> List[Dict]:
	"""
	Convert CSV rows to internal track dicts.
	- Optional playlist filter (exact match).
	- Ignores rows that don't look like tracks.
	- Duration is 0 if not provided; downstream matchers can still score by title/artist.
	"""
	work = df
	if playlist:
		work = work[work["Playlist name"] == playlist]

	# Keep only plausible tracks
	mask = work.apply(_is_valid_track_row, axis=1)
	work = work[mask]

	out: List[Dict] = []
	for position, (_, r) in enumerate(work.iterrows(), start=1):
		isrc = str(r.get("ISRC", "")).strip()
		spid = _spotify_track_id(r.get("Spotify - id", "")) or _spotify_track_id(r.get("Link", ""))
		# duration if present
		if "Duration (ms)" in work.columns:
			try:
				dur_ms = int(r.get("Duration (ms)", 0)) if pd.notna(r.get("Duration (ms)")) else 0
			except Exception:
				dur_ms = 0
		else:
			dur_ms = 0

		track_no = int(r.get("Track number", 0) or 0) if "Track number" in work.columns else 0
		disc_no = int(r.get("Disc number", 0) or 0) if "Disc number" in work.columns else 0
		out.append({
			"title": str(r.get("Track name", "")).strip(),
			"artists": str(r.get("Artist name", "")).strip(),
			"album": str(r.get("Album", "")).strip(),
			"playlist": str(r.get("Playlist name", "")).strip(),
			"isrc": isrc if isrc and isrc.lower() != "nan" else None,
			"sp_id": spid,
			"duration_ms": dur_ms,
			"year": _release_year(r.get("Release date", "")),
			"cover_url": str(r.get("Cover URL", "")).strip() or None,
			"track_no": track_no or position,
			"disc_no": disc_no or 1,
		})
	return out
