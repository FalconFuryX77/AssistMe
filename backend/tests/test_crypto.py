"""Tests for the application-layer cryptography.

These are security property tests, not coverage exercises. Each one pins a
specific claim made in ``docs/CRYPTOGRAPHY_DESIGN.md``, so a change that
silently weakens a guarantee fails here rather than in an incident.
"""

import os

import pytest

from core.crypto.blind_index import blind_index, normalise_value, parse_token
from core.crypto.envelope import (
    OVERHEAD_BYTES,
    DecryptionError,
    decrypt,
    encrypt,
    inspect,
)
from core.crypto.hashing import (
    PEPPER_DOMAIN_PASSWORD,
    PEPPER_DOMAIN_RECOVERY,
    hash_secret,
    verify_secret,
)
from core.crypto.keyring import (
    KeyMaterialError,
    KeyPurpose,
    KeyRing,
    VersionedKey,
    generate_key,
    load_keyring,
)


def _keyring(kek_versions=(1,), bik_versions=(1,)) -> KeyRing:
    """Build a deterministic keyring for tests."""
    keys = [
        VersionedKey(
            purpose=KeyPurpose.KEK, version=v, material=bytes([v]) * 32
        )
        for v in kek_versions
    ] + [
        VersionedKey(
            purpose=KeyPurpose.BIK, version=v, material=bytes([100 + v]) * 32
        )
        for v in bik_versions
    ]
    return KeyRing(keys)


# ---------------------------------------------------------------------------
# Envelope encryption
# ---------------------------------------------------------------------------


class TestEnvelopeEncryption:
    def test_round_trip(self) -> None:
        ring = _keyring()
        blob = encrypt(b"Grandma Parker", context="users.display_name", keyring=ring)
        assert decrypt(blob, context="users.display_name", keyring=ring) == (
            b"Grandma Parker"
        )

    def test_ciphertext_is_randomised(self) -> None:
        """Equal plaintexts must not produce equal ciphertexts.

        Deterministic encryption would leak which users share a display name
        directly from the ciphertext column, which is exactly what the blind
        index exists to control deliberately rather than leak by accident.
        """
        ring = _keyring()
        first = encrypt(b"same", context="users.email", keyring=ring)
        second = encrypt(b"same", context="users.email", keyring=ring)
        assert first != second

    def test_overhead_is_bounded(self) -> None:
        ring = _keyring()
        blob = encrypt(b"x" * 100, context="users.email", keyring=ring)
        assert len(blob) == 100 + OVERHEAD_BYTES

    def test_relocation_between_columns_is_rejected(self) -> None:
        """Ciphertext moved to another column must fail authentication.

        An attacker with UPDATE privileges must not be able to lift a value
        from one column into another and have it decrypt.
        """
        ring = _keyring()
        blob = encrypt(b"secret", context="users.display_name", keyring=ring)
        with pytest.raises(DecryptionError):
            decrypt(blob, context="chat_messages.content", keyring=ring)

    def test_row_binding_prevents_row_swap(self) -> None:
        """With a row binding, ciphertext cannot be moved between rows."""
        ring = _keyring()
        blob = encrypt(
            b"secret", context="users.email", row_binding="row-1", keyring=ring
        )
        assert decrypt(
            blob, context="users.email", row_binding="row-1", keyring=ring
        ) == b"secret"
        with pytest.raises(DecryptionError):
            decrypt(blob, context="users.email", row_binding="row-2", keyring=ring)

    @pytest.mark.parametrize("position", [0, 5, 20, 70, -1])
    def test_tampering_is_detected_at_every_offset(self, position: int) -> None:
        """Flipping any byte of the blob must fail authentication."""
        ring = _keyring()
        blob = bytearray(encrypt(b"sensitive value", context="users.email", keyring=ring))
        blob[position] ^= 0x01
        with pytest.raises(DecryptionError):
            decrypt(bytes(blob), context="users.email", keyring=ring)

    def test_truncated_ciphertext_is_rejected(self) -> None:
        ring = _keyring()
        blob = encrypt(b"value", context="users.email", keyring=ring)
        with pytest.raises(DecryptionError):
            decrypt(blob[:-4], context="users.email", keyring=ring)
        with pytest.raises(DecryptionError):
            decrypt(b"", context="users.email", keyring=ring)

    def test_old_key_version_still_decrypts(self) -> None:
        """Key rotation must not orphan existing data."""
        old = _keyring(kek_versions=(1,))
        blob = encrypt(b"written under v1", context="users.email", keyring=old)

        rotated = _keyring(kek_versions=(1, 2))
        assert rotated.active_version(KeyPurpose.KEK) == 2
        assert decrypt(blob, context="users.email", keyring=rotated) == (
            b"written under v1"
        )
        # New writes use the new key.
        assert inspect(
            encrypt(b"new", context="users.email", keyring=rotated)
        ).kek_version == 2

    def test_retired_key_fails_loudly(self) -> None:
        """A missing key version must raise, never silently return garbage."""
        old = _keyring(kek_versions=(1,))
        blob = encrypt(b"value", context="users.email", keyring=old)
        without_v1 = _keyring(kek_versions=(2,))
        with pytest.raises(DecryptionError, match="version 1"):
            decrypt(blob, context="users.email", keyring=without_v1)

    def test_header_is_inspectable_without_keys(self) -> None:
        ring = _keyring()
        blob = encrypt(b"value", context="users.email", keyring=ring)
        header = inspect(blob)
        assert header.kek_version == 1
        assert header.plaintext_bytes == len(b"value")

    def test_empty_context_is_rejected(self) -> None:
        ring = _keyring()
        with pytest.raises(ValueError):
            encrypt(b"value", context="", keyring=ring)


