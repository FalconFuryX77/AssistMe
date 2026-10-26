"""Phase 19 — Internet Connectivity Tests.

Validates that the application is properly configured for internet deployment:
  • CORS middleware is active and returns correct headers
  • ICE servers endpoint returns public URLs (not Docker-internal hostnames)
  • TURN server config includes external-ip directive
  • Nginx config includes SSL/TLS server block
  • ALLOWED_ORIGINS configuration parsing works correctly
  • WebSocket upgrade is proxied through Nginx config
"""

import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEPLOY_DIR = BACKEND_DIR.parent / "deploy"


async def _empty_turn_credentials() -> None:
    return None


@pytest.fixture
def app():
    """Import a fresh FastAPI app instance."""
    # Reset the settings module to pick up patched env vars
    import importlib
    import core.config
    importlib.reload(core.config)
    import app as app_module
    importlib.reload(app_module)
    return app_module.app


@pytest.fixture
def transport(app):
    return ASGITransport(app=app)


# ---------------------------------------------------------------------------
# 1. CORS Middleware Tests
# ---------------------------------------------------------------------------

class TestCORSMiddleware:
    """Verify CORSMiddleware is attached and responds correctly."""

    @pytest.mark.anyio
    async def test_cors_headers_on_response(self, transport):
        """Any response should include Access-Control-Allow-Origin."""
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get("/health", headers={"Origin": "https://example.com"})
        assert resp.status_code == 200
        # With ALLOWED_ORIGINS defaulting to "*", the header should be present
        assert "access-control-allow-origin" in resp.headers

    @pytest.mark.anyio
    async def test_cors_preflight_options(self, transport):
        """OPTIONS preflight must return CORS allow headers."""
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.options(
                "/health",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Authorization",
                },
            )
        assert resp.status_code == 200
        assert "access-control-allow-methods" in resp.headers
        assert "access-control-allow-headers" in resp.headers

    @pytest.mark.anyio
    async def test_cors_allows_credentials(self, transport):
        """Credentials flag must be set for cookie/token auth."""
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get("/health", headers={"Origin": "https://example.com"})
        assert resp.headers.get("access-control-allow-credentials") == "true"


# ---------------------------------------------------------------------------
# 2. ALLOWED_ORIGINS Config Parsing Tests
# ---------------------------------------------------------------------------

class TestAllowedOriginsConfig:
    """Validate ALLOWED_ORIGINS env var parsing."""

    def test_default_allows_wildcard(self):
        """Without env var, ALLOWED_ORIGINS should default to ['*']."""
        import importlib
        import core.config
        try:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("ALLOWED_ORIGINS", None)
                importlib.reload(core.config)
                assert "*" in core.config.settings.ALLOWED_ORIGINS
        finally:
            importlib.reload(core.config)

    def test_comma_separated_parsing(self):
        """Multiple origins should be parsed from comma-separated string."""
        import importlib
        import core.config
        try:
            with patch.dict(os.environ, {"ALLOWED_ORIGINS": "https://a.com,https://b.com"}, clear=False):
                importlib.reload(core.config)
                assert core.config.settings.ALLOWED_ORIGINS == ["https://a.com", "https://b.com"]
        finally:
            importlib.reload(core.config)

    def test_whitespace_trimmed(self):
        """Whitespace around origins must be trimmed."""
        import importlib
        import core.config
        try:
            with patch.dict(os.environ, {"ALLOWED_ORIGINS": " https://a.com , https://b.com "}, clear=False):
                importlib.reload(core.config)
                assert core.config.settings.ALLOWED_ORIGINS == ["https://a.com", "https://b.com"]
        finally:
            importlib.reload(core.config)


# ---------------------------------------------------------------------------
# 3. ICE Servers — Public URLs Test
# ---------------------------------------------------------------------------

