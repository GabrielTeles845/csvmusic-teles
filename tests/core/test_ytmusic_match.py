from csvmusic.core import ytmusic_match


class FakeYTMusic:
	def __init__(self, results):
		self.results = results

	def search(self, _query, filter, limit):
		return self.results.get(filter, [])[:limit]


def test_search_filter_uses_video_author_as_channel():
	yt = FakeYTMusic({
		"videos": [
			{
				"videoId": "abc123",
				"title": "Same Song",
				"author": "Uploader Channel",
				"duration": "3:05",
			}
		]
	})

	results = ytmusic_match._search_filter(yt, "same song", "videos", 10)

	assert results[0]["author"] == "Uploader Channel"
	assert results[0]["channel"] == "Uploader Channel"
	assert results[0]["duration_seconds"] == 185


def test_search_filter_falls_back_to_video_artist_names_for_uploader():
	yt = FakeYTMusic({
		"videos": [
			{
				"videoId": "abc123",
				"title": "Same Song",
				"artists": [{"name": "Uploader One"}, {"name": "Uploader Two"}],
				"duration_seconds": 201,
			}
		]
	})

	results = ytmusic_match._search_filter(yt, "same song", "videos", 10)

	assert results[0]["author"] == "Uploader One, Uploader Two"
	assert results[0]["channel"] == "Uploader One, Uploader Two"


def test_short_tracks_allow_small_absolute_duration_variance():
	track = {"duration_ms": 15000}

	assert ytmusic_match._duration_within_tolerance(track, {"duration_seconds": 22}) is True
	assert ytmusic_match._duration_within_tolerance(track, {"duration_seconds": 24}) is False


def test_alternative_ranking_can_include_duration_mismatch():
	yt = FakeYTMusic({
		"songs": [{
			"videoId": "song-candidate",
			"title": "Tiny Song",
			"artists": [{"name": "Artist"}],
			"duration": "0:30",
		}],
		"videos": [],
	})
	track = {"title": "Tiny Song", "artists": "Artist", "duration_ms": 15000}

	assert ytmusic_match._rank_candidates(yt, track, enforce_duration=True) == []
	assert len(ytmusic_match._rank_candidates(yt, track, enforce_duration=False)) == 1


def test_confident_youtube_music_song_is_preferred_over_higher_scoring_video(monkeypatch):
	yt = FakeYTMusic({
		"songs": [{"videoId": "music", "title": "Song", "artists": [{"name": "Artist"}], "duration": "3:00"}],
		"videos": [{"videoId": "video", "title": "Song", "author": "Artist Official", "duration": "3:00"}],
	})
	track = {"title": "Song", "artists": "Artist", "duration_ms": 180000}

	def fake_score(_track, candidate):
		return 0.75 if candidate["source"] == "music" else 0.95

	monkeypatch.setattr(ytmusic_match, "_score", fake_score)
	options = ytmusic_match._rank_candidates(yt, track)
	assert [option["videoId"] for option in options[:2]] == ["music", "video"]


def test_unconfident_music_result_does_not_displace_confident_video(monkeypatch):
	yt = FakeYTMusic({
		"songs": [{"videoId": "music", "title": "Wrong", "artists": [{"name": "Other"}], "duration": "3:00"}],
		"videos": [{"videoId": "video", "title": "Song", "author": "Artist", "duration": "3:00"}],
	})
	track = {"title": "Song", "artists": "Artist", "duration_ms": 180000}

	def fake_score(_track, candidate):
		return 0.4 if candidate["source"] == "music" else 0.8

	monkeypatch.setattr(ytmusic_match, "_score", fake_score)
	options = ytmusic_match._rank_candidates(yt, track)
	assert options[0]["videoId"] == "video"


def test_manual_alternatives_group_youtube_music_first(monkeypatch):
	options = [
		{"videoId": "video", "source": "videos", "score": 0.95},
		{"videoId": "music", "source": "music", "score": 0.35},
	]
	monkeypatch.setattr(ytmusic_match, "YTMusic", lambda: object())
	monkeypatch.setattr(ytmusic_match, "_rank_candidates", lambda *_args, **_kwargs: options)
	results = ytmusic_match.more_candidates({"title": "Song"})
	assert [result["videoId"] for result in results] == ["music", "video"]


