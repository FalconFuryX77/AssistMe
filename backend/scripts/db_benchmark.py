"""Measure the effect of the physical-design decisions with EXPLAIN ANALYZE.

Purpose
-------
A schema document can assert that a partial index helps. This script measures
whether it does, on generated data at a realistic scale, and prints the plans
so the claim can be checked rather than believed.

Each benchmark runs a query twice — once with the relevant index available and
once with it disabled — and reports execution time, rows scanned, and the plan
node chosen. Indexes are disabled with ``enable_indexscan``/``enable_bitmapscan``
rather than by dropping them, so the comparison is against the same physical
table with the same statistics and no rebuild cost between runs.

Usage::

    DATABASE_URL=postgresql+asyncpg://user:pass@host/db \\
        python -m scripts.db_benchmark --scale 200000

Caveats stated up front: this runs on synthetic data on one machine, so the
absolute timings mean nothing. The *ratios* between plans on the same data are
the result, and even those depend on cache state — the script warms each query
before measuring for exactly that reason.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from core.database import async_session_factory, create_tables, engine
from core.db.dialect import is_postgres

APPS = [
    ("com.example.bank", "banking"),
    ("com.example.wallet", "payment"),
    ("com.example.health", "health"),
    ("com.whatsapp", "messaging"),
    ("com.facebook.katana", "social"),
    ("com.android.settings", "system"),
    ("com.spotify.music", "media"),
    ("com.example.notes", "productivity"),
]


@dataclass
class BenchmarkResult:
    """One query measured under two plan regimes."""

    name: str
    description: str
    query: str
    with_index_ms: float
    without_index_ms: float
    with_index_plan: str
    without_index_plan: str
    rows: int

    @property
    def speedup(self) -> float:
        if self.with_index_ms <= 0:
            return 0.0
        return self.without_index_ms / self.with_index_ms

    def summary(self) -> str:
        return (
            f"{self.name:34s} {self.with_index_ms:9.2f}ms "
            f"{self.without_index_ms:11.2f}ms {self.speedup:8.1f}x  "
            f"{self.with_index_plan}"
        )


@dataclass
class BenchmarkReport:
    scale: int
    generated_at: str
    results: list[BenchmarkResult] = field(default_factory=list)
    table_sizes: dict[str, str] = field(default_factory=dict)
    index_sizes: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------
# Data generation
# ----------------------------------------------------------------------


async def seed(session, scale: int) -> None:
    """Generate a workload-shaped dataset.

    Proportions matter more than volume for these measurements. Most sessions
    are ended and most audit entries are old, which is what makes a partial
    index over live rows worth having — on a table where 90% of rows are hot,
    it would not be.
    """
    print(f"Seeding {scale:,} sessions and roughly {scale * 6:,} events...")
    started = time.perf_counter()
    now = datetime.now(timezone.utc)
    rng = random.Random(20260901)

    # The seed spans six months of history, so the partitions covering that
    # range must exist before the first insert. In production the monthly
    # maintenance job does this; here it is explicit.
    await session.execute(
        text("SELECT assistme_provision_partitions('context_events', 1, 7)")
    )
    await session.execute(
        text("SELECT assistme_provision_partitions('audit_ledger', 1, 7)")
    )
    await session.commit()

    n_users = max(100, scale // 20)
    user_ids = [str(uuid.uuid4()) for _ in range(n_users)]

    await session.execute(
        text(
            "INSERT INTO users (id, email, email_bi, hashed_password, is_active,"
            " created_at, updated_at)"
            " SELECT CAST(u.id AS uuid), CAST('\\x00' AS bytea),"
            " 'v1:' || md5(u.id), 'x', true,"
            " CAST(:t AS timestamptz), CAST(:t AS timestamptz)"
            " FROM unnest(CAST(:ids AS text[])) AS u(id)"
        ),
        {"ids": user_ids, "t": now},
    )

    session_rows = []
    for i in range(scale):
        created = now - timedelta(minutes=rng.randint(0, 60 * 24 * 180))
        # 92% ended: the realistic shape, and the reason partial indexes pay.
        ended = rng.random() < 0.92
        session_rows.append(
            {
                "id": str(uuid.uuid4()),
                "creator": rng.choice(user_ids),
                "status": "ended" if ended else rng.choice(["waiting", "active"]),
                "code": f"{i:08X}",
                "created": created,
                "ended": created + timedelta(minutes=rng.randint(1, 45)) if ended else None,
                "granted": rng.random() < 0.08,
            }
        )

    for chunk_start in range(0, len(session_rows), 5000):
        chunk = session_rows[chunk_start : chunk_start + 5000]
        await session.execute(
            text(
                "INSERT INTO sessions (id, creator_id, status, session_code,"
                " timeout_minutes, remote_control_granted, remote_control_granted_at,"
                " remote_control_platform, e2ee_enabled, e2ee_key_exchange_complete,"
                " e2ee_mitm_verified, recording_consent_granted, is_recording,"
                " created_at, updated_at, ended_at)"
                # Every bind is explicitly cast. asyncpg infers parameter
                # types from first use, and a value used in both a column
                # position and a CASE arm gets two conflicting inferences.
                " VALUES (CAST(:id AS uuid), CAST(:creator AS uuid),"
                " CAST(:status AS session_status), :code, 30,"
                " CAST(:granted AS boolean),"
                " CASE WHEN CAST(:granted AS boolean)"
                "      THEN CAST(:created AS timestamptz) ELSE NULL END,"
                " CASE WHEN CAST(:granted AS boolean)"
                "      THEN 'android_accessibility' ELSE NULL END,"
                " true, false, false, false, false,"
                " CAST(:created AS timestamptz), CAST(:created AS timestamptz),"
                " CAST(:ended AS timestamptz))"
            ),
            chunk,
        )
    await session.commit()

    # Context events: the fastest-growing table, several per session.
    print("  seeding context_events...")
    for chunk_start in range(0, len(session_rows), 2000):
        chunk = session_rows[chunk_start : chunk_start + 2000]
        events = []
        for row in chunk:
            for _ in range(rng.randint(3, 8)):
                app, category = rng.choice(APPS)
                events.append(
                    {
                        "sid": row["id"],
                        "uid": row["creator"],
                        "app": app,
                        "cat": category,
                        "sensitive": category
                        in ("banking", "payment", "health", "password_manager"),
                        "secure": rng.random() < 0.2,
                        "t": row["created"],
                    }
                )
        await session.execute(
            text(
                "INSERT INTO context_events (id, session_id, user_id, platform,"
                " foreground_app, foreground_app_category, is_sensitive_app,"
                " accessibility_enabled, accessibility_gesture_capable,"
                " screen_share_permission, microphone_permission,"
                " remote_control_permission, is_screen_sharing,"
                " is_flag_secure_active, is_in_audio_call, role, recorded_at)"
                " VALUES (gen_random_uuid(), CAST(:sid AS uuid), CAST(:uid AS uuid),"
                " 'android', :app, :cat, CAST(:sensitive AS boolean), true, true,"
                " true, true, false, true, CAST(:secure AS boolean), true,"
                " 'helpee', CAST(:t AS timestamptz))"
            ),
            events,
        )
    await session.commit()

    print(f"  done in {time.perf_counter() - started:.1f}s")


# ----------------------------------------------------------------------
# Measurement
# ----------------------------------------------------------------------


async def _explain(session, query: str, params: dict, settings: list[str]) -> tuple[float, str, int]:
    """Run EXPLAIN ANALYZE under a set of planner settings."""
    for setting in settings:
        await session.execute(text(f"SET LOCAL {setting}"))

    # Warm the cache first, so the measurement is not dominated by the first
    # read pulling pages off disk.
    await session.execute(text(query), params)

    rows = (
        await session.execute(
            text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}"), params
        )
    ).scalar_one()

    plan = rows[0]["Plan"] if isinstance(rows, list) else json.loads(rows)[0]["Plan"]
    duration = float(rows[0]["Execution Time"]) if isinstance(rows, list) else 0.0

    node = plan.get("Node Type", "?")
    if "Index Name" in plan:
        node = f"{node} on {plan['Index Name']}"
    else:
        node = _find_scan_node(plan) or node

    return duration, node, int(plan.get("Actual Rows", 0))


def _find_scan_node(plan: dict) -> str | None:
    """Descend to the first scan node, which is what the comparison is about."""
    node_type = plan.get("Node Type", "")
    if "Scan" in node_type:
        name = plan.get("Index Name")
        return f"{node_type} on {name}" if name else node_type
    for child in plan.get("Plans", []):
        found = _find_scan_node(child)
        if found:
            return found
    return None


async def benchmark(
    session, name: str, description: str, query: str, params: dict, disable: list[str]
) -> BenchmarkResult:
    """Measure one query with and without its access path."""
    with_ms, with_plan, rows = await _explain(session, query, params, [])
    await session.rollback()

    without_ms, without_plan, _ = await _explain(
        session, query, params, [f"{flag} = off" for flag in disable]
    )
    await session.rollback()

    return BenchmarkResult(
        name=name,
        description=description,
        query=" ".join(query.split()),
        with_index_ms=with_ms,
        without_index_ms=without_ms,
        with_index_plan=with_plan,
        without_index_plan=without_plan,
        rows=rows,
    )


async def run(scale: int) -> BenchmarkReport:
    report = BenchmarkReport(
        scale=scale, generated_at=datetime.now(timezone.utc).isoformat()
    )

    async with async_session_factory() as session:
        if not is_postgres(session.bind):
            raise SystemExit(
                "This benchmark measures PostgreSQL planner behaviour. "
                "Set DATABASE_URL to a PostgreSQL database."
            )

        await seed(session, scale)

        print("Analysing tables so the planner has current statistics...")
        for table in ("users", "sessions", "context_events"):
            await session.execute(text(f"ANALYZE {table}"))
        await session.commit()

        print("\nRunning benchmarks...\n")
        scans = ["enable_indexscan", "enable_bitmapscan", "enable_indexonlyscan"]

        report.results.append(
            await benchmark(
                session,
                "live sessions by creator",
                "The hot path: a user's non-ended sessions. The partial index "
                "excludes the ~92% of rows that are ended, so it stays small "
                "no matter how much history accumulates.",
                "SELECT id, status, created_at FROM sessions"
                " WHERE creator_id = (SELECT creator_id FROM sessions LIMIT 1)"
                "   AND status <> 'ended' ORDER BY created_at DESC LIMIT 20",
                {},
                scans,
            )
        )

        report.results.append(
            await benchmark(
                session,
                "elevated-control review",
                "Every session that granted remote control — the population a "
                "security review starts from, and a small minority of rows.",
                "SELECT id, remote_control_granted_at FROM sessions"
                " WHERE remote_control_granted"
                " ORDER BY remote_control_granted_at DESC LIMIT 50",
                {},
                scans,
            )
        )

        report.results.append(
            await benchmark(
                session,
                "session list (covering index)",
                "Answered from the index alone via INCLUDE columns, with no "
                "heap access at all.",
                "SELECT status, created_at, creator_id, ended_at FROM sessions"
                " WHERE status = 'ended' AND created_at > now() - interval '30 days'"
                " ORDER BY created_at DESC LIMIT 100",
                {},
                scans,
            )
        )

        report.results.append(
            await benchmark(
                session,
                "context history for a session",
                "The training extract's access pattern: one session's events "
                "in time order.",
                "SELECT foreground_app, recorded_at FROM context_events"
                " WHERE session_id = (SELECT session_id FROM context_events LIMIT 1)"
                " ORDER BY recorded_at",
                {},
                scans,
            )
        )

        report.results.append(
            await benchmark(
                session,
                "protected-content events",
                "Partial index over the security-relevant minority of events.",
                "SELECT count(*) FROM context_events"
                " WHERE (is_flag_secure_active OR is_sensitive_app)"
                "   AND recorded_at > now() - interval '7 days'",
                {},
                scans,
            )
        )

        # Partition pruning is a planner property, not an index one, so it is
        # measured against a full scan rather than an index-disabled plan.
        #
        # The bound is a literal rather than now(). With now() the value is not
        # known until execution, so PostgreSQL falls back to *runtime* pruning,
        # which enable_partition_pruning=off does not disable — the two runs
        # then measure the same plan and the benchmark reports no effect. A
        # constant bound makes it a plan-time decision, which is what the
        # setting controls and what the schema design is claiming.
        # A closed window, not a one-sided bound. "recorded_at > cutoff" is
        # unbounded above, so every future partition still qualifies and the
        # planner correctly cannot prune them — which would understate pruning
        # rather than measure it. Real analytical queries ask for a window.
        window_end = datetime.now(timezone.utc)
        cutoff = window_end - timedelta(days=7)
        report.results.append(
            await benchmark(
                session,
                "partition pruning (7-day window)",
                "A time-windowed scan should touch only the partitions that "
                "can contain matching rows, not all of them.",
                "SELECT count(*) FROM context_events"
                " WHERE recorded_at >= CAST(:cutoff AS timestamptz)"
                "   AND recorded_at <  CAST(:window_end AS timestamptz)",
                {"cutoff": cutoff, "window_end": window_end},
                ["enable_partition_pruning"],
            )
        )

        # How many partitions each plan actually touches — the number the
        # pruning claim is really about, independent of timing noise.
        pruned_plan = (
            await session.execute(
                text(
                    "EXPLAIN SELECT count(*) FROM context_events"
                    " WHERE recorded_at >= CAST(:cutoff AS timestamptz)"
                    "   AND recorded_at <  CAST(:window_end AS timestamptz)"
                ),
                {"cutoff": cutoff, "window_end": window_end},
            )
        ).fetchall()
        await session.rollback()

        await session.execute(text("SET LOCAL enable_partition_pruning = off"))
        unpruned_plan = (
            await session.execute(
                text(
                    "EXPLAIN SELECT count(*) FROM context_events"
                    " WHERE recorded_at >= CAST(:cutoff AS timestamptz)"
                    "   AND recorded_at <  CAST(:window_end AS timestamptz)"
                ),
                {"cutoff": cutoff, "window_end": window_end},
            )
        ).fetchall()
        await session.rollback()

        pruned = sum("context_events_p" in row[0] for row in pruned_plan)
        unpruned = sum("context_events_p" in row[0] for row in unpruned_plan)
        report.notes.append(
            f"Partition pruning: {pruned} of {unpruned} partitions scanned for a "
            f"7-day window ({100 * (1 - pruned / unpruned):.0f}% eliminated "
            "before execution)."
        )

        # --- Sizes ---------------------------------------------------------
        sizes = (
            await session.execute(
                text(
                    "SELECT relname, pg_size_pretty(pg_total_relation_size(oid))"
                    " FROM pg_class WHERE relnamespace = 'public'::regnamespace"
                    "   AND relkind IN ('r','p')"
                    " ORDER BY pg_total_relation_size(oid) DESC LIMIT 12"
                )
            )
        ).fetchall()
        report.table_sizes = {name: size for name, size in sizes}

        index_sizes = (
            await session.execute(
                text(
                    "SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid))"
                    " FROM pg_stat_user_indexes"
                    " ORDER BY pg_relation_size(indexrelid) DESC LIMIT 12"
                )
            )
        ).fetchall()
        report.index_sizes = {name: size for name, size in index_sizes}

        # A BRIN index over append-ordered time data should be dramatically
        # smaller than the equivalent B-tree; this is the number that justifies
        # the choice.
        brin_vs_btree = (
            await session.execute(
                text(
                    "SELECT pg_size_pretty(sum(pg_relation_size(indexrelid)))"
                    " FROM pg_stat_user_indexes WHERE indexrelname LIKE 'brin_%'"
                )
            )
        ).scalar_one_or_none()
        if brin_vs_btree:
            report.notes.append(
                f"Total BRIN index size across context_events partitions: {brin_vs_btree}"
            )

    return report


def print_report(report: BenchmarkReport) -> None:
    print("=" * 100)
    print(f"AssistMe database benchmark — {report.scale:,} sessions")
    print("=" * 100)
    print(
        f"\n{'query':34s} {'with index':>11s} {'without':>12s} {'speedup':>9s}  plan"
    )
    print("-" * 100)
    for result in report.results:
        print(result.summary())

    print("\nLargest relations:")
    for name, size in report.table_sizes.items():
        print(f"  {name:34s} {size}")

    print("\nLargest indexes:")
    for name, size in report.index_sizes.items():
        print(f"  {name:44s} {size}")

    for note in report.notes:
        print(f"\n{note}")

    print(
        "\nAbsolute timings are machine- and cache-specific and mean nothing on "
        "their own.\nThe ratios between plans on identical data are the result."
    )
    print("=" * 100)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", type=int, default=50000, help="number of sessions")
    parser.add_argument("--json", help="write the report to this path")
    args = parser.parse_args()

    await create_tables()
    report = await run(args.scale)
    print_report(report)

    if args.json:
        payload = asdict(report)
        payload["results"] = [
            {**asdict(r), "speedup": r.speedup} for r in report.results
        ]
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
        print(f"\nWrote {args.json}")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
