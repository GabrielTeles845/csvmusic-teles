# tabs only
"""Chromium flags for the embedded browser (must be set before QtWebEngine starts)."""
import os
from typing import MutableMapping, Optional

# Without these, Chromium slows timers and rendering when the window is hidden or
# covered, and the Spotify reader stops seeing new rows (docs/fork/05 §4.3).
BACKGROUND_FLAGS = (
	"--disable-background-timer-throttling",
	"--disable-renderer-backgrounding",
	"--disable-backgrounding-occluded-windows",
)


def configure_webengine_background_flags(environment: Optional[MutableMapping[str, str]] = None) -> None:
	"""Add the anti-throttling flags to QTWEBENGINE_CHROMIUM_FLAGS on every platform, keeping existing ones."""
	env = environment if environment is not None else os.environ
	flags = str(env.get("QTWEBENGINE_CHROMIUM_FLAGS") or "").split()
	for flag in BACKGROUND_FLAGS:
		if flag not in flags:
			flags.append(flag)
	env["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flags)