# ---------------------------------------------------------------------------
# Blind index
# ---------------------------------------------------------------------------


class TestBlindIndex:
    def test_deterministic_for_equal_values(self) -> None:
        ring = _keyring()
        a = blind_index("Grandma", domain="users.display_name", keyring=ring)
        b = blind_index("Grandma", domain="users.display_name", keyring=ring)
        assert a == b

    def test_normalisation_folds_case_and_whitespace(self) -> None:
        ring = _keyring()
        variants = ["Grandma", "  grandma ", "GRANDMA", "grand ma".replace(" ", "")]
        tokens = {
            blind_index(v, domain="users.display_name", keyring=ring) for v in variants
        }
        assert len(tokens) == 1

    def test_domain_separation(self) -> None:
        """The same plaintext in two columns must yield unrelated tokens."""
        ring = _keyring()
        a = blind_index("grandma", domain="users.display_name", keyring=ring)
        b = blind_index("grandma", domain="chat_messages.author", keyring=ring)
        assert a != b

    def test_key_dependence(self) -> None:
        """Without the key, a token cannot be reproduced."""
        a = blind_index("grandma", domain="users.display_name", keyring=_keyring(bik_versions=(1,)))
        b = blind_index("grandma", domain="users.display_name", keyring=_keyring(bik_versions=(7,)))
        assert a != b

    def test_token_carries_its_version(self) -> None:
        ring = _keyring(bik_versions=(1, 3))
        token = blind_index("value", domain="users.email", keyring=ring)
        version, digest = parse_token(token)
        assert version == 3
        assert len(digest) == 64

    def test_truncation_shortens_the_digest(self) -> None:
        ring = _keyring()
        token = blind_index("value", domain="users.email", bits=64, keyring=ring)
        _, digest = parse_token(token)
        assert len(digest) == 16

    def test_normalisation_is_unicode_aware(self) -> None:
        # NFKC folds the compatibility ligature to its ASCII expansion.
        assert normalise_value("ﬁle") == normalise_value("file")

    def test_malformed_token_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_token("not-a-token")


# ---------------------------------------------------------------------------
# Secret hashing
# ---------------------------------------------------------------------------


