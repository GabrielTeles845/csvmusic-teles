from csvmusic.core.manual_match import choice_warnings, describe_video, fetch_video_info, video_info_from_song


def _song(video_id="uLivzCQcQW8", title="Country House", author="Blur", seconds=237, kind="MUSIC_VIDEO_TYPE_ATV", status="OK", reason=None):
	playability = {"status": status}
	if reason:
		playability["reason"] = reason
	return {
		"videoDetails": {"videoId": video_id, "title": title, "author": author, "lengthSeconds": str(seconds), "musicVideoType": kind},
		"playabilityStatus": playability,
	}


TRACK = {"title": "Country House - 2012 Remaster", "artists": "Blur", "duration_ms": 237_500, "duration_precision_s": 1}


def test_song_with_same_length_has_no_warning():
	info = video_info_from_song(_song())
	assert info["kind"] == "song"
	assert choice_warnings(TRACK, info) == []
	assert describe_video(info) == "Country House — Blur · 3:57 · YouTube Music song"


def test_music_video_is_flagged_even_with_close_length():
	info = video_info_from_song(_song(kind="MUSIC_VIDEO_TYPE_OMV", seconds=232))
	warnings = choice_warnings(TRACK, info)
	assert len(warnings) == 1
	assert "music video" in warnings[0]


def test_much_longer_video_warns_with_the_difference():
	info = video_info_from_song(_song(kind="MUSIC_VIDEO_TYPE_UGC", seconds=272))
	warnings = choice_warnings(TRACK, info)
	assert any("34 s longer than the song (3:58)" in w for w in warnings)


def test_shorter_video_says_shorter():
	info = video_info_from_song(_song(seconds=200))
	assert any("s shorter" in w for w in choice_warnings(TRACK, info))


def test_unknown_song_length_skips_length_check():
	info = video_info_from_song(_song(seconds=600))
	assert choice_warnings({"title": "Country House", "artists": "Blur"}, info) == []


def test_other_song_title_is_flagged():
	info = video_info_from_song(_song(title="Parklife"))
	assert any("does not mention \"Country House\"" in w for w in choice_warnings(TRACK, info))


def test_accents_do_not_count_as_another_title():
	track = {"title": "Coração Selvagem", "artists": "Belchior"}
	info = video_info_from_song(_song(title="Coracao Selvagem (Ao Vivo)"))
	assert choice_warnings(track, info) == []


def test_age_restricted_video_says_it_needs_the_account():
	info = video_info_from_song(_song(status="LOGIN_REQUIRED", reason="Sign in to confirm your age"))
	assert info["age_restricted"] is True
	assert any("Age-restricted" in w for w in choice_warnings(TRACK, info))


def test_unavailable_video_shows_youtube_reason():
	info = video_info_from_song(_song(status="UNPLAYABLE", reason="Video unavailable"))
	assert any(w == "Not playable: Video unavailable" for w in choice_warnings(TRACK, info))


def test_fetch_uses_given_client_without_network():
	class FakeYT:
		def get_song(self, video_id):
			return _song(video_id=video_id)

	assert fetch_video_info("uLivzCQcQW8", yt=FakeYT())["videoId"] == "uLivzCQcQW8"


def test_missing_details_keep_the_requested_id():
	info = video_info_from_song({}, "abcdefghijk")
	assert info["videoId"] == "abcdefghijk"
	assert describe_video(info) == "abcdefghijk · YouTube video"
