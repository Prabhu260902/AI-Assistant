"""Database engine/session management for the knowledge graph store."""

from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from services.config import get_settings
from services.models import Base


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url)


def create_all(engine: Engine | None = None) -> None:
    Base.metadata.create_all(engine or get_engine())


@contextmanager
def session_scope(engine: Engine | None = None):
    session_factory = sessionmaker(bind=engine or get_engine())
    session: Session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
