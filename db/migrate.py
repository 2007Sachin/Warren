"""Apply db/migrations/*.sql on DATABASE_URL_UNPOOLED (direct)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def _direct_dsn() -> str:
    url = os.environ.get("DATABASE_URL_UNPOOLED", "").strip() or os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("DATABASE_URL_UNPOOLED (or DATABASE_URL) is not set")
    return url


def main() -> None:
    import psycopg

    dsn = _direct_dsn()
    files = sorted(p for p in MIGRATIONS.glob("*.sql") if p.is_file())
    conn = psycopg.connect(dsn, connect_timeout=5, autocommit=False)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists schema_migrations (
                  name text primary key,
                  applied_at timestamptz not null default now()
                )
                """
            )
            conn.commit()
            cur.execute("select name from schema_migrations")
            done = {r[0] for r in cur.fetchall()}
            for path in files:
                name = path.name
                if name in done:
                    print(f"skip {name}")
                    continue
                sql = path.read_text()
                cur.execute(sql)
                cur.execute("insert into schema_migrations (name) values (%s)", (name,))
                conn.commit()
                print(f"applied {name}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print("migrations ok")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
