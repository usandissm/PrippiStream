# -*- coding: utf-8 -*-

import os
import sys

# Appends the main plugin dir to the PYTHONPATH if an internal package cannot be imported.
# Examples: In Plex Media Server all modules are under "Code.*" package, and in Enigma2 under "Plugins.Extensions.*"
try:
    import core
except:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Connect to database
from . import filetools
from platformcode import config
from collections import defaultdict
from lib.sqlitedict import SqliteDict


class nested_dict_sqlite(defaultdict):
    'like defaultdict but default_factory receives the key'

    def __missing__(self, key):
        self[key] = value = self.default_factory(key)
        return value

    def close(self):
        for key in self.keys():
            self[key].close()
        self.clear()


db_name = filetools.join(config.get_data_path(), "db.sqlite")
# journal_mode='WAL' (v2 FASE 4): con autocommit e journal DELETE ogni write
# creava+cancellava un file journal su flash (costo dominante su eMMC lenta dei
# box ARM). WAL scrive in append su un unico sidecar db.sqlite-wal. Sicuro qui:
# path userdata locale, tutte le connessioni in-process. synchronous=OFF è già
# impostato dalla lib. Rollback: togliere journal_mode (SQLite riconverte da sé).
db = nested_dict_sqlite(lambda table: SqliteDict(db_name, table, 'c', True, journal_mode='WAL'))
