"""Domain integrity: enumerated value sets enforced by the database.

The inherited schema declared every categorical column as ``String(20)`` with
the legal values written in a Python comment::

    status: Mapped[str] = mapped_column(
        String(20), default="waiting", nullable=False  # "waiting", "active", "ended"
    )

A comment is not a constraint. Nothing prevented ``status = 'banana'``, a typo
in one of the fourteen services that write these columns, or — the failure mode
that actually matters here — a capability string like ``'tap '`` with trailing
whitespace silently bypassing an ``== 'tap'`` authorisation check. In a system
whose entire security story is "the helpee's device only does what the policy
column says", unconstrained categorical columns are a security defect, not a
style issue.

Every value set below is enforced by the database itself:

* On **PostgreSQL** each becomes a native ``ENUM`` type. Native enums are
  stored as a 4-byte OID rather than a variable-length string, are validated on
  write, and — importantly for this schema — give the query planner exact
  cardinality statistics for the ~5-value domains it plans against.
* On **SQLite** SQLAlchemy emits ``VARCHAR`` plus a ``CHECK (col IN (...))``
  constraint, so the test suite enforces the same domain.

Python-side values remain plain strings, so no service or test code changes.

Adding a value
--------------
Adding a value to a native PostgreSQL enum requires ``ALTER TYPE ... ADD
VALUE``, which is a migration, not an edit to this file. That friction is the
point: widening a security-relevant domain should be a reviewed change.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import Enum

__all__ = [
    "ASSISTANCE_MODES",
    "AUDIT_EVENT_CATEGORIES",
    "CAPABILITIES",
    "DEVICE_PLATFORMS",
    "ESCALATION_STATUSES",
    "NETWORK_TYPES",
    "PAIRING_STATUSES",
    "PARTICIPANT_ROLES",
    "PARTICIPANT_STATUSES",
    "REQUEST_STATUSES",
    "RISK_LEVELS",
    "SESSION_STATUSES",
    "TRUST_STATUSES",
    "assistance_mode_enum",
    "device_platform_enum",
    "escalation_status_enum",
    "network_type_enum",
    "pairing_status_enum",
    "participant_role_enum",
    "participant_status_enum",
    "request_status_enum",
    "risk_level_enum",
    "session_status_enum",
    "trust_status_enum",
]

# ----------------------------------------------------------------------
# Value sets
# ----------------------------------------------------------------------

#: Session lifecycle. ``waiting`` → ``active`` → ``ended``.
SESSION_STATUSES: Final = ("waiting", "active", "ended")

#: Which side of an assistance session a participant is on. Roles are
#: per-session, not per-device: the same install is a helper in one session and
#: a helpee in another.
PARTICIPANT_ROLES: Final = ("helper", "helpee")

#: Connection state of a participant within a session.
PARTICIPANT_STATUSES: Final = ("connected", "disconnected", "left")

#: Lifecycle of a help request from helpee to helper.
REQUEST_STATUSES: Final = ("pending", "accepted", "denied", "cancelled", "expired")

#: Lifecycle of a privilege-escalation request.
ESCALATION_STATUSES: Final = ("pending", "approved", "rejected", "revoked", "expired")

#: Lifecycle of a device-to-device trust relationship.
#:
#: ``rejected`` and ``revoked`` are deliberately distinct: rejected means the
#: request was never accepted, revoked means trust existed and was withdrawn.
#: Collapsing them would lose the ability to answer "did this person ever have
#: access to my screen?", which is exactly the question a worried user asks.
TRUST_STATUSES: Final = ("pending", "accepted", "rejected", "revoked")

#: Lifecycle of a one-time pairing code.
#:
#: ``awaiting_helper`` is the helper-driven variant: the helpee generates a
#: setup code before any helper device is known, so the pairing exists with no
#: fingerprint until a helper claims it. ``locked`` is the terminal state after
#: too many failed code attempts, distinguished from ``expired`` so that
#: "someone is guessing your code" is visible in the audit trail rather than
#: indistinguishable from an unused code timing out.
PAIRING_STATUSES: Final = (
    "pending",
    "awaiting_helper",
    "claimed",
    "confirmed",
    "expired",
    "locked",
)

#: Risk classification produced by the adaptive policy engine.
RISK_LEVELS: Final = ("low", "medium", "high")

#: Assistance mode selected by the policy engine, in ascending privilege order.
#: ``restricted`` is view-only; ``tap`` implies full gesture control.
ASSISTANCE_MODES: Final = ("restricted", "voice", "pointer", "drawing", "tap")

#: Atomic capabilities that modes are composed from. Stored individually in
#: ``policy_decision_capabilities`` so the set is a first-normal-form relation
#: rather than a delimited string.
CAPABILITIES: Final = ("voice", "pointer", "drawing", "tap", "drag", "keyboard")

#: Client platform.
DEVICE_PLATFORMS: Final = ("android", "ios", "web", "unknown")

#: Network transport reported by the client, used as a risk and adaptation signal.
NETWORK_TYPES: Final = ("wifi", "cellular", "ethernet", "none", "unknown")

#: Coarse grouping of audit events, used for retention policy and for the
#: partial indexes that serve the security review queries.
AUDIT_EVENT_CATEGORIES: Final = (
    "session",
    "consent",
    "capability",
    "input",
    "security",
    "recording",
    "model",
)


# ----------------------------------------------------------------------
# SQLAlchemy enum type factories
# ----------------------------------------------------------------------


def _enum(values: tuple[str, ...], name: str) -> Enum:
    """Build a database-enforced enum type.

    ``create_constraint=True`` matters for the SQLite path: without it,
    SQLAlchemy emits a bare ``VARCHAR`` and the domain is unenforced in tests
    even though it is enforced in production — the worst possible split, since
    a test would happily accept a value production rejects.

    ``validate_strings=True`` additionally rejects out-of-domain values in
    Python before a round trip, turning a database error into a clear
    application-level one.
    """
    return Enum(
        *values,
        name=name,
        native_enum=True,
        create_constraint=True,
        validate_strings=True,
        metadata=None,
    )


def session_status_enum() -> Enum:
    return _enum(SESSION_STATUSES, "session_status")


def participant_role_enum() -> Enum:
    return _enum(PARTICIPANT_ROLES, "participant_role")


def participant_status_enum() -> Enum:
    return _enum(PARTICIPANT_STATUSES, "participant_status")


def request_status_enum() -> Enum:
    return _enum(REQUEST_STATUSES, "request_status")


def escalation_status_enum() -> Enum:
    return _enum(ESCALATION_STATUSES, "escalation_status")


def trust_status_enum() -> Enum:
    return _enum(TRUST_STATUSES, "trust_status")


def pairing_status_enum() -> Enum:
    return _enum(PAIRING_STATUSES, "pairing_status")


def risk_level_enum() -> Enum:
    return _enum(RISK_LEVELS, "risk_level")


def assistance_mode_enum() -> Enum:
    return _enum(ASSISTANCE_MODES, "assistance_mode")


def capability_enum() -> Enum:
    return _enum(CAPABILITIES, "capability")


def device_platform_enum() -> Enum:
    return _enum(DEVICE_PLATFORMS, "device_platform")


def network_type_enum() -> Enum:
    return _enum(NETWORK_TYPES, "network_type")


def audit_category_enum() -> Enum:
    return _enum(AUDIT_EVENT_CATEGORIES, "audit_event_category")


# ----------------------------------------------------------------------
# Ordering helpers (privilege lattice)
# ----------------------------------------------------------------------

#: Privilege rank of each assistance mode. The policy engine's core safety
#: invariant is expressed against this ordering: a decision may never select a
#: mode whose rank exceeds the rank permitted by the rule-based ceiling.
MODE_RANK: Final[dict[str, int]] = {
    mode: rank for rank, mode in enumerate(ASSISTANCE_MODES)
}

#: Capabilities each mode confers. ``tap`` is cumulative over the lower modes.
MODE_CAPABILITIES: Final[dict[str, frozenset[str]]] = {
    "restricted": frozenset(),
    "voice": frozenset({"voice"}),
    "pointer": frozenset({"voice", "pointer"}),
    "drawing": frozenset({"voice", "pointer", "drawing"}),
    "tap": frozenset({"voice", "pointer", "drawing", "tap"}),
}

#: Risk levels ordered by severity, for monotonicity assertions.
RISK_RANK: Final[dict[str, int]] = {level: i for i, level in enumerate(RISK_LEVELS)}
