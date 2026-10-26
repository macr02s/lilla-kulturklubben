"""Shared database adapter: local SQLite or persistent PostgreSQL on the server."""
from pathlib import Path
import sqlite3

import psycopg


class DatabaseUnavailable(Exception):
    pass


class Database:
    def __init__(self, raw, postgres=False):
        self.raw = raw
        self.postgres = postgres
        self.transactions = []

    def execute(self, query, parameters=()):
        # Queries are internal constants. User values remain bound parameters.
        if self.postgres:
            query = query.replace("?", "%s")
        try:
            return self.raw.execute(query, parameters)
        except (psycopg.OperationalError, psycopg.InterfaceError, sqlite3.OperationalError):
            raise DatabaseUnavailable("Databasen är inte tillgänglig just nu.") from None

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()

    def __enter__(self):
        context = self.raw.transaction() if self.postgres else self.raw
        self.transactions.append(context)
        context.__enter__()
        return self

    def __exit__(self, *args):
        return self.transactions.pop().__exit__(*args)


def open_database(database_url, sqlite_path):
    try:
        if database_url:
            return Database(psycopg.connect(database_url, autocommit=True,
                                            connect_timeout=5, prepare_threshold=None), postgres=True)
        path = Path(sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return Database(sqlite3.connect(path, timeout=10))
    except (psycopg.Error, sqlite3.Error, OSError):
        raise DatabaseUnavailable("Databasen kunde inte öppnas. Kontrollera serverns databasinställningar.") from None