class TestICEServersPublicURLs:
    """ICE servers endpoint must return public (not Docker-internal) URLs."""

    @pytest.mark.asyncio
    async def test_ice_servers_use_public_turn_url(self):
        """When PUBLIC_TURN_URL is set, it must appear in the ICE response."""
        import importlib
        import core.config
        import api.services.webrtc_service

        public_turns = [
            "turn:my-public-server.example.com:3478?transport=udp",
            "turns:my-public-server.example.com:443?transport=tcp",
        ]
        env_patch = {
            "PUBLIC_TURN_URL": ",".join(public_turns),
            "PUBLIC_STUN_URLS": "stun:my-public-server.example.com:3478",
            "TURN_SERVER_USERNAME": "user",
            "TURN_SERVER_CREDENTIAL": "pass",
        }
        try:
            with patch.dict(os.environ, env_patch, clear=False):
                importlib.reload(core.config)
                importlib.reload(api.services.webrtc_service)
                from api.services.webrtc_service import WebRTCService
                with patch.object(
                    WebRTCService,
                    "_fetch_metered",
                    staticmethod(_empty_turn_credentials),
                ):
                    response = await WebRTCService.get_ice_servers()

                turn_urls = []
                for server in response.ice_servers:
                    urls = server.urls if isinstance(server.urls, list) else [server.urls]
                    turn_urls.extend(urls)
                assert all(url in turn_urls for url in public_turns), (
                    f"Expected TURN fallback URLs were not found in ICE servers: {turn_urls}"
                )
        finally:
            # Restore defaults so subsequent tests are not polluted
            importlib.reload(core.config)
            importlib.reload(api.services.webrtc_service)

    @pytest.mark.asyncio
    async def test_ice_servers_no_docker_hostnames(self):
        """Docker-internal hostnames like 'coturn' must NOT appear in client responses."""
        import importlib
        import core.config
        import api.services.webrtc_service

        env_patch = {
            "PUBLIC_TURN_URL": "turn:public.example.com:3478",
            "PUBLIC_STUN_URLS": "stun:public.example.com:3478",
            "TURN_SERVER_USERNAME": "user",
            "TURN_SERVER_CREDENTIAL": "pass",
        }
        try:
            with patch.dict(os.environ, env_patch, clear=False):
                importlib.reload(core.config)
                importlib.reload(api.services.webrtc_service)
                from api.services.webrtc_service import WebRTCService
                with patch.object(
                    WebRTCService,
                    "_fetch_metered",
                    staticmethod(_empty_turn_credentials),
                ):
                    response = await WebRTCService.get_ice_servers()

                for server in response.ice_servers:
                    urls = server.urls if isinstance(server.urls, list) else [server.urls]
                    for url in urls:
                        assert "coturn" not in url, (
                            f"Docker-internal hostname 'coturn' found in ICE URL: {url}"
                        )
        finally:
            importlib.reload(core.config)
            importlib.reload(api.services.webrtc_service)


# ---------------------------------------------------------------------------
# 4. Coturn Config — external-ip Directive
# ---------------------------------------------------------------------------

class TestCoturnConfig:
    """Validate turnserver.conf has required internet deployment directives."""

    @pytest.fixture
    def turnserver_conf(self):
        conf_path = DEPLOY_DIR / "coturn" / "turnserver.conf"
        assert conf_path.exists(), f"turnserver.conf not found at {conf_path}"
        return conf_path.read_text(encoding="utf-8")

    def test_external_ip_present(self, turnserver_conf):
        """external-ip directive must be present for NAT traversal."""
        assert "external-ip=" in turnserver_conf

    def test_relay_ip_present(self, turnserver_conf):
        """relay-ip should bind to all interfaces."""
        assert "relay-ip=0.0.0.0" in turnserver_conf

    def test_denied_peer_ip_private_ranges(self, turnserver_conf):
        """Private IP ranges should be denied to prevent relay abuse."""
        assert "denied-peer-ip=10.0.0.0-10.255.255.255" in turnserver_conf
        assert "denied-peer-ip=192.168.0.0-192.168.255.255" in turnserver_conf


