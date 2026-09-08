"""Key generation, inspection, and rotation for the cryptography layer.

Usage::

    python -m scripts.manage_keys generate                 # new key material
    python -m scripts.manage_keys generate --file keys.json
    python -m scripts.manage_keys inspect                  # what is loaded
    python -m scripts.manage_keys rotate --dry-run         # count what changes
    python -m scripts.manage_keys rotate                   # re-encrypt
    python -m scripts.manage_keys rotate --blind-index     # rebuild search tokens

See ``docs/CRYPTOGRAPHY_DESIGN.md`` §8 for what each rotation costs and which
one needs a maintenance window.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("manage_keys")

#: Columns holding envelope-encrypted values, by model.
ENCRYPTED_COLUMNS: dict[str, list[str]] = {
    "User": ["email", "display_name"],
    "DeviceAccount": ["fingerprint", "fcm_token"],
    "TrustedDevice": ["device_fingerprint", "friendly_name"],
    "DevicePairing": ["device_fingerprint", "friendly_name"],
    "Session": ["title"],
    "AssistanceRequest": ["message", "helper_device_fingerprint"],
    "ChatMessage": ["content", "encrypted_payload"],
    "FileTransfer": ["filename"],
}

#: ``(source, index)`` column pairs for blind-index rotation.
BLIND_INDEX_PAIRS: dict[str, list[tuple[str, str]]] = {
    "User": [("email", "email_bi"), ("display_name", "display_name_bi")],
    "DeviceAccount": [("fingerprint", "fingerprint_bi")],
    "TrustedDevice": [("device_fingerprint", "device_fingerprint_bi")],
    "DevicePairing": [("device_fingerprint", "device_fingerprint_bi")],
}


def cmd_generate(args: argparse.Namespace) -> int:
    """Emit fresh key material at the next version."""
    from core.crypto.keyring import KeyPurpose, generate_key, get_keyring

    try:
        ring = get_keyring()
        next_kek = ring.active_version(KeyPurpose.KEK) + 1
        next_bik = ring.active_version(KeyPurpose.BIK) + 1
    except Exception:  # noqa: BLE001 - nothing loaded yet is a normal first run
        next_kek = next_bik = 1

    material = {
        f"ASSISTME_KEK_V{next_kek}": generate_key(),
        f"ASSISTME_BIK_V{next_bik}": generate_key(),
    }

    if args.file:
        path = Path(args.file)
        existing: dict[str, str] = {}
        if path.is_file():
            existing = json.loads(path.read_text(encoding="utf-8"))
            logger.info("Merging into existing key file with %s key(s)", len(existing))
        existing.update(material)
        path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        path.chmod(0o600)
        logger.info("Wrote %s (mode 600)", path)
        print(f"\nPoint the runtime at it:\n  export ASSISTME_KEY_FILE={path.resolve()}")
    else:
        print("\n# Add to the runtime environment. Keep the previous versions:")
        print("# ciphertext written under them stays readable, and removing a")
        print("# key makes its rows permanently undecryptable.\n")
        for name, value in material.items():
            print(f"{name}={value}")

    print(
        "\nAfter provisioning, re-encrypt existing rows under the new KEK:\n"
        "  python -m scripts.manage_keys rotate --dry-run\n"
        "  python -m scripts.manage_keys rotate"
    )
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """Report which key versions are loaded, without revealing material."""
    from core.crypto.keyring import get_keyring

    ring = get_keyring()
    summary = ring.describe()

    print("Key ring")
    print(f"  KEK versions   {summary['kek_versions']}  (active: {summary['kek_active']})")
    print(f"  BIK versions   {summary['bik_versions']}  (active: {summary['bik_active']})")

    if summary["derived_from_secret_key"]:
        print(
            "\n  WARNING: keys are DERIVED FROM SECRET_KEY.\n"
            "  This is a development convenience. In production the process\n"
            "  refuses to start without explicit key material."
        )
    return 0


async def _rotate(dry_run: bool, blind_index: bool) -> int:
    from core.crypto.keyring import KeyPurpose, get_keyring
    from core.crypto.rotation import (
        RotationReport,
        rotate_blind_indexes,
        rotate_table_kek,
    )
    from core.database import async_session_factory, engine

    import models

    ring = get_keyring()
    logger.info(
        "Rotating to KEK v%s (loaded: %s)",
        ring.active_version(KeyPurpose.KEK),
        ring.versions(KeyPurpose.KEK),
    )
    if dry_run:
        logger.info("DRY RUN — no rows will be written")

    total = RotationReport(table="TOTAL")

    async with async_session_factory() as db:
        for model_name, columns in ENCRYPTED_COLUMNS.items():
            model = getattr(models, model_name)
            report = await rotate_table_kek(
                db, model, columns, dry_run=dry_run
            )
            logger.info("  %s", report.summary())
            total.merge(report)

        if blind_index:
            logger.info("Rebuilding blind indexes (requires decrypting each row)")
            for model_name, pairs in BLIND_INDEX_PAIRS.items():
                model = getattr(models, model_name)
                report = await rotate_blind_indexes(db, model, pairs, dry_run=dry_run)
                logger.info("  %s", report.summary())
                total.merge(report)

    await engine.dispose()

    print(f"\n{total.summary()}")
    if total.failures:
        print(f"\n{len(total.failures)} failure(s):")
        for failure in total.failures[:20]:
            print(f"  {failure}")
        if len(total.failures) > 20:
            print(f"  ... and {len(total.failures) - 20} more")
        return 1

    if not dry_run:
        print(
            "\nRotation complete. The previous KEK version can be retired once\n"
            "every row reports the new version — re-run with --dry-run to confirm\n"
            "that nothing remains to rewrite."
        )
    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    return asyncio.run(_rotate(args.dry_run, args.blind_index))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="generate new key material")
    generate.add_argument("--file", help="write to a JSON key file instead of stdout")
    generate.set_defaults(func=cmd_generate)

    inspect = sub.add_parser("inspect", help="show loaded key versions")
    inspect.set_defaults(func=cmd_inspect)

    rotate = sub.add_parser("rotate", help="re-encrypt under the active key")
    rotate.add_argument("--dry-run", action="store_true", help="count without writing")
    rotate.add_argument(
        "--blind-index",
        action="store_true",
        help="also rebuild blind indexes (slow; see CRYPTOGRAPHY_DESIGN.md §8)",
    )
    rotate.set_defaults(func=cmd_rotate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
