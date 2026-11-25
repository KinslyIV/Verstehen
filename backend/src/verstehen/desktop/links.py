import re
from typing import Literal

ALLOWED_EXTERNAL_URL = re.compile(
    r"https://auth\.openai\.com/.*|https://code\.claude\.com/docs/en/setup"
)
BLANK_PAGES = ("about:blank", "about:srcdoc")

Navigation = Literal["load", "open-externally", "block"]


def navigation_for(url: str, origin: str | None, *, is_main_frame: bool) -> Navigation:
    """Decide what the window does with a navigation: stay on the app, open a link, or refuse."""
    if not is_main_frame or url in BLANK_PAGES:
        return "load"
    if origin is not None and (url == origin or url.startswith(f"{origin}/")):
        return "load"
    if ALLOWED_EXTERNAL_URL.fullmatch(url):
        return "open-externally"
    return "block"
