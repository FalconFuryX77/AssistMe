"""WebRTC signaling and ICE configuration business logic."""

from core.config import settings
from api.schemas.webrtc import ICEServerEntry, ICEServersResponse


class WebRTCService:
    """Manages WebRTC signaling configuration and helper methods."""

    @staticmethod
    def get_ice_servers() -> ICEServersResponse:
        """Construct RTCIceServer configuration for WebRTC clients.

        Includes configured STUN servers and optional TURN server.
        """
        # Use public-facing STUN URLs if configured, otherwise fallback to internal list
        stun_urls = settings.PUBLIC_STUN_URLS if settings.PUBLIC_STUN_URLS else settings.STUN_SERVERS
        servers = [ICEServerEntry(urls=stun_urls)]

        # Use public TURN URL if configured, otherwise fall back to internal TURN
        if settings.PUBLIC_TURN_URL:
            turn_entry = ICEServerEntry(
                urls=settings.PUBLIC_TURN_URL,
                username=settings.TURN_SERVER_USERNAME,
                credential=settings.TURN_SERVER_CREDENTIAL,
            )
            servers.append(turn_entry)
        elif settings.TURN_SERVER_URL:
            turn_entry = ICEServerEntry(
                urls=settings.TURN_SERVER_URL,
                username=settings.TURN_SERVER_USERNAME,
                credential=settings.TURN_SERVER_CREDENTIAL,
            )
            servers.append(turn_entry)

        return ICEServersResponse(ice_servers=servers)
