# Cryptography Design

> Application-layer protection for personal data.
> Implementation: `backend/core/crypto/` · Tests: `backend/tests/test_crypto.py`
> Companion: [`DATABASE_DESIGN.md`](DATABASE_DESIGN.md),
> [`threat_model.md`](threat_model.md)

---

## 1. Threat model

AssistMe's users are elderly people and their families. The database holds what
they are struggling with, who they trust, which device is theirs, and what was
said during a session. This document covers protection of that data **at rest**,
against a specific and deliberately narrow set of adversaries.

### In scope

| Adversary | Capability | Defence |
|---|---|---|
| **Backup or dump theft** | Reads a database file or `pg_dump` output | Field-level AES-256-GCM. Ciphertext without key material is useless. |
| **Compromised read replica** | Reads all rows via SQL | Same. Key material is not in the database. |
| **Over-broad analyst access** | Legitimate SQL access, no key access | Same. Analysts see ciphertext and blind-index tokens. |
| **Ciphertext relocation** | Has `UPDATE`; moves ciphertext between columns or rows | AEAD associated data binds every ciphertext to its column (and optionally its row). |
| **Offline credential cracking** | Has the credential hash table | Argon2id with a keyed pepper. Without the pepper, no offline attack is possible at all. |
| **Bearer-token replay from a dump** | Has `refresh_tokens` | Only SHA-256 digests are stored; the dump yields no usable tokens. |

### Explicitly out of scope

* **A live compromise of the application process.** It holds key material by
  necessity; an attacker with code execution there can decrypt what the
  application can decrypt. Mitigating this needs an HSM or a separate decryption
  service, which is future work, not a claim made here.
* **End-to-end encryption of chat.** `VISION.md` records a deliberate, disclosed
  trade-off: chat is server-readable in v1. That is about confidentiality
  *against the operator*, which is not claimed. Confidentiality against *theft*
  is claimed, and is delivered — the distinction is exactly the point of §5.
* **Traffic analysis and metadata.** Row counts, timestamps, and the shape of
  the trust graph are not hidden. Hiding them needs padding and oblivious access
  structures well beyond this system's threat model.
* **WebRTC media.** Already end-to-end encrypted by DTLS-SRTP; TURN relays
  ciphertext. Nothing here changes that.

---

## 2. Key hierarchy

```
Key Encryption Key (KEK, versioned)          ← environment / secret mount
    └── Data Encryption Key (DEK, per field)  ← random 32 B, wrapped by KEK
            └── field ciphertext (AES-256-GCM)

Blind Index Key (BIK, versioned)             ← environment / secret mount
    ├── HMAC-SHA256 deterministic search token
    └── pepper for Argon2id credential hashing
```

A **fresh DEK per field write** is what removes the nonce-reuse constraint that
normally bounds AES-GCM at 2³² messages per key: each DEK encrypts exactly one
message, so 96-bit random nonces are safe without a counter.

Only the *wrapped* DEK reaches storage, so compromising one row's ciphertext
does not help decrypt any other row.

### Key provisioning

```bash
# Production: explicit key material, highest version is active
ASSISTME_KEK_V3=<base64url or hex, 32 bytes>   # active
ASSISTME_KEK_V2=<...>                          # retained, decrypt-only
ASSISTME_BIK_V1=<...>

# Preferred: a mounted secret, so key bytes never appear in the process
# environment listing
ASSISTME_KEY_FILE=/var/run/secrets/assistme/keys.json
```

In development, with no key material supplied, keys are derived from
`SECRET_KEY` via HKDF-SHA256 with a distinct `info` per purpose, so a developer
database stays readable across restarts. **This derivation is refused outright
when `APP_ENV` is production** — the process will not start.

Generate keys with `python -m scripts.manage_keys generate`.

---

## 3. Envelope encryption

### Wire format