def test_live_and_acoustic_versions_are_strongly_penalized_unless_requested():
	track = {"title": "The Trooper", "artists": "Iron Maiden", "duration_ms": 240000}
	studio = {"title": "The Trooper", "author": "Iron Maiden", "duration_seconds": 240}
	live = {"title": "The Trooper (Live at Rock in Rio)", "author": "Iron Maiden", "duration_seconds": 240}
	acoustic = {"title": "The Trooper (Acoustic)", "author": "Iron Maiden", "duration_seconds": 240}
	assert ytmusic_match._score(track, studio) > ytmusic_match._score(track, live)
	assert ytmusic_match._score(track, studio) > ytmusic_match._score(track, acoustic)
	requested = {"title": "The Trooper Live", "artists": "Iron Maiden", "duration_ms": 240000}
	assert ytmusic_match._score(requested, live) > ytmusic_match._score(requested, studio)


def test_live_album_is_detected_when_song_title_omits_live_marker():
	track = {"title": "War Pigs - 2009 Remaster", "artists": "Black Sabbath", "duration_ms": 475000}
	studio = {"title": "War Pigs (2009 Remaster)", "author": "Black Sabbath", "album": {"name": "Paranoid"}, "duration_seconds": 475}
	live = {"title": "War Pigs (2023 Remaster)", "author": "Black Sabbath", "album": {"name": "Live Evil"}, "duration_seconds": 559}
	assert ytmusic_match._candidate_version_markers(live) >= {"live"}
	assert "live" not in ytmusic_match._candidate_version_markers(studio)
	assert ytmusic_match._score(track, studio) > ytmusic_match._score(track, live)


def test_remaster_word_does_not_weaken_unrequested_live_penalty():
	track = {"title": "War Pigs - 2009 Remaster", "artists": "Black Sabbath"}
	studio = {"title": "War Pigs / Luke's Wall", "author": "Black Sabbath", "album": {"name": "Paranoid"}}
	live = {"title": "War Pigs (2023 Remaster)", "author": "Black Sabbath", "album": {"name": "Live Evil"}}
	assert ytmusic_match._score(track, studio) > ytmusic_match._score(track, live)


def test_search_preserves_album_metadata_for_scoring_and_display():
	yt = FakeYTMusic({
		"songs": [{"videoId": "live", "title": "War Pigs (2023 Remaster)", "artists": [{"name": "Black Sabbath"}], "album": {"name": "Live Evil"}, "duration": "9:19"}],
	})
	result = ytmusic_match._search_filter(yt, "War Pigs", "songs", 10)[0]
	assert result["album"] == {"name": "Live Evil"}


def test_requested_extended_version_beats_single_versions():
	track = {"title": "Hocus Pocus - Extended Version", "artists": "Focus", "duration_ms": 420000}
	extended = {"title": "Hocus Pocus (Extended Version)", "author": "Focus", "duration_seconds": 420}
	single = {"title": "Hocus Pocus (U.S. Single Version)", "author": "Focus", "duration_seconds": 420}
	original_single = {"title": "Hocus Pocus (Original Single Version)", "author": "Focus", "duration_seconds": 420}
	assert ytmusic_match._score(track, extended) > ytmusic_match._score(track, single)
	assert ytmusic_match._score(track, extended) > ytmusic_match._score(track, original_single)


def test_requested_single_version_does_not_choose_extended_version():
	track = {"title": "Hocus Pocus - U.S. Single Version", "artists": "Focus", "duration_ms": 240000}
	single = {"title": "Hocus Pocus (U.S. Single Version)", "author": "Focus", "duration_seconds": 240}
	extended = {"title": "Hocus Pocus (Extended Version)", "author": "Focus", "duration_seconds": 240}
	assert ytmusic_match._score(track, single) > ytmusic_match._score(track, extended)


def test_translated_catalog_title_uses_exact_duration_as_confidence_evidence():
	track = {"title": "上を向いて歩こう", "artists": "坂本九", "duration_ms": 185000}
	candidate = {
		"title": "Sukiyaki", "author": "Kyu Sakamoto", "duration_seconds": 185,
		"source": "music",
	}

	assert ytmusic_match._score(track, candidate) >= ytmusic_match.CONFIDENCE_MIN


def test_translated_title_floor_rejects_duration_mismatch():
	track = {"title": "上を向いて歩こう", "artists": "坂本九", "duration_ms": 185000}
	candidate = {
		"title": "Unrelated Song", "author": "Other Artist", "duration_seconds": 210,
		"source": "music",
	}

	assert ytmusic_match._score(track, candidate) < ytmusic_match.CONFIDENCE_MIN


def test_strip_noise_removes_feat_credit_only_as_whole_word():
	assert ytmusic_match._strip_noise("Song (feat. Guest)") == "Song"
	assert ytmusic_match._strip_noise("Song [ft. Guest]") == "Song"
	assert ytmusic_match._strip_noise("Song (Radio Edit; featuring Guest)") == "Song"
	assert ytmusic_match._strip_noise("Undefeated (Defeated)") == "Undefeated Defeated"
	assert ytmusic_match._strip_noise("Bird (Feather Song)") == "Bird Feather Song"


