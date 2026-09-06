# -*- coding: utf-8 -*-
"""Ponte di test Kodi -> installer Android per la preview TV nativa."""

import hashlib
import os

import xbmc
import xbmcgui

from platformcode import logger

APK_URL = (
    'https://github.com/usandissm/PrippiStream/releases/download/v0.9.13/'
    'PrippiStream-0.9.13-armeabi-v7a.apk'
)
APK_SHA256 = '2d00076d376af89c322eac4d2f70e335e98aea5635e8fcb2a9c1dcde815e303c'
APK_NAME = 'PrippiStream-0.9.13-armeabi-v7a.apk'
DOWNLOAD_DIR = '/storage/emulated/0/Download'


def _remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        logger.exception('[android-app] impossibile rimuovere %s' % path)


def _download(url, destination, show_progress=True):
    from urllib.request import Request, urlopen

    dialog = None
    if show_progress:
        dialog = xbmcgui.DialogProgress()
        dialog.create('PrippiStream', 'Download app Android TV...')
    digest = hashlib.sha256()
    received = 0
    try:
        request = Request(url, headers={'User-Agent': 'PrippiStream-Kodi/1.9.989'})
        with urlopen(request, timeout=20) as response:
            total = int(response.headers.get('Content-Length') or 0)
            with open(destination, 'wb') as output:
                while True:
                    if dialog is not None and dialog.iscanceled():
                        raise RuntimeError('Download annullato')
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    percent = int(received * 100 / total) if total else 0
                    if dialog is not None:
                        dialog.update(
                            min(percent, 100),
                            '%0.1f / %0.1f MB' %
                            (received / 1048576.0, total / 1048576.0 if total else 0),
                        )
    finally:
        if dialog is not None:
            dialog.close()
    return digest.hexdigest()


def install():
    if not xbmc.getCondVisibility('System.Platform.Android'):
        xbmcgui.Dialog().ok(
            'PrippiStream',
            'Questa funzione è disponibile soltanto su Kodi per Android.',
        )
        return

    if not xbmcgui.Dialog().yesno(
        'PrippiStream app Android TV',
        'Scaricare la build ARM32 0.9.13 da GitHub e aprire l’installer Android?',
        nolabel='Annulla',
        yeslabel='Scarica',
    ):
        return

    destination = os.path.join(DOWNLOAD_DIR, APK_NAME)
    try:
        if not os.path.isdir(DOWNLOAD_DIR):
            os.makedirs(DOWNLOAD_DIR)
        _remove(destination)
        actual_hash = _download(APK_URL, destination)
        if actual_hash.lower() != APK_SHA256:
            _remove(destination)
            raise RuntimeError(
                'Verifica SHA-256 fallita: il file scaricato non è quello atteso.'
            )
    except Exception as exc:
        logger.exception('[android-app] download/installazione: %s' % exc)
        xbmcgui.Dialog().ok(
            'PrippiStream',
            'Download non riuscito.\n\n%s\n\n'
            'Controlla che la box sia collegata a Internet.' % exc,
        )
        return

    xbmcgui.Dialog().ok(
        'PrippiStream',
        'APK verificato e salvato in Download.\n\n'
        'Ora seleziona il file nell’installer di sistema e conferma Installa. '
        'Se richiesto, autorizza Kodi o File come sorgente sconosciuta.',
    )
    # È lo stesso percorso adottato dall'add-on ufficiale Kodi Android
    # Installer: DocumentsUI non deve avere un'icona nel launcher per poter
    # aprire il file locale e passarlo al Package Installer.
    xbmc.executebuiltin(
        'StartAndroidActivity(com.android.documentsui,,,"content://%s")' %
        destination
    )


def download_only():
    """Scarica e verifica l'APK senza aprire finestre o Package Installer."""
    if not xbmc.getCondVisibility('System.Platform.Android'):
        return False
    destination = os.path.join(DOWNLOAD_DIR, APK_NAME)
    try:
        if not os.path.isdir(DOWNLOAD_DIR):
            os.makedirs(DOWNLOAD_DIR)
        _remove(destination)
        actual_hash = _download(APK_URL, destination, show_progress=False)
        if actual_hash.lower() != APK_SHA256:
            _remove(destination)
            raise RuntimeError('Verifica SHA-256 fallita')
        logger.info('[android-app] APK verificato disponibile in %s' % destination)
        return True
    except Exception:
        logger.exception('[android-app] download autonomo non riuscito')
        return False
