"""WebRTC signaling and ICE configuration business logic."""

import asyncio
import time

import httpx
from core.config import settings
from api.schemas.webrtc import ICEServerEntry, ICEServersResponse

_metered_cache: list | None = None
_metered_cache_expiry: float = 0.0
_metered_fetch_lock = asyncio.Lock()


class WebRTCService:
    """Manages WebRTC signaling configuration and helper methods."""

    @staticmethod
    async def _fetch_metered() -> list | None:
        """Fetch short-lived TURN creds from Metered REST API (cached)."""
        global _metered_cache, _metered_cache_expiry
        if not settings.METERED_API_KEY:
            return None
        if _metered_cache is not None and time.time() < _metered_cache_expiry:
            return _metered_cache
        async with _metered_fetch_lock:
            if _metered_cache is not None and time.time() < _metered_cache_expiry:
                return _metered_cache
            try:
                domain = settings.METERED_DOMAIN or "assistme.metered.live"
                url = f"https://{domain}/api/v1/turn/credentials"
                timeout = httpx.Timeout(4.0, connect=1.5)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(
                        url,
                        params={"apiKey": settings.METERED_API_KEY},
                    )
                response.raise_for_status()
                data = response.json()
                if isinstance(data, list) and data:
                    _metered_cache = data
                    _metered_cache_expiry = time.time() + 600  # 10 min
                    return data
            except Exception:
                return _metered_cache  # stale cache is better than no relay
            return None

    @staticmethod
    async def get_ice_servers() -> ICEServersResponse:
        """Construct RTCIceServer configuration for WebRTC clients.

        Priority: Metered dynamic creds → static TURN env → STUN-only.
        """
        metered = await WebRTCService._fetch_metered()
        if metered is not None:
            google_stun = ICEServerEntry(urls=[
                "stun:stun.l.google.com:19302",
                "stun:stun1.l.google.com:19302",
                "stun:stun2.l.google.com:19302",
            ])
            servers = [google_stun]
            for entry in metered:
                servers.append(ICEServerEntry(**entry))
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

        # A comma-separated URL list permits a UDP path plus a TLS/TCP 443
        # fallback for restrictive campus and enterprise networks.
        if settings.PUBLIC_TURN_URL and settings.PUBLIC_TURN_URL.strip():
            turn_urls = [
                url.strip()
                for url in settings.PUBLIC_TURN_URL.split(",")
                if url.strip()
            ]
            turn_entry = ICEServerEntry(
                urls=turn_urls if len(turn_urls) > 1 else turn_urls[0],
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
