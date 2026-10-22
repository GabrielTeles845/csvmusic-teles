from csvmusic.core.spotify_import import SpotifyImportError, SpotifyPlaylistPrivateError
from csvmusic.ui.spotify_public_scrape import baseline_error_kind, baseline_row, jittered_scroll_delay_ms, merge_captured_duration, metadata_gap_positions, normalized_capture, ordered_playlist_tracks, recover_single_missing_position


def test_normalized_capture_maps_public_row():
	assert normalized_capture({
		"id": "track-id",
		"position": 7,
		"title": " Song ",
		"artists": ["Artist One", "Artist Two"],
		"album": "Album",
		"cover_url": "https://i.scdn.co/image/cover",
	}) == {
		"id": "track-id",
		"position": 7,
		"title": "Song",
		"artists": "Artist One, Artist Two",
		"album": "Album",
		"cover_url": "https://i.scdn.co/image/cover",
	}


def test_playlist_position_filter_excludes_recommendations_and_orders_rows():
	tracks = [
		{"id": "recommended", "position": None},
		{"id": "second", "position": 2},
		{"id": "outside", "position": 4},
		{"id": "first", "position": 1},
	]
	assert [track["id"] for track in ordered_playlist_tracks(tracks, 3)] == ["first", "second"]


def test_normalized_capture_rejects_missing_identity():
	assert normalized_capture({"title": "Song"}) is None


def test_production_scroll_jitter_centers_on_moderate_interval():
	values = [jittered_scroll_delay_ms(350) for _ in range(100)]
	assert all(322 <= value <= 378 for value in values)


def test_metadata_verification_ignores_recommendations_beyond_reported_total():
	tracks = [
		{"album": "Album", "cover_url": "album-cover"},
		{"album": "Album 2", "cover_url": "album-cover-2"},
		{"album": "", "cover_url": "playlist-cover"},
	]

	assert metadata_gap_positions(tracks, "playlist-cover", reported_total=2) == []


def test_metadata_verification_reports_incomplete_playlist_rows():
	tracks = [
		{"album": "Album", "cover_url": "album-cover"},
		{"album": "", "cover_url": "playlist-cover"},
	]

	assert metadata_gap_positions(tracks, "playlist-cover", reported_total=2) == [2]


def test_single_positionless_final_track_is_recovered():
	existing = {
		str(position): {"id": str(position), "position": position}
		for position in range(1, 53)
	}
	captured = [{"id": "last-track", "position": None, "title": "Final Song"}]

	recovered = recover_single_missing_position(captured, existing, 53)

	assert recovered[0]["position"] == 53


def test_ambiguous_positionless_tracks_are_not_guessed():
	existing = {"1": {"id": "1", "position": 1}}
	captured = [
		{"id": "unknown-a", "position": None},
		{"id": "unknown-b", "position": None},
	]

	recovered = recover_single_missing_position(captured, existing, 2)

	assert all(track["position"] is None for track in recovered)


def test_baseline_error_kind_separates_private_from_other_failures():
	assert baseline_error_kind(SpotifyPlaylistPrivateError()) == "private"
	assert baseline_error_kind(SpotifyImportError("Spotify took too long to respond.")) == "error"


def test_normalized_capture_reads_row_duration_as_mss():
	track = normalized_capture({"id": "t", "position": 1, "title": "Song", "artists": ["A"], "duration": "2:57"})

	assert track["duration_ms"] == 177500
	assert track["duration_source"] == "spotify"
	assert track["duration_precision_s"] == 1


def test_normalized_capture_ignores_non_clock_duration_text():
	track = normalized_capture({"id": "t", "position": 1, "title": "Song", "artists": ["A"], "duration": "1979"})

	assert "duration_ms" not in track


def test_baseline_row_keeps_exact_embed_duration_and_page_does_not_replace_it():
	row = baseline_row({"title": "Song", "artists": "A", "duration_ms": 177321}, "t", 1)
	merge_captured_duration(row, {"duration_ms": 177500, "duration_source": "spotify", "duration_precision_s": 1})

	assert row["duration_ms"] == 177321
	assert row["duration_precision_s"] == 0

	empty = baseline_row({"title": "Song", "artists": "A"}, "u", 2)
	merge_captured_duration(empty, {"duration_ms": 177500, "duration_source": "spotify", "duration_precision_s": 1})

	assert empty["duration_ms"] == 177500
	assert empty["duration_precision_s"] == 1


def test_baseline_duration_reaches_the_finished_scan(qt_application):
	from types import SimpleNamespace

	from csvmusic.ui.spotify_public_scrape import SpotifyPublicScrapeDialog

	dialog = SpotifyPublicScrapeDialog()
	emitted = []
	dialog.scrape_finished.connect(emitted.append)
	dialog.running = True
	dialog.session_id = "s"
	playlist = SimpleNamespace(
		name="P", cover_url="playlist-cover", total_count=1, warning=None,
		tracks=[{"sp_id": "t", "title": "Song", "artists": "A", "album": "Al", "cover_url": "album-cover", "duration_ms": 201000}],
	)
	try:
		dialog._baseline_finished(True, playlist, "", "https://open.spotify.com/playlist/x", session="s")
	finally:
		dialog.running = False
		dialog.timer.stop()
		dialog.deleteLater()

	assert emitted[0]["tracks"][0]["duration_ms"] == 201000
