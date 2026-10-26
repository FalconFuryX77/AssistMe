"""Comprehensive test suite for Phase 18 Production Infrastructure & Deployment.

Covers: Dockerfile multi-stage build structure, docker-compose orchestration networks,
Coturn STUN/TURN configuration contracts, Nginx WebSockets reverse proxy headers, and K8s manifests.
"""

from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_dockerfile_multi_stage_structure() -> None:
    """Verify Dockerfile contains builder stage, unprivileged runner user, and health check."""
    dockerfile_path = REPO_ROOT / "backend" / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist in backend/"

    content = dockerfile_path.read_text(encoding="utf-8")
    assert "AS builder" in content
    assert "AS runner" in content
    assert "useradd" in content
    assert "USER assistme" in content
    assert "HEALTHCHECK" in content
    assert "uvicorn" in content


def test_runtime_service_account_is_excluded_from_image_build() -> None:
    """Credential JSON must only enter the container through its runtime mount."""
    dockerignore = (REPO_ROOT / "backend" / ".dockerignore").read_text(
        encoding="utf-8"
    )
    compose = (REPO_ROOT / "deploy" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    notification_code = (
        REPO_ROOT / "backend" / "api" / "routers" / "help_flow.py"
    ).read_text(encoding="utf-8")

    assert "firebase-service-account*.json" in dockerignore
    assert "FIREBASE_SERVICE_ACCOUNT=/run/secrets/firebase-service-account.json" in compose
    assert "../backend/firebase-service-account.json:/run/secrets/firebase-service-account.json:ro" in compose
    assert 'os.getenv("FIREBASE_SERVICE_ACCOUNT")' in notification_code
    assert 'os.path.isfile(creds_path)' in notification_code
    assert '"backend/firebase-service-account.json"' not in notification_code


def test_docker_compose_service_orchestration() -> None:
    """Verify docker-compose.yml defines backend, PostgreSQL, Coturn, and Nginx with healthchecks."""
    compose_path = REPO_ROOT / "deploy" / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist in deploy/"

    content = compose_path.read_text(encoding="utf-8")
    assert "backend:" in content
    assert "db:" in content
    assert "coturn:" in content
    assert "nginx:" in content
    assert "healthcheck:" in content
    assert "3478:3478" in content
    assert "assistme_net" in content


def test_production_compose_requires_secrets_and_keeps_api_private() -> None:
    """Production Compose must not ship dev credentials or publish the API port."""
    content = (REPO_ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    backend_service = content.split("  # --- PostgreSQL", maxsplit=1)[0]

    assert "SECRET_KEY=${SECRET_KEY:?" in backend_service
    assert "ALLOWED_ORIGINS=${ALLOWED_ORIGINS:?" in backend_service
    assert "TURN_SERVER_CREDENTIAL=${TURN_CREDENTIAL:?" in backend_service
    assert "dev-secret-key-change-in-production" not in content
    assert '"8000:8000"' not in backend_service

    local_override = (REPO_ROOT / "deploy" / "docker-compose.local.yml").read_text(encoding="utf-8")
    assert '"${BACKEND_BIND_PORT:-8000}:8000"' in local_override


def test_coturn_configuration_syntax() -> None:
    """Verify Coturn turnserver.conf contains listening ports, realm, and credential mechanisms."""
    coturn_path = REPO_ROOT / "deploy" / "coturn" / "turnserver.conf"
    assert coturn_path.exists(), "turnserver.conf must exist in deploy/coturn/"

    content = coturn_path.read_text(encoding="utf-8")
    assert "listening-port=3478" in content
    assert "tls-listening-port=5349" in content
    assert "lt-cred-mech" in content
    assert "user=${TURN_USERNAME}:${TURN_CREDENTIAL}" in content
    assert "realm=assistme.net" in content
    assert "min-port=" in content
    assert "max-port=" in content


def test_nginx_websockets_reverse_proxy_configuration() -> None:
    """Verify Nginx configuration includes Upgrade headers and extended proxy timeouts."""
    nginx_conf = REPO_ROOT / "deploy" / "nginx" / "conf.d" / "assistme.conf"
    assert nginx_conf.exists(), "assistme.conf must exist in deploy/nginx/conf.d/"

    content = nginx_conf.read_text(encoding="utf-8")
    assert "proxy_set_header Upgrade $http_upgrade;" in content
    # Accept both hardcoded "upgrade" and map-variable $connection_upgrade
    assert (
        'proxy_set_header Connection "upgrade";' in content
        or "proxy_set_header Connection $connection_upgrade;" in content
    ), "WebSocket Connection upgrade header not found in Nginx config"
    assert "location /ws/" in content
    assert "proxy_read_timeout" in content


def test_kubernetes_manifests_structure() -> None:
    """Verify Kubernetes manifests define backend, Coturn, and Ingress routing."""
    k8s_dir = REPO_ROOT / "deploy" / "k8s"
    assert (k8s_dir / "configmap.yaml").exists()
    assert (k8s_dir / "backend-deployment.yaml").exists()
    assert (k8s_dir / "coturn-deployment.yaml").exists()
    assert (k8s_dir / "ingress.yaml").exists()

    backend_yaml = (k8s_dir / "backend-deployment.yaml").read_text(encoding="utf-8")
    assert "livenessProbe" in backend_yaml
    assert "readinessProbe" in backend_yaml
    assert "resources:" in backend_yaml
