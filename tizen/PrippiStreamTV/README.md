# PrippiStream TV

Applicazione Samsung Tizen per la TV `QE55Q60AAUXZT`.

La UI Web TV usa focus D-pad, firma Samsung, pacchetto `.wgt` e player nativo
AVPlay. Il pacchetto `0.3.0` contiene inoltre il bootstrap OTA: all'avvio
controlla il canale GitHub, verifica gli SHA-256, conserva l'ultima versione
valida in cache e usa il bundle locale se la rete o il canale non rispondono.

## Runtime standalone

Il runtime Tizen non usa un server PrippiStream, il PC o il vecchio gateway
locale. `standalone.js` interroga direttamente i provider pubblici e conserva
in locale host e Home già validati. La modalità attuale copre:

- Home, ricerca, dettaglio, episodi e riproduzione StreamingCommunity;
- metadati TMDB;
- catalogo Live TV incorporato e resolver diretti Rai, Mediaset e La7;
- catalogo Discovery, la cui riproduzione Widevine resta da completare;
- nessun fallback HTTP alla porta del PC.

La connessione Internet rimane necessaria per cataloghi e flussi video: per
"senza server" si intende senza backend PrippiStream dedicato. Sky/Sport usa
attualmente ClearKey, non supportato da AVPlay sui TV Samsung.

Il catalogo Live e i loghi condivisi con Android si rigenerano con:

```powershell
python tools\export_tizen_live_catalog.py
```

## Aggiornamenti OTA

1. Modificare `index.html`, `css/style.css`, `standalone.js` o `main.js`.
2. Incrementare `version` e `revision` in `ota-version.json`.
3. Eseguire `python tools/publish_tizen_ota.py` dalla root per una prova locale.
4. Pubblicare su `main`: il workflow `Publish Tizen OTA` aggiorna
   `docs/tizen/app` automaticamente.

Il TV scarica il nuovo bundle al successivo avvio senza reinstallare il WGT.
Una nuova installazione resta necessaria solo quando cambiano `config.xml`,
permessi Tizen, bootstrap o asset locali del guscio.

## Build e deploy

```powershell
& 'C:\tizen-studio\tools\ide\bin\tizen.bat' build-web -- .
& 'C:\tizen-studio\tools\ide\bin\tizen.bat' package -t wgt -s MS -- .buildResult
& 'C:\tizen-studio\tools\ide\bin\tizen.bat' install -n PrippiStreamTV.wgt -s 192.168.1.117:26101 -- .buildResult
```
