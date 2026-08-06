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
        servers = [
            ICEServerEntry(urls=settings.STUN_SERVERS)
        ]

        if settings.TURN_SERVER_URL:
            turn_entry = ICEServerEntry(
                urls=settings.TURN_SERVER_URL,
                username=settings.TURN_SERVER_USERNAME,
                credential=settings.TURN_SERVER_CREDENTIAL,
            )
            servers.append(turn_entry)

        return ICEServersResponse(ice_servers=servers)
