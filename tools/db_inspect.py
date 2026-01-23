from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.url import make_url


def _default_database_url() -> str:
    env = (os.environ.get("DATABASE_URL") or "").strip()
    if env:
        return env
    # Fallback to repo-local sqlite DB (useful for dev / CI without secrets).
    db_path = Path(__file__).resolve().parents[1] / "backend" / "local.db"
    return f"sqlite:///{db_path}"


def _safe_url_for_logs(url: str) -> str:
    try:
        u = make_url(url)
        return str(u._replace(password="***"))  # type: ignore[attr-defined]
    except Exception:
        # Avoid printing raw value if parsing fails.
        return "<unparsed DATABASE_URL>"


def _ensure_empty_dir(out_dir: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)


def _pick_cols(preferred: list[str], available: set[str]) -> list[str]:
    out: list[str] = []
    for c in preferred:
        if c in available:
            out.append(c)
    # Add any remaining columns at the end (stable-ish ordering).
    for c in sorted(available):
        if c not in out:
            out.append(c)
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cols), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in cols})


def _utc_day_window(now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    n = now or dt.datetime.now(dt.timezone.utc)
    start = dt.datetime(n.year, n.month, n.day, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    return start, end


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect DB and write CSV summaries into a folder.")
    ap.add_argument("--database-url", default="", help="SQLAlchemy DATABASE_URL (defaults to env DATABASE_URL or backend/local.db).")
    ap.add_argument("--out-dir", required=True, help="Output directory to overwrite (e.g. 'DB_Inspect results').")
    ap.add_argument("--today-only", action="store_true", help="Filter users/properties created today (UTC) when created_at exists.")
    args = ap.parse_args()

    url = (args.database_url or "").strip() or _default_database_url()
    out_dir = Path(args.out_dir)

    _ensure_empty_dir(out_dir)

    engine = create_engine(url, pool_pre_ping=True, future=True)
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    start_utc, end_utc = _utc_day_window()
    today_params = {"start": start_utc, "end": end_utc}

    def has_created_at(table: str) -> bool:
        try:
            cols = {c["name"] for c in insp.get_columns(table)}
            return "created_at" in cols
        except Exception:
            return False

    def fetch_table(table: str, preferred_cols: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        cols_available = {c["name"] for c in insp.get_columns(table)}
        cols = _pick_cols(preferred_cols, cols_available)
        if not cols:
            return [], []
        col_sql = ", ".join([f'"{c}"' for c in cols])
        where = ""
        params: dict[str, Any] = {}
        if bool(args.today_only) and has_created_at(table):
            where = 'WHERE "created_at" >= :start AND "created_at" < :end'
            params = dict(today_params)
        q = f'SELECT {col_sql} FROM "{table}" {where} ORDER BY "id" DESC'
        with engine.connect() as conn:
            rows = conn.execute(text(q), params).mappings().all()
        return [dict(r) for r in rows], cols

    out_meta: dict[str, Any] = {
        "inspected_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "database_url": _safe_url_for_logs(url),
        "today_only": bool(args.today_only),
        "today_window_utc": {"start": start_utc.isoformat(), "end": end_utc.isoformat()},
        "tables": sorted(tables),
    }

    # Users
    if "users" in tables:
        users_rows, users_cols = fetch_table(
            "users",
            preferred_cols=[
                "id",
                "email",
                "phone",
                "username",
                "name",
                "role",
                "state",
                "district",
                "owner_category",
                "company_name",
                "approval_status",
                "created_at",
            ],
        )
        _write_csv(out_dir / "users.csv", users_rows, users_cols)
        out_meta["users_rows"] = len(users_rows)
    else:
        out_meta["users_rows"] = 0

    # Properties (Ads)
    if "properties" in tables:
        prop_rows, prop_cols = fetch_table(
            "properties",
            preferred_cols=[
                "id",
                "ad_number",
                "owner_id",
                "title",
                "property_type",
                "rent_sale",
                "price",
                "state",
                "district",
                "area",
                "status",
                "created_at",
            ],
        )
        _write_csv(out_dir / "ads.csv", prop_rows, prop_cols)
        out_meta["ads_rows"] = len(prop_rows)
    else:
        out_meta["ads_rows"] = 0

    # Dashboard totals
    dashboard: dict[str, Any] = {}
    with engine.connect() as conn:
        if "users" in tables:
            dashboard["users_total"] = int(conn.execute(text('SELECT COUNT(*) AS c FROM "users"')).scalar() or 0)
            try:
                dashboard["users_by_role"] = {
                    str(r["role"]): int(r["c"])
                    for r in conn.execute(text('SELECT "role" AS role, COUNT(*) AS c FROM "users" GROUP BY "role" ORDER BY c DESC')).mappings().all()
                }
            except Exception:
                dashboard["users_by_role"] = {}
        if "properties" in tables:
            dashboard["ads_total"] = int(conn.execute(text('SELECT COUNT(*) AS c FROM "properties"')).scalar() or 0)
            try:
                dashboard["ads_by_status"] = {
                    str(r["status"]): int(r["c"])
                    for r in conn.execute(text('SELECT "status" AS status, COUNT(*) AS c FROM "properties" GROUP BY "status" ORDER BY c DESC')).mappings().all()
                }
            except Exception:
                dashboard["ads_by_status"] = {}
        if "property_images" in tables:
            dashboard["property_images_total"] = int(conn.execute(text('SELECT COUNT(*) AS c FROM "property_images"')).scalar() or 0)
        if "free_contact_usage" in tables:
            dashboard["free_contact_usage_total"] = int(conn.execute(text('SELECT COUNT(*) AS c FROM "free_contact_usage"')).scalar() or 0)
        if "contact_usage" in tables:
            dashboard["contact_usage_total"] = int(conn.execute(text('SELECT COUNT(*) AS c FROM "contact_usage"')).scalar() or 0)

        if bool(args.today_only):
            # Today-only totals (best-effort: only if created_at exists).
            if "users" in tables and has_created_at("users"):
                try:
                    dashboard["users_today"] = int(
                        conn.execute(text('SELECT COUNT(*) AS c FROM "users" WHERE "created_at" >= :start AND "created_at" < :end'), today_params).scalar() or 0
                    )
                except Exception:
                    dashboard["users_today"] = 0
            if "properties" in tables and has_created_at("properties"):
                try:
                    dashboard["ads_today"] = int(
                        conn.execute(text('SELECT COUNT(*) AS c FROM "properties" WHERE "created_at" >= :start AND "created_at" < :end'), today_params).scalar() or 0
                    )
                except Exception:
                    dashboard["ads_today"] = 0

    (out_dir / "dashboard.json").write_text(json.dumps(dashboard, indent=2, default=str) + "\n", encoding="utf-8")
    (out_dir / "meta.json").write_text(json.dumps(out_meta, indent=2) + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

