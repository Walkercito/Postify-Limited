from typing import Final

DEFAULT_GRAPH_BASE: Final[str] = "https://graph.facebook.com"
DEFAULT_REST_BASE: Final[str] = "https://b-api.facebook.com"

ANDROID_API_KEY: Final[str] = "882a8490361da98702bf97a021ddc14d"
ANDROID_API_SECRET: Final[str] = "62f8ce9f74b12f84c123cc23437a4a32"

DEFAULT_TIMEOUT_SEC: Final[float] = 30.0

FB_WEB_BASE: Final[str] = "https://www.facebook.com"
FB_GROUPS_PATH: Final[str] = "groups"

# Browser User-Agent for the unauthenticated public-preview scrape. A mobile
# Safari string yields the Open Graph-tagged page without an app-style payload.
GROUP_PREVIEW_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
