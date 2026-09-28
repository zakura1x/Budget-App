"""
SEC-32. A coarse device label from a User-Agent: "Chrome on Android".

Only the label is ever stored - never the raw string, which carries version
numbers and build ids that make a browser easier to fingerprint and say
nothing the Security screen needs. Pure, and deliberately rough: an unknown
browser or system reads as "Browser" / "a device", never as a wrong guess.
"""

import re
from typing import Optional

LABEL_MAX = 60

# Order matters: Edge, Opera and Samsung Internet all say "Chrome" too, and
# Chrome says "Safari".
_BROWSERS = (
    (r"Edg(e|A|iOS)?/", "Edge"),
    (r"OPR/|Opera", "Opera"),
    (r"SamsungBrowser/", "Samsung Internet"),
    (r"Firefox/|FxiOS/", "Firefox"),
    (r"Chrome/|CriOS/", "Chrome"),
    (r"Safari/", "Safari"),
)

_SYSTEMS = (
    (r"iPhone", "iPhone"),
    (r"iPad", "iPad"),
    (r"Android", "Android"),
    (r"CrOS", "ChromeOS"),
    (r"Windows", "Windows"),
    (r"Macintosh|Mac OS X", "Mac"),
    (r"Linux", "Linux"),
)


def device_label(user_agent: Optional[str]) -> Optional[str]:
    """"Chrome on Android", or None when there is no User-Agent at all."""
    ua = (user_agent or "").strip()
    if not ua:
        return None
    browser = next((name for pattern, name in _BROWSERS if re.search(pattern, ua)), "Browser")
    system = next((name for pattern, name in _SYSTEMS if re.search(pattern, ua)), "a device")
    return f"{browser} on {system}"[:LABEL_MAX]
