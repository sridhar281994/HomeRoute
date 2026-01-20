from __future__ import annotations

import os
from sqlalchemy import create_engine, text


def main() -> None:
    db_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not db_url:
        raise SystemExit("DATABASE_URL is required")

    engine = create_engine(db_url, future=True)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM property_images"))
        conn.execute(text("DELETE FROM saved_properties"))
        conn.execute(text("DELETE FROM contact_usage"))
        conn.execute(text("DELETE FROM free_contact_usage"))
        conn.execute(text("DELETE FROM moderation_logs WHERE entity_type IN ('property', 'property_image')"))
        conn.execute(text("DELETE FROM properties"))

    print("Cleared property-related records.")


if __name__ == "__main__":
    main()
