"""Connexion et session SQLAlchemy vers la base SQLite locale.

Le moteur est configuré pour de bonnes performances hors ligne :
- ``WAL`` (journalisation en écriture anticipée) pour la concurrence lecture/écriture ;
- ``foreign_keys=ON`` pour l'intégrité référentielle ;
- un cache mémoire élargi.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app import config


class Base(DeclarativeBase):
    """Classe de base déclarative pour tous les modèles ORM."""


config.ensure_directories()

engine: Engine = create_engine(
    config.database_url(),
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    """Active les optimisations SQLite à chaque nouvelle connexion."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-16000")
    cursor.close()


def get_session() -> Session:
    """Retourne une nouvelle session (à fermer par l'appelant)."""
    return SessionFactory()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Fournit une session transactionnelle (commit/rollback automatique)."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_database() -> None:
    """Crée toutes les tables si elles n'existent pas encore."""
    # Import tardif pour enregistrer les modèles sur ``Base.metadata``.
    from app import models  # noqa: F401

    config.ensure_directories()
    Base.metadata.create_all(engine)
