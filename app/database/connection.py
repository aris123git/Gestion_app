"""Connexion et session SQLAlchemy vers la base SQLite locale.

Le moteur est configuré pour de bonnes performances hors ligne :
- ``WAL`` (journalisation en écriture anticipée) pour la concurrence lecture/écriture ;
- ``foreign_keys=ON`` pour l'intégrité référentielle ;
- un cache mémoire élargi.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, text
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
    _migrate_schema()
    _backfill_client_debts()


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    ).fetchone()
    return row is not None


def _existing_columns(conn, table: str) -> set[str]:
    return {
        row[1]
        for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    }


def _migrate_schema() -> None:
    """Ajoute les colonnes manquantes (idempotent, sans perte de données)."""
    alterations = {
        "stock_movements": {
            "comment": "TEXT DEFAULT ''",
            "invoice_number": "VARCHAR(80) DEFAULT ''",
            "supplier_id": "INTEGER",
        },
        "clients": {
            "phone2": "VARCHAR(80) DEFAULT ''",
            "last_visit": "VARCHAR(40) DEFAULT ''",
            "purchase_count": "INTEGER DEFAULT 0",
        },
        "products": {
            "is_active": "BOOLEAN DEFAULT 1",
            "free_amount_sale": "BOOLEAN DEFAULT 0",
            "pack_content": "NUMERIC(14, 3) DEFAULT 0",
        },
        "purchases": {
            "status": "VARCHAR(20) DEFAULT 'completed'",
        },
        "sales": {
            "status": "VARCHAR(20) DEFAULT 'completed'",
            "cancel_reason": "VARCHAR(500) DEFAULT ''",
        },
        "debts": {
            "due_date": "DATE",
            "status": "VARCHAR(40) DEFAULT 'en_cours'",
            "created_by": "INTEGER",
        },
        "supplier_debts": {
            "due_date": "DATE",
            "status": "VARCHAR(40) DEFAULT 'en_cours'",
        },
    }
    with engine.begin() as conn:
        for table, columns in alterations.items():
            if not _table_exists(conn, table):
                continue
            existing = _existing_columns(conn, table)
            for name, definition in columns.items():
                if name not in existing:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                    )


def _backfill_client_debts() -> None:
    """Crée une dette d'ouverture pour les soldes ``Client.debt`` sans ledger.

    Idempotent : ne crée rien si le client a déjà au moins une dette, ou si
    le solde est nul.
    """
    from sqlalchemy import func, select

    from app.models.client import Client
    from app.models.debt import ACTIVE_DEBT_STATUSES, STATUS_OPEN, Debt
    from app.services.debt_service import DebtService

    with session_scope() as session:
        if not _table_exists(session.connection(), "debts"):
            return
        clients = list(session.scalars(select(Client)).all())
        for client in clients:
            balance = float(client.debt or 0)
            existing = session.scalar(
                select(func.count()).select_from(Debt).where(Debt.client_id == client.id)
            )
            if balance > 0 and not existing:
                session.add(
                    Debt(
                        client_id=client.id,
                        sale_id=None,
                        amount_initial=balance,
                        amount_remaining=balance,
                        status=STATUS_OPEN,
                        note="Solde repris à la migration (Sprint 1)",
                    )
                )
                session.flush()
            ledger_balance = session.scalar(
                select(func.coalesce(func.sum(Debt.amount_remaining), 0)).where(
                    Debt.client_id == client.id,
                    Debt.status.in_(ACTIVE_DEBT_STATUSES),
                )
            )
            if abs(float(ledger_balance or 0) - float(client.debt or 0)) >= 0.01:
                DebtService.sync_client_debt_cache(session, client.id)