```
offset  size  field
------  ----  -----------------------------------------------------------
0       1     format version           (0x01)
1       1     algorithm identifier     (0x01 = AES-256-GCM envelope)
2       2     KEK version, big-endian uint16
4       12    DEK wrap nonce
16      48    wrapped DEK (32 B ciphertext + 16 B GCM tag)
64      12    payload nonce
76      ..    payload ciphertext + 16 B GCM tag
```

Fixed overhead: **92 bytes per encrypted field**. The blob is self-describing,
so a value written under an older key version stays readable with no out-of-band
metadata and no lookup table.

### Associated data: defeating relocation

Both GCM operations authenticate associated data that includes a caller-supplied
context string, conventionally `"<table>.<column>"`:

```python
encrypt(value, context="users.display_name")
```

An attacker with `UPDATE` cannot lift the ciphertext of `users.display_name`
into `chat_messages.content` and have it decrypt — the context in the AAD would
not match and GCM authentication fails.

Callers that know a stable row identity may bind it too (`row_binding`), which
additionally defeats row-swap within a single column. **The ORM type decorators
cannot do this**: a type decorator has no access to the row being flushed. So
the default protection is column-level, row-level binding is available to call
sites that manage it explicitly, and this limitation is stated rather than
hidden.

### Storage

Ciphertext is `LargeBinary` — `BYTEA` on PostgreSQL, `BLOB` on SQLite. This
avoids base64's 33% inflation and keeps the test dialect working unmodified.

---

## 4. Blind indexes

### The problem

A randomised AEAD — which is the correct choice — means two rows holding the
same plaintext produce different ciphertexts. That breaks
`WHERE display_name = 'Grandma'` and every `UNIQUE` constraint.

### The construction

```
token = "v{version}:" ‖ hex( HMAC-SHA256(BIK_v, domain ‖ 0x00 ‖ normalise(plaintext)) )
```

Because it is **keyed**, an attacker holding only the database cannot compute
tokens for guessed plaintexts — unlike an unkeyed hash, which is trivially
dictionary-attacked over a small domain such as first names. Because it is
**deterministic**, equality lookups and uniqueness work with a plain B-tree.

### What it deliberately leaks, and the mitigations

Determinism necessarily leaks **equality**: an attacker learns which rows share
a value and can mount frequency analysis against a known plaintext distribution
(that "Mum" is a common display name, say). Three mitigations, and an honest
statement that the leak is inherent rather than eliminated:

| Mitigation | Effect |
|---|---|
| **Per-domain separation** | The same plaintext in two columns yields unrelated tokens, so cross-column correlation fails. |
| **Key versioning** | The index can be rotated — though this requires decrypting to re-derive, so it is expensive. |
| **Optional truncation** | `bits < 256` induces deliberate collisions, flattening the frequency distribution at the cost of a decrypt-side post-filter. |

Full 256-bit tokens are used where a `UNIQUE` constraint must be exact.
Eliminating the equality leak entirely requires an oblivious index structure,
which is out of scope for this system.

### Normalisation

Values are NFKC-normalised, case-folded, whitespace-collapsed and stripped, so
`"Grandma "` matches `"grandma"`. The consequence — the index cannot distinguish
values differing only in those respects — is intended for names and wrong for
device fingerprints, which pass `normalise=False`.

### Where blind indexes replaced something worse

| Column | Was | Now |
|---|---|---|
| `users.display_name` | `WHERE lower(display_name) = ?` — a **sequential scan on every registration**, and a check-then-act race that let two concurrent registrations both succeed | Unique blind index: O(log n) lookup, uniqueness enforced by the database under concurrency |
| `device_pairings.pairing_code` | Loaded **every** open pairing in the database and compared hashes in Python — O(global traffic) per keystroke of a six-digit code, and a trivial denial-of-service lever | Index lookup narrowing to the one or two rows that collide on six digits |
| `device_accounts.recovery_code` | Unsalted SHA-256, looked up by hash equality | Blind index for lookup, Argon2id for verification (§5.2) |

---

## 5. Credential hashing

### 5.1 Argon2id with a keyed pepper

