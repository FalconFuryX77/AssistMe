"""WebRTC signaling and ICE configuration business logic."""

import time
from core.config import settings
from api.schemas.webrtc import ICEServerEntry, ICEServersResponse

_metered_cache: list | None = None
_metered_cache_expiry: float = 0.0


class WebRTCService:
    """Manages WebRTC signaling configuration and helper methods."""

    @staticmethod
    def _fetch_metered() -> list | None:
        """Fetch short-lived TURN creds from Metered REST API (cached)."""
        global _metered_cache, _metered_cache_expiry
        if not settings.METERED_API_KEY:
            return None
        if _metered_cache is not None and time.time() < _metered_cache_expiry:
            return _metered_cache
        try:
            import urllib.request, json  # stdlib, no extra deps
            domain = settings.METERED_DOMAIN or "assistme.metered.live"
            url = f"https://{domain}/api/v1/turn/credentials?apiKey={settings.METERED_API_KEY}"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if isinstance(data, list) and data:
                    _metered_cache = data
                    _metered_cache_expiry = time.time() + 600  # 10 min
                    return data
        except Exception:
            return _metered_cache  # stale cache better than nothing
        return None

    @staticmethod
    def get_ice_servers() -> ICEServersResponse:
        """Construct RTCIceServer configuration for WebRTC clients.

        Priority: Metered dynamic creds → static TURN env → STUN-only.
        """
        metered = WebRTCService._fetch_metered()
        if metered is not None:
            servers = [ICEServerEntry(**entry) for entry in metered]
            return ICEServersResponse(ice_servers=servers)

        # Use public-facing STUN URLs if configured, otherwise fallback to internal list
        raw_stun = settings.PUBLIC_STUN_URLS if settings.PUBLIC_STUN_URLS else settings.STUN_SERVERS
        # Filter out internal Docker-only service hostnames like "coturn" which cause DNS timeouts on real devices
        clean_stun = [u for u in raw_stun if "coturn" not in u.lower()]
        if not clean_stun:
            clean_stun = [
                "stun:stun.l.google.com:19302",
                "stun:stun1.l.google.com:19302",
                "stun:stun2.l.google.com:19302",
            ]
        servers = [ICEServerEntry(urls=clean_stun)]

        # Use public TURN URL if configured, otherwise fall back to internal TURN if resolvable
        if settings.PUBLIC_TURN_URL:
            turn_entry = ICEServerEntry(
                urls=settings.PUBLIC_TURN_URL,
                username=settings.TURN_SERVER_USERNAME,
                credential=settings.TURN_SERVER_CREDENTIAL,
            )
            servers.append(turn_entry)
        elif settings.TURN_SERVER_URL and "coturn" not in settings.TURN_SERVER_URL.lower():
            turn_entry = ICEServerEntry(
                urls=settings.TURN_SERVER_URL,
                username=settings.TURN_SERVER_USERNAME,
                credential=settings.TURN_SERVER_CREDENTIAL,
            )
            servers.append(turn_entry)

        return ICEServersResponse(ice_servers=servers)
