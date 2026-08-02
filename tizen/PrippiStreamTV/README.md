# PrippiStream TV

Applicazione Samsung Tizen per la TV `QE55Q60AAUXZT`.

La UI Web TV usa focus D-pad, firma Samsung, pacchetto `.wgt` e player nativo
AVPlay. Il pacchetto `0.3.0` contiene inoltre il bootstrap OTA: all'avvio
controlla il canale GitHub, verifica gli SHA-256, conserva l'ultima versione
valida in cache e usa il bundle locale se la rete o il canale non rispondono.

## Aggiornamenti OTA

1. Modificare `index.html`, `css/style.css` o `main.js`.
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
