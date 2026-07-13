# -*- coding: utf-8 -*-
# Ambiente/percorsi per gli shim xbmc*. Impostati una volta all'avvio dal bridge
# (o dal test PC). RUNTIME_DIR = cartella del motore (dove stanno channels.json,
# resources/, i channels/*.py). DATA_DIR = storage scrivibile per settings/cache.
import os
import tempfile

RUNTIME_DIR = os.environ.get('PRIPPI_RUNTIME', '')
DATA_DIR = os.environ.get('PRIPPI_DATA', '')
TEMP_DIR = os.environ.get('PRIPPI_TEMP', '')


def init(runtime_dir, data_dir, temp_dir=None):
    """Configura i percorsi. Da chiamare PRIMA di importare il motore."""
    global RUNTIME_DIR, DATA_DIR, TEMP_DIR
    RUNTIME_DIR = os.path.abspath(runtime_dir)
    DATA_DIR = os.path.abspath(data_dir)
    TEMP_DIR = os.path.abspath(temp_dir) if temp_dir else os.path.join(DATA_DIR, 'temp')
    for d in (DATA_DIR, TEMP_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass


def _ensure():
    """Fallback se init() non è stato chiamato (usa una temp dir)."""
    global RUNTIME_DIR, DATA_DIR, TEMP_DIR
    if not DATA_DIR:
        DATA_DIR = os.path.join(tempfile.gettempdir(), 'prippi_app_data')
        os.makedirs(DATA_DIR, exist_ok=True)
    if not TEMP_DIR:
        TEMP_DIR = os.path.join(DATA_DIR, 'temp')
        os.makedirs(TEMP_DIR, exist_ok=True)
    if not RUNTIME_DIR:
        # engine è sibling di xbmc_shim: .../python/engine
        RUNTIME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'engine')
