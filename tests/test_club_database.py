from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

import psycopg

from club_database import Database, DatabaseUnavailable, open_database


class ClubDatabaseTests(TestCase):
    def test_sqlite_data_survives_connection_close_and_reopen(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'club.sqlite3'
            first=open_database('',path)
            first.execute('CREATE TABLE saved (value TEXT)')
            with first:
                first.execute('INSERT INTO saved VALUES(?)',('saved-bank-connection',))
            first.close()
            second=open_database('',path)
            self.assertEqual(second.execute('SELECT value FROM saved').fetchone()[0],'saved-bank-connection')
            second.close()

    def test_postgres_uses_bound_parameters_and_transaction_without_closing_connection(self):
        raw=MagicMock()
        db=Database(raw,postgres=True)
        value="user-input'); DROP TABLE saved; --"
        with db:
            db.execute('INSERT INTO saved(value) VALUES(?)',(value,))
        raw.execute.assert_called_once_with('INSERT INTO saved(value) VALUES(%s)',(value,))
        raw.transaction.assert_called_once()
        raw.close.assert_not_called()
        db.close()
        raw.close.assert_called_once()

    def test_postgres_configuration_does_not_fall_back_to_temporary_sqlite(self):
        with patch('club_database.psycopg.connect',side_effect=psycopg.OperationalError('private database details')):
            with self.assertRaises(DatabaseUnavailable) as error:
                open_database('postgresql://private-database','unused.sqlite3')
        self.assertNotIn('private database details',str(error.exception))
