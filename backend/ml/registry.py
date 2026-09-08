"""Versioned model artefact store with model cards.

Why a registry rather than ``model.pkl``
-----------------------------------------
Three properties are needed on a safety path, and a bare pickle provides none:

**Attribution.** Every row in ``ml_decision_log`` records a ``model_version``.
That is worthless unless the named artefact can be retrieved and re-run months
later. Versions are immutable and content-addressed by a timestamp plus a hash
of the training configuration.

**Rollback.** A regression must be reversible by pointing at the previous
version, not by retraining and hoping. Versions are never overwritten; the
``current`` pointer is a small file that can be moved back in one operation.

**Provenance.** Each artefact carries a **model card** — training data
description, metrics, intended use, and, most importantly, the limitations. The
model card is not documentation added afterwards; it is written by the training
run itself, so it cannot drift from the artefact it describes.

On pickle
---------
Artefacts are serialised with ``joblib``, which uses pickle underneath, so
loading an artefact executes code from the file. The registry therefore
**refuses to load from outside its configured root**, and the root is expected
to be a read-only mount in production. This is stated plainly because "we use
pickle" is often left implicit; the mitigation is that the artefact directory is
part of the deployment's trust boundary, exactly like the application code.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

from ml.config import ARTIFACT_DIR, GLOBAL_SEED

logger = logging.getLogger(__name__)

__all__ = ["ModelCard", "ModelRegistry", "RegistryError"]


class RegistryError(RuntimeError):
    """Raised on a missing, malformed, or out-of-root artefact."""


@dataclass
class ModelCard:
    """Provenance and limitations for one trained artefact.

    Modelled on the Model Cards proposal (Mitchell et al., FAT* 2019). The
    ``limitations`` and ``ethical_considerations`` fields are required rather
    than optional: a model that decides what a stranger may do on an elderly
    person's phone should not be deployable without someone having written down
    what it cannot do.
    """

    name: str
    version: str
    created_at: str

    #: What the model is for, and what it must not be used for.
    intended_use: str
    out_of_scope_use: str

    #: How the training data was produced.
    training_data: str
    n_training_samples: int

    #: Model family and selection criterion.
    model_type: str
    selection_criterion: str

    #: Held-out metrics at training time.
    metrics: dict[str, Any] = field(default_factory=dict)

    #: Known failure modes and populations where performance is weaker.
    limitations: list[str] = field(default_factory=list)
    ethical_considerations: list[str] = field(default_factory=list)

    #: Everything needed to reproduce the run.
    global_seed: int = GLOBAL_SEED
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    feature_names: list[str] = field(default_factory=list)
    library_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _library_versions() -> dict[str, str]:
    """Record the library versions an artefact was produced with.

    A scikit-learn artefact is not guaranteed to load, or to behave identically,
    across major versions. Recording the versions turns a silent behavioural
    change into a diagnosable one.
    """
    versions: dict[str, str] = {}
    for module_name in ("sklearn", "numpy", "scipy", "joblib"):
        try:
            module = __import__(module_name)
            versions[module_name] = getattr(module, "__version__", "unknown")
        except ImportError:  # pragma: no cover
            versions[module_name] = "not installed"
    return versions


class ModelRegistry:
    """Filesystem-backed registry of versioned artefacts.

    Layout::

        artifacts/
          risk_classifier/
            current                    -> text file holding a version string
            2026-09-01T10-00-00Z-a1b2/
              model.joblib
              model_card.json
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or ARTIFACT_DIR).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def save(
        self,
        name: str,
        model: Any,
        card: ModelCard,
        *,
        make_current: bool = True,
    ) -> str:
        """Persist an artefact and its card, returning the version identifier.

        The version is a UTC timestamp plus a short hash of the hyperparameters
        and seed, so two runs of the same configuration are distinguishable by
        time while a configuration change is visible in the identifier itself.
        """
        fingerprint = hashlib.blake2b(
            json.dumps(
                {"hyperparameters": card.hyperparameters, "seed": card.global_seed},
                sort_keys=True,
                default=str,
            ).encode("utf-8"),
            digest_size=3,
        ).hexdigest()

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        version = f"{timestamp}-{fingerprint}"

        card.version = version
        card.created_at = datetime.now(timezone.utc).isoformat()
        card.library_versions = _library_versions()

        directory = self.root / name / version
        directory.mkdir(parents=True, exist_ok=True)

        joblib.dump(model, directory / "model.joblib")
        (directory / "model_card.json").write_text(
            json.dumps(card.to_dict(), indent=2, default=str), encoding="utf-8"
        )

        if make_current:
            self.set_current(name, version)

        logger.info("Saved %s version %s", name, version)
        return version

    def set_current(self, name: str, version: str) -> None:
        """Point ``current`` at a version. This is the rollback operation."""
        directory = self.root / name / version
        if not directory.is_dir():
            raise RegistryError(f"{name} has no version {version}")
        (self.root / name / "current").write_text(version, encoding="utf-8")

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def current_version(self, name: str) -> str | None:
        """The version ``load`` will return, or ``None`` if none is published."""
        pointer = self.root / name / "current"
        if not pointer.is_file():
            return None
        version = pointer.read_text(encoding="utf-8").strip()
        return version or None

    def versions(self, name: str) -> list[str]:
        """All stored versions, newest first."""
        directory = self.root / name
        if not directory.is_dir():
            return []
        return sorted(
            (p.name for p in directory.iterdir() if p.is_dir()), reverse=True
        )

    def load(self, name: str, version: str | None = None) -> tuple[Any, ModelCard]:
        """Load an artefact and its card.

        Raises:
            RegistryError: If nothing is published, or the resolved path
                escapes the registry root.
        """
        version = version or self.current_version(name)
        if version is None:
            raise RegistryError(
                f"No current version published for {name!r}. "
                f"Run `python -m ml.experiments.run_all --train` first."
            )

        directory = (self.root / name / version).resolve()

        # Path containment check. ``version`` reaches this method from a
        # database column, so a value like "../../etc" must not be able to make
        # joblib unpickle an arbitrary file.
        if not directory.is_relative_to(self.root):
            raise RegistryError(
                f"Refusing to load artefact outside the registry root: {directory}"
            )

        model_path = directory / "model.joblib"
        card_path = directory / "model_card.json"
        if not model_path.is_file():
            raise RegistryError(f"{name} version {version} has no model.joblib")

        model = joblib.load(model_path)
        card_data = (
            json.loads(card_path.read_text(encoding="utf-8"))
            if card_path.is_file()
            else {}
        )
        card = ModelCard(
            **{
                key: card_data.get(key, default)
                for key, default in _card_defaults().items()
            }
        )
        return model, card

    def prune(self, name: str, keep: int = 5) -> list[str]:
        """Delete all but the newest ``keep`` versions, never the current one."""
        current = self.current_version(name)
        removed: list[str] = []
        for version in self.versions(name)[keep:]:
            if version == current:
                continue
            shutil.rmtree(self.root / name / version, ignore_errors=True)
            removed.append(version)
        return removed


def _card_defaults() -> dict[str, Any]:
    """Field defaults, so an older card missing a field still loads."""
    return {
        "name": "unknown",
        "version": "unknown",
        "created_at": "",
        "intended_use": "",
        "out_of_scope_use": "",
        "training_data": "",
        "n_training_samples": 0,
        "model_type": "",
        "selection_criterion": "",
        "metrics": {},
        "limitations": [],
        "ethical_considerations": [],
        "global_seed": GLOBAL_SEED,
        "hyperparameters": {},
        "feature_names": [],
        "library_versions": {},
    }