class TestSecretHashing:
    def test_round_trip(self) -> None:
        ring = _keyring()
        stored = hash_secret("correct horse battery staple", keyring=ring)
        assert stored.startswith("$argon2id$")
        assert verify_secret("correct horse battery staple", stored, keyring=ring).ok

    def test_wrong_secret_fails_without_raising(self) -> None:
        ring = _keyring()
        stored = hash_secret("right", keyring=ring)
        result = verify_secret("wrong", stored, keyring=ring)
        assert result.ok is False
        assert result.scheme == "argon2id"

    def test_salted_so_equal_secrets_differ(self) -> None:
        ring = _keyring()
        assert hash_secret("same", keyring=ring) != hash_secret("same", keyring=ring)

    def test_long_secrets_do_not_collide(self) -> None:
        """The bcrypt 72-byte truncation defect must not recur.

        bcrypt ignores input past 72 bytes, so two distinct passphrases sharing
        a 72-byte prefix verify as equal. Peppering with HMAC before Argon2id
        makes the hash input a fixed 32 bytes, so length is irrelevant.
        """
        ring = _keyring()
        first = "A" * 72 + "XXXX"
        second = "A" * 72 + "YYYY"
        stored = hash_secret(first, keyring=ring)
        assert verify_secret(first, stored, keyring=ring).ok
        assert not verify_secret(second, stored, keyring=ring).ok

    def test_pepper_is_required(self) -> None:
        """A stolen database alone must not permit verification."""
        stored = hash_secret("secret", keyring=_keyring(bik_versions=(1,)))
        attacker_view = verify_secret(
            "secret", stored, keyring=_keyring(bik_versions=(9,))
        )
        assert attacker_view.ok is False

    def test_domain_separation_between_uses(self) -> None:
        ring = _keyring()
        stored = hash_secret("value", domain=PEPPER_DOMAIN_PASSWORD, keyring=ring)
        assert not verify_secret(
            "value", stored, domain=PEPPER_DOMAIN_RECOVERY, keyring=ring
        ).ok

    def test_legacy_bcrypt_verifies_and_requests_upgrade(self) -> None:
        """Existing bcrypt credentials must keep working, and be flagged."""
        import bcrypt

        legacy = bcrypt.hashpw(b"legacy-password", bcrypt.gensalt(rounds=4)).decode()
        result = verify_secret("legacy-password", legacy, keyring=_keyring())
        assert result.ok
        assert result.scheme == "bcrypt"
        assert result.needs_rehash

    def test_unknown_hash_scheme_fails_closed(self) -> None:
        result = verify_secret("x", "plaintext-not-a-hash", keyring=_keyring())
        assert result.ok is False
        assert result.scheme == "unknown"


# ---------------------------------------------------------------------------
# Key ring
# ---------------------------------------------------------------------------


class TestKeyRing:
    def test_highest_version_is_active(self) -> None:
        ring = _keyring(kek_versions=(1, 5, 3))
        assert ring.active_version(KeyPurpose.KEK) == 5

    def test_wrong_key_length_is_rejected(self) -> None:
        with pytest.raises(KeyMaterialError):
            VersionedKey(purpose=KeyPurpose.KEK, version=1, material=b"short")

    def test_missing_purpose_is_rejected(self) -> None:
        with pytest.raises(KeyMaterialError, match="BIK"):
            KeyRing([VersionedKey(purpose=KeyPurpose.KEK, version=1, material=b"k" * 32)])

    def test_production_refuses_derived_keys(self) -> None:
        """Deriving keys from SECRET_KEY must be impossible in production."""
        with pytest.raises(KeyMaterialError, match="production"):
            load_keyring({}, secret_key="dev-secret", is_production=True)

    def test_development_derives_stable_keys(self) -> None:
        first = load_keyring({}, secret_key="dev-secret", is_production=False)
        second = load_keyring({}, secret_key="dev-secret", is_production=False)
        assert first.derived and second.derived
        assert first.get(KeyPurpose.KEK, 1) == second.get(KeyPurpose.KEK, 1)
        # Different SECRET_KEY must give different key material.
        third = load_keyring({}, secret_key="other-secret", is_production=False)
        assert first.get(KeyPurpose.KEK, 1) != third.get(KeyPurpose.KEK, 1)

    def test_keys_load_from_environment(self) -> None:
        environ = {
            "ASSISTME_KEK_V4": generate_key(),
            "ASSISTME_BIK_V2": generate_key(),
        }
        ring = load_keyring(environ, secret_key="unused", is_production=True)
        assert ring.active_version(KeyPurpose.KEK) == 4
        assert ring.active_version(KeyPurpose.BIK) == 2
        assert ring.derived is False

    def test_hex_encoded_keys_are_accepted(self) -> None:
        environ = {
            "ASSISTME_KEK_V1": os.urandom(32).hex(),
            "ASSISTME_BIK_V1": os.urandom(32).hex(),
        }
        ring = load_keyring(environ, secret_key="unused", is_production=True)
        assert len(ring.get(KeyPurpose.KEK, 1)) == 32

    def test_describe_leaks_no_material(self) -> None:
        summary = _keyring(kek_versions=(1, 2)).describe()
        assert summary["kek_active"] == 2
        assert "material" not in str(summary).lower()


