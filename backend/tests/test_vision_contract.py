"""Small, stable checks for the product surface described by VISION.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app  # noqa: E402


def _paths() -> set[str]:
    return {route.path for route in app.routes}


def test_device_first_help_surface_is_exposed() -> None:
    paths = _paths()
    assert "/auth/device" in paths
    assert "/auth/device/reclaim" in paths
    assert "/help/call" in paths
    assert "/help/pending" in paths
    assert "/devices/pairing/setup-code" in paths
    assert "/devices/pairing/claim" in paths
    assert "/devices/pairing/approve" in paths


def test_legacy_product_surfaces_are_not_exposed() -> None:
    paths = _paths()
    assert "/auth/login" not in paths
    assert "/auth/register" not in paths
    assert not any("chat" in path or "files" in path for path in paths)
    assert not any("participants/invite" in path for path in paths)
    assert not any("zeroize" in path or "policy" in path or "context" in path for path in paths)


def test_live_session_has_screen_voice_and_control_channels() -> None:
    paths = _paths()
    assert "/sessions/{session_id}/ice-servers" in paths
    assert "/sessions/{session_id}/audio/mute" in paths
    assert "/sessions/{session_id}/remote-control/input" in paths