The inherited implementation used bcrypt at cost 12. Two properties made that
the wrong choice here:

* **72-byte silent truncation.** bcrypt ignores input past 72 bytes, so two
  distinct passphrases sharing a 72-byte prefix verify as *equal*. That is a
  correctness bug, not a theoretical concern — and bcrypt 5.x now raises on
  such input instead, so the inherited `hash_password` would crash outright on a
  long passphrase. (Found by testing; see `tests/test_crypto.py::
  test_long_secrets_do_not_collide`.)
* **Low memory hardness.** bcrypt's 4 KiB working set parallelises cheaply on
  GPUs.

Argon2id — PHC winner, RFC 9106 default, OWASP recommendation — is memory-hard.
Parameters follow RFC 9106 §4's second recommended option: **64 MiB, t=3, p=4**,
about 50–80 ms per verification on commodity hardware.

**Peppering** applies `HMAC-SHA256(BIK, domain ‖ 0x00 ‖ secret)` before hashing.
An attacker who steals only the database — the overwhelmingly common breach
shape — cannot mount an offline dictionary attack **at all**, because they lack
the pepper. One who steals both faces Argon2id at full cost. As a side effect
the hash input is always exactly 32 bytes, so the truncation class of bug cannot
recur.

Legacy bcrypt hashes still verify and are upgraded opportunistically on the next
successful login — the one moment the plaintext is known to be correct — so no
forced reset is needed.

### 5.2 Lookup versus verification

Salting makes hash-equality lookup impossible; that is what a per-record salt is
*for*. But the reclaim flow must **find** an account from a code the user types
and then **verify** it. The inherited code resolved this by using one unsalted
SHA-256 for both roles, which meant a database dump yielded every 12-character
recovery code by dictionary attack — and every **six-digit** pairing code by
exhaustive search of 10⁶ preimages, in milliseconds.

The two roles are now separated:

```python
# 1. Find: keyed, indexed, O(log n). Not a credential check.
account = await db.execute(
    select(DeviceAccount).where(DeviceAccount.recovery_code_bi == code)
)
# 2. Verify: salted, memory-hard, peppered. The actual credential check.
verify_secret(code, account.recovery_code_hash, domain=PEPPER_DOMAIN_RECOVERY)
```

Neither alone is sufficient. Recovering a six-digit code now costs roughly
10⁶ × 60 ms of memory-hard work per code — and is impossible without the pepper.

### 5.3 Refresh tokens: SHA-256, not Argon2id

Refresh tokens are stored as bare SHA-256 digests, and that is deliberate rather
than an oversight.

Password hashing is slow *because* passwords have low entropy and must resist
offline guessing. A refresh token is 48 bytes from `secrets.token_urlsafe` —
384 bits of uniform randomness. There is no dictionary and no feasible brute
force, so a memory-hard KDF would buy nothing while adding ~60 ms to every token
refresh. A single SHA-256 is the correct construction for a high-entropy secret.

The change that mattered was storing the digest at all. The inherited table held
the token itself under a `UNIQUE` index, making the database a bearer-credential
store: anyone with a dump could mint access tokens for every user with no
cracking step, for the seven-day token lifetime.

The migration hashes existing tokens **without signing anyone out** — the lookup
path hashes whatever the client presents, so a token issued before the migration
still authenticates afterwards, and the client holds the only copy of the
plaintext. That is precisely the intended end state.

---

## 6. What is encrypted, and what is not

### Encrypted

| Table | Columns | Why |
|---|---|---|
| `users` | `email`, `display_name` | Directly identifying |
| `device_accounts` | `fingerprint`, `fcm_token` | Identifies a physical handset; the FCM token is a durable push handle to a specific person |
| `trusted_devices`, `device_pairings` | `device_fingerprint`, `friendly_name` | "Mum's phone" is personal data |
| `sessions` | `title` | The helpee's own words about what is wrong |
| `assistance_requests` | `message`, `helper_device_fingerprint` | Among the most sensitive free text here — a vulnerable person describing their difficulty |
| `chat_messages` | `content`, `encrypted_payload` | Session conversation |
| `file_transfers` | `filename` | `bank-statement-march.pdf` discloses a great deal |
| `context_events` | `extra` | An open payload from a personal device is personal data by default |