# ---------------------------------------------------------------------------
# Key rotation
# ---------------------------------------------------------------------------


class TestKeyRotation:
    """Rotation must actually rewrite rows, and be idempotent.

    These exist because the first implementation reported success without
    writing anything. Two separate bugs conspired: it could not read the stored
    ciphertext (so it never detected which rows needed rewriting), and it marked
    rows dirty by assigning an attribute its existing value — a no-op for
    SQLAlchemy's change detection, so no UPDATE was emitted. A rotation that
    silently does nothing is worse than one that fails, because the operator
    then retires a key that is still in use.
    """

    @pytest.mark.asyncio(loop_scope="session")
    async def test_rotation_rewrites_and_is_idempotent(self) -> None:
        from sqlalchemy import select, text

        from core.crypto.envelope import inspect as inspect_blob
        from core.crypto.keyring import (
            KeyPurpose,
            VersionedKey,
            get_keyring,
            reset_keyring,
        )
        from core.crypto.rotation import rotate_table_kek
        from core.database import Base
        from models.user import User
        from tests.conftest import test_engine
        from tests.conftest import test_session_factory as async_session_factory

        # This test drives the ORM directly rather than through the API, so it
        # creates its own tables instead of relying on the request-scoped
        # fixture that the HTTP tests share.
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        original = get_keyring()
        v1 = original.get(KeyPurpose.KEK, original.active_version(KeyPurpose.KEK))
        bik_version = original.active_version(KeyPurpose.BIK)
        bik = original.get(KeyPurpose.BIK, bik_version)

        # Write rows under the current key.
        async with async_session_factory() as db:
            for i in range(3):
                user = User(hashed_password="x")
                user.set_email(f"rotation-{i}@example.com")
                db.add(user)
            await db.commit()

        try:
            # Provision a second KEK version and make it active.
            rotated = KeyRing(
                [
                    VersionedKey(purpose=KeyPurpose.KEK, version=1, material=v1),
                    VersionedKey(
                        purpose=KeyPurpose.KEK, version=2, material=b"\x02" * 32
                    ),
                    VersionedKey(
                        purpose=KeyPurpose.BIK, version=bik_version, material=bik
                    ),
                ]
            )
            reset_keyring(rotated)

            async with async_session_factory() as db:
                report = await rotate_table_kek(db, User, ["email", "display_name"])
                assert report.rewritten >= 3, (
                    f"rotation rewrote {report.rewritten} rows; it must rewrite "
                    "every row still under the old key"
                )
                assert report.failed == 0

                # The rows must now actually be at version 2 on disk.
                raw = (
                    await db.execute(
                        text("SELECT email FROM users WHERE email_bi LIKE 'v%'")
                    )
                ).fetchall()
                versions = {
                    inspect_blob(bytes(row[0])).kek_version for row in raw if row[0]
                }
                assert versions == {2}, f"rows still under KEK {versions}"

                # And must still decrypt.
                users = (await db.execute(select(User))).scalars().all()
                assert any(u.email.startswith("rotation-") for u in users)

            # A second pass has nothing to do.
            async with async_session_factory() as db:
                again = await rotate_table_kek(db, User, ["email", "display_name"])
                assert again.rewritten == 0, "rotation is not idempotent"
                assert again.already_current == again.scanned
        finally:
            reset_keyring(original)
