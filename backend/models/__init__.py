"""SQLAlchemy ORM models.

Import order matters: SQLAlchemy resolves ``relationship()`` targets by name at
configuration time, so every model must be imported before the first mapper is
used. Importing this package is what guarantees that.

Table groups
------------
*Identity and trust* — ``users``, ``device_accounts``, ``refresh_tokens``,
``trusted_contacts``, ``trusted_devices``, ``device_pairings``.

*Sessions* — ``sessions``, ``session_participants``, ``chat_messages``,
``file_transfers``, ``assistance_requests``, ``assistance_escalations``.

*Context and policy* — ``context_events`` (append-only history),
``context_snapshots`` (current-state projection), ``policy_decisions`` and
``policy_decision_capabilities``.

*Audit* — ``audit_ledger`` (append-only, hash-chained), ``audit_logs``
(deprecated predecessor).

*Learning* — ``assistance_task_patterns``, ``assistance_action_transitions``,
``preferred_assistance_modes``, ``assistance_suggestions``, ``ml_decision_log``.
"""

from models.user import User  # noqa: F401
from models.device_account import DeviceAccount  # noqa: F401
from models.refresh_token import RefreshToken  # noqa: F401
from models.trusted_contact import TrustedContact  # noqa: F401
from models.session import Session  # noqa: F401
from models.session_participant import SessionParticipant  # noqa: F401
from models.trusted_device import DevicePairing, TrustedDevice  # noqa: F401
from models.assistance_request import (  # noqa: F401
    AssistanceEscalation,
    AssistanceRequest,
)
from models.audit_log import AuditLog  # noqa: F401
from models.audit_ledger import AuditLedgerEntry  # noqa: F401
from models.chat_message import ChatMessage  # noqa: F401
from models.file_transfer import FileTransfer  # noqa: F401
from models.context_event import ContextEvent  # noqa: F401
from models.context_snapshot import ContextSnapshot  # noqa: F401
from models.policy_decision import PolicyDecision, PolicyDecisionCapability  # noqa: F401
from models.ml_decision_log import MLDecisionLog  # noqa: F401
from models.intelligent_assistance import (  # noqa: F401
    AssistanceActionTransition,
    AssistanceSuggestion,
    AssistanceTaskPattern,
    PreferredAssistanceMode,
)
from models.guide import GuideStep, SessionGuide  # noqa: F401

__all__ = [
    "GuideStep",
    "SessionGuide",
    "AssistanceActionTransition",
    "AssistanceEscalation",
    "AssistanceRequest",
    "AssistanceSuggestion",
    "AssistanceTaskPattern",
    "AuditLedgerEntry",
    "AuditLog",
    "ChatMessage",
    "ContextEvent",
    "ContextSnapshot",
    "DeviceAccount",
    "DevicePairing",
    "FileTransfer",
    "MLDecisionLog",
    "PolicyDecision",
    "PolicyDecisionCapability",
    "PreferredAssistanceMode",
    "RefreshToken",
    "Session",
    "SessionParticipant",
    "TrustedContact",
    "TrustedDevice",
    "User",
]
from models.guide_delivery import GuideDelivery  # noqa: F401