### Deliberately in plaintext

`context_events.foreground_app` and `foreground_app_category` are the grouping
keys of `mv_app_risk_profile` and the strongest single predictor in the risk
model. Encrypting them would make the feature store unbuildable — and the risk
classifier is the mechanism that *protects* users in sensitive apps.

This is a real confidentiality/utility trade-off, decided in favour of utility
with the privacy cost bounded by the view's `k >= 5` aggregation floor (§8 of
`DATABASE_DESIGN.md`). It is recorded here so the decision can be revisited
rather than rediscovered.

`chat_messages.encrypted_payload` is encrypted **again** at rest even when the
client already encrypted it end-to-end. Double encryption costs 92 bytes and one
AES-GCM pass, and removes the need to reason about whether the client's scheme is
sound before concluding the server's storage is safe.

---

## 7. Failure policy

`strict=True` is the default on every encrypted column: a row that fails
authentication raises rather than rendering a placeholder. A ciphertext that
does not authenticate is a security event — tampering, a wrong key, or
relocation from another column — not a display glitch. Analytics-only columns
may opt into `strict=False`, where one unreadable telemetry row should not take
down a dashboard.

A **retired key version fails loudly**. `KeyRing.get` raises with the loaded
versions listed, rather than returning garbage. Silent data loss is worse than a
startup error.

---

## 8. Key rotation

**KEK rotation** is cheap and online-safe. Only the wrapped DEK inside each blob
is rewritten, and because the envelope is self-describing, old and new rows
coexist during the run. Reads keep working throughout. Rows already at the
target version are skipped by inspecting the header, so an interrupted run is
safely resumable.

**BIK rotation** is expensive and must be planned. A blind index is a one-way
function of plaintext, so a new token can only be derived by decrypting the
source column first — which is why it runs through the ORM rather than in SQL.
A `UNIQUE` constraint on an index column can only be re-satisfied atomically, so
this needs a maintenance window or a drop-and-rebuild of the constraint: a
partially rotated column briefly holds tokens from two key generations that
cannot collide-check against each other.

Both run in bounded batches with a commit per batch, so a rotation over a large
table neither holds a long transaction open nor blocks writers for its duration.

```bash
python -m scripts.manage_keys generate            # new key material
python -m scripts.manage_keys rotate --dry-run    # count what would change
python -m scripts.manage_keys rotate              # execute
```

---

## 9. A note on pickle

Model artefacts are loaded with `joblib`, which uses pickle, so loading executes
code from the file. The registry therefore **refuses to load from outside its
configured root**, and that root is expected to be a read-only mount in
production.

This is stated plainly because "we use pickle" is usually left implicit. The
mitigation is that the artefact directory is part of the deployment's trust
boundary, exactly like the application code — not that pickle has been made
safe, because it has not.

---

## 10. Verified properties

`tests/test_crypto.py` — 39 tests, each pinning a claim made above:

* Round-trip correctness across all types
* Ciphertext is randomised (equal plaintexts → different ciphertexts)
* Relocation between columns is rejected
* Row-binding prevents row-swap
* Tampering is detected at **every byte offset** (parametrised)
* Truncated ciphertext is rejected
* Old key versions still decrypt; new writes use the new key
* A retired key version raises rather than returning garbage
* Blind indexes are deterministic, normalised, domain-separated, key-dependent
* Argon2id round-trips; wrong secrets fail without raising
* **Long secrets do not collide** — the bcrypt truncation defect cannot recur
* **The pepper is required** — a database-only attacker cannot verify
* Legacy bcrypt verifies and requests upgrade
* Production refuses key derivation from `SECRET_KEY`
* `describe()` leaks no key material