def test_split_title_removes_spotify_dash_suffixes():
	cases = {
		"Country House - 2012 Remaster": ("Country House", {"remaster"}),
		"Wonderwall - Remastered 2014": ("Wonderwall", {"remaster"}),
		"Song - Radio Edit": ("Song", {"edit"}),
		"Song - Live at Leeds": ("Song", {"live"}),
		"Song - Mono": ("Song", set()),
		"Song - 2009 Mix": ("Song", set()),
		"Song - From \"Some Film\"": ("Song", set()),
		"Song (2012 Remaster)": ("Song", {"remaster"}),
	}
	for title, (core, markers) in cases.items():
		got_core, got_markers, guests = ytmusic_match.split_title(title)
		assert got_core == core, title
		assert markers <= got_markers, title
		assert guests == []


def test_split_title_keeps_meaningful_title_parts():
	assert ytmusic_match.split_title("(Don't Fear) The Reaper")[0] == "(Don't Fear) The Reaper"
	assert ytmusic_match.split_title("Love - Hate")[0] == "Love - Hate"
	assert ytmusic_match.split_title("Undefeated (Defeated)")[0] == "Undefeated (Defeated)"


def test_split_title_moves_feat_and_with_guests_to_artists():
	core, _markers, guests = ytmusic_match.split_title("Song (feat. Guest One & Guest Two)")
	assert core == "Song"
	assert guests == ["Guest One", "Guest Two"]
	core, _markers, guests = ytmusic_match.split_title("Other Song (with Guest)")
	assert core == "Other Song"
	assert guests == ["Guest"]


def test_blur_country_house_remaster_scores_above_point_eight():
	# Real skipped track: Spotify title with " - 2012 Remaster", no duration.
	track = {"title": "Country House - 2012 Remaster", "artists": "Blur", "duration_ms": 0}
	candidate = {"title": "Country House", "artists": [{"name": "Blur"}], "author": "Blur", "duration_seconds": 241, "source": "music"}
	assert ytmusic_match._score(track, candidate) > 0.8


def test_feat_guest_in_title_does_not_lower_title_score():
	track = {"title": "Song (feat. Guest)", "artists": "Artist", "duration_ms": 200000}
	candidate = {"title": "Song", "artists": [{"name": "Artist"}, {"name": "Guest"}], "duration_seconds": 200, "source": "music"}
	assert ytmusic_match._score(track, candidate) >= 0.9


def test_query_variants_search_title_core_first():
	track = {"title": "Country House - 2012 Remaster", "artists": "Blur"}
	variants = ytmusic_match._query_variants(track)
	assert variants[0] == "Country House Blur"
	track = {"title": "Song (feat. Guest)", "artists": "Artist, Guest", "isrc": "GBAYE9500001"}
	assert ytmusic_match._query_variants(track)[0] == "GBAYE9500001 Song Artist, Guest"


def test_penalty_terms_match_whole_words_only():
	cases = [
		("Demons", "Imagine Dragons"),
		("Discover", "Artist"),
		("Undercover Martyn", "Two Door Cinema Club"),
		("Reverberation", "The 13th Floor Elevators"),
	]
	for title, artist in cases:
		track = {"title": title, "artists": artist, "duration_ms": 200000}
		candidate = {"title": title, "artists": [{"name": artist}], "duration_seconds": 200, "source": "music"}
		assert ytmusic_match._score(track, candidate) >= 0.95, title
	cover = {"title": "Demons (Cover)", "artists": [{"name": "Imagine Dragons"}], "duration_seconds": 200}
	exact = {"title": "Demons", "artists": [{"name": "Imagine Dragons"}], "duration_seconds": 200}
	track = {"title": "Demons", "artists": "Imagine Dragons", "duration_ms": 200000}
	assert ytmusic_match._score(track, exact) - ytmusic_match._score(track, cover) >= 0.09


def test_cast_penalty_ignores_castle_and_broadcast():
	track = {"title": "Castle on the Hill", "artists": "Ed Sheeran", "duration_ms": 261000}
	# A video upload whose channel does not match the artist name.
	candidate = {"title": "Castle on the Hill", "author": "Lyrics Channel", "duration_seconds": 261, "source": "videos"}
	cast = {"title": "Castle on the Hill (Original Cast)", "author": "Lyrics Channel", "duration_seconds": 261, "source": "videos"}
	assert ytmusic_match._score(track, candidate) - ytmusic_match._score(track, cast) >= 0.3
	assert ytmusic_match._has_term("castle on the hill", "cast") is False
	assert ytmusic_match._has_term("broadcast news", "cast") is False
	assert ytmusic_match._has_term("song original  cast", "original cast") is True
