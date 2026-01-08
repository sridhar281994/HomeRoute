from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import database_url


ENGINE = create_engine(database_url(), pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=ENGINE, class_=Session, expire_on_commit=False, autoflush=False, autocommit=False)


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