# ---------------------------------------------------------------------------
# 5. Nginx Config — SSL/TLS Block
# ---------------------------------------------------------------------------

class TestNginxSSLConfig:
    """Validate Nginx configuration has proper HTTPS/TLS setup."""

    @pytest.fixture
    def nginx_conf(self):
        conf_path = DEPLOY_DIR / "nginx" / "conf.d" / "assistme.conf"
        assert conf_path.exists(), f"assistme.conf not found at {conf_path}"
        return conf_path.read_text(encoding="utf-8")

    def test_ssl_listen_directive(self, nginx_conf):
        """Nginx must listen on 443 with SSL."""
        assert re.search(r"listen\s+443\s+ssl", nginx_conf), (
            "Missing 'listen 443 ssl' directive in Nginx config"
        )

    def test_ssl_certificate_paths(self, nginx_conf):
        """ssl_certificate and ssl_certificate_key must be configured."""
        assert "ssl_certificate " in nginx_conf
        assert "ssl_certificate_key " in nginx_conf

    def test_http_to_https_redirect(self, nginx_conf):
        """Port 80 block must redirect to HTTPS."""
        assert "return 301 https://" in nginx_conf

    def test_tls_protocols(self, nginx_conf):
        """Only TLS 1.2 and 1.3 should be allowed."""
        assert "TLSv1.2" in nginx_conf
        assert "TLSv1.3" in nginx_conf

    def test_hsts_header(self, nginx_conf):
        """Strict-Transport-Security header must be set."""
        assert "Strict-Transport-Security" in nginx_conf

    def test_websocket_upgrade_in_ssl_block(self, nginx_conf):
        """WebSocket upgrade headers must be in the HTTPS block."""
        # The 443 block should contain proxy_set_header Upgrade
        ssl_block = nginx_conf[nginx_conf.index("listen 443"):]
        assert "Upgrade" in ssl_block
        assert "upgrade" in ssl_block


# ---------------------------------------------------------------------------
# 6. Docker Compose — Public Env Vars
# ---------------------------------------------------------------------------

class TestDockerComposeConfig:
    """Validate docker-compose.yml has public-facing env vars."""

    @pytest.fixture
    def compose_content(self):
        compose_path = DEPLOY_DIR / "docker-compose.yml"
        assert compose_path.exists(), f"docker-compose.yml not found at {compose_path}"
        return compose_path.read_text(encoding="utf-8")

    def test_public_turn_url_in_compose(self, compose_content):
        """PUBLIC_TURN_URL must be passed to backend."""
        assert "PUBLIC_TURN_URL" in compose_content

    def test_public_stun_urls_in_compose(self, compose_content):
        """PUBLIC_STUN_URLS must be passed to backend."""
        assert "PUBLIC_STUN_URLS" in compose_content

    def test_allowed_origins_in_compose(self, compose_content):
        """ALLOWED_ORIGINS must be passed to backend."""
        assert "ALLOWED_ORIGINS" in compose_content

    def test_external_ip_in_coturn(self, compose_content):
        """EXTERNAL_IP must be passed to coturn container."""
        assert "EXTERNAL_IP" in compose_content

    def test_certs_volume_mounted(self, compose_content):
        """Certs volume must be mounted to nginx."""
        assert "certs" in compose_content


# ---------------------------------------------------------------------------
# 7. Self-Signed Dev Certificate Exists
# ---------------------------------------------------------------------------

class TestDevCertificatePresent:
    """Verify that development TLS certificates are generated."""

    def test_fullchain_exists(self):
        cert_path = DEPLOY_DIR / "nginx" / "certs" / "fullchain.pem"
        assert cert_path.exists(), f"Dev certificate not found at {cert_path}"

    def test_privkey_exists(self):
        key_path = DEPLOY_DIR / "nginx" / "certs" / "privkey.pem"
        assert key_path.exists(), f"Dev private key not found at {key_path}"
