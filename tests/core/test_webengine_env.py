# tabs only
import os

from csvmusic.core.webengine_env import BACKGROUND_FLAGS, configure_webengine_background_flags


def test_background_flags_are_added_and_existing_flags_kept():
	environment = {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu"}

	configure_webengine_background_flags(environment)
	configure_webengine_background_flags(environment)

	flags = environment["QTWEBENGINE_CHROMIUM_FLAGS"].split()
	assert flags[0] == "--disable-gpu"
	for flag in BACKGROUND_FLAGS:
		assert flags.count(flag) == 1
	assert "--disable-backgrounding-occluded-windows" in flags


def test_background_flags_are_set_without_previous_value():
	environment: dict[str, str] = {}

	configure_webengine_background_flags(environment)

	assert environment["QTWEBENGINE_CHROMIUM_FLAGS"].split() == list(BACKGROUND_FLAGS)


def test_importing_the_spotify_reader_sets_the_flags():
	import csvmusic.ui.spotify_public_scrape  # noqa: F401

	flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").split()
	for flag in BACKGROUND_FLAGS:
		assert flag in flags
