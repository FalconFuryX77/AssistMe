"""Small, stable checks for the product surface described by VISION.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import INTERNAL_PREFIX, app  # noqa: E402


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


def _consumer_paths() -> set[str]:
    """Routes that form the helpee- and helper-facing product surface.

    Framework endpoints under /internal are excluded: they implement ACSAF
    Phases 8 and 9, which the roadmap requires, and they are deliberately not
    part of the small product surface VISION.md commits to. See app.py for why
    the prefix exists.
    """
    return {path for path in _paths() if not path.startswith(INTERNAL_PREFIX)}


def test_legacy_product_surfaces_are_not_exposed() -> None:
    paths = _consumer_paths()
    assert "/auth/login" not in paths
    assert "/auth/register" not in paths
    assert not any("chat" in path or "files" in path for path in paths)
    assert not any("participants/invite" in path for path in paths)
    assert not any("zeroize" in path for path in paths)
    # No adaptive-policy or context machinery in the consumer surface: the
    # helpee never sees a risk dashboard, only plain-language consent screens.
    assert not any("policy" in path or "context" in path for path in paths)


def test_research_framework_is_reachable_but_separated() -> None:
    """ACSAF Phases 8 and 9 are mounted, and only under /internal.

    An unmounted router is dead code: it cannot be integration-tested, cannot
    appear in the OpenAPI document, and silently rots. This test pins both
    halves of the arrangement — the endpoints exist, and they stay out of the
    consumer surface.
    """
    paths = _paths()
    assert f"{INTERNAL_PREFIX}/sessions/{{session_id}}/context/report" in paths
    assert f"{INTERNAL_PREFIX}/sessions/{{session_id}}/policy/evaluate" in paths

    for path in paths:
        if "policy" in path or "/context" in path:
            assert path.startswith(INTERNAL_PREFIX), (
                f"framework route {path} leaked into the consumer surface"
            )


def test_live_session_has_screen_voice_and_control_channels() -> None:
    paths = _paths()
    assert "/sessions/{session_id}/ice-servers" in paths
    assert "/sessions/{session_id}/audio/mute" in paths
    assert "/sessions/{session_id}/remote-control/input" in paths
