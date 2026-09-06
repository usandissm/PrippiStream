# PrippiStream TV

Applicazione Samsung Tizen per la TV `QE55Q60AAUXZT`.

La UI Web TV usa focus D-pad, firma Samsung, pacchetto `.wgt` e player nativo
AVPlay. Il pacchetto `0.7.0` contiene inoltre il bootstrap OTA: all'avvio
controlla il canale GitHub, verifica gli SHA-256, conserva l'ultima versione
valida in cache e usa il bundle locale se la rete o il canale non rispondono.

## Runtime standalone

Il runtime Tizen non usa un server PrippiStream, il PC o il vecchio gateway
locale. `standalone.js` interroga direttamente i provider pubblici e conserva
in locale host e Home già validati. La modalità attuale copre:

- Home completa della 2.0: righe StreamingCommunity generali/Film/Serie TV,
  archivi curati, generi e AnimeUnity, caricati progressivamente;
- ricerca globale aggregata e deduplicata su StreamingCommunity, HD4Me,
  AnimeUnity, Cineblog01, StreamingITA, RaiPlay, Mediaset Infinity e La7;
- dettaglio, stagioni, episodi e riproduzione StreamingCommunity;
- metadati TMDB e catalogo TMDB di riserva quando la sorgente primaria è lenta
  o temporaneamente irraggiungibile;
- cataloghi on-demand ufficiali RaiPlay, Mediaset Infinity e La7;
- pagina Live separata dalla Home con le righe TV, SKY e Sport Live, catalogo
  incorporato, 97 loghi locali e resolver TV/ClearKey/Freeshot/IPTV/Daddy;
- fallback Daddy associato ai canali TV/SKY/Sport compatibili e canali Daddy
  autonomi (Sky Cinema Uno +24, Eurosport 1/2 e Rai Sport);
- EPG SKY/Sport caricato in background dall'API ufficiale Sky, con programma
  corrente, orario, sinossi e programma successivo;
- ricerca Mediaset GraphQL allineata alla 2.0, con fallback sulle pagine
  ufficiali e lettura episodi dalle pagine moderne/WittyTV;
- catalogo Discovery, la cui riproduzione Widevine resta da completare;
- nessun fallback HTTP alla porta del PC.

La connessione Internet rimane necessaria per cataloghi e flussi video: per
"senza server" si intende senza backend PrippiStream dedicato. Sky/Sport usa
ClearKey tramite DASH, Shaka, MSE ed EME `org.w3.clearkey`: il test definitivo
resta sulla TV Samsung reale. L'emulatore viene fermato prima di creare la
sessione DRM perchÃ© il suo processo termina anche quando manifest, chiave ed EME
risultano supportati.

## Baseline UI/UX 0.7.0

La baseline TV validata nell'emulatore Tizen 10 è progettata a 1920×1080 e
ridimensionata dal runtime Samsung. Comprende:

- rail laterale con focus unico e prevedibile, Impostazioni ancorate in basso;
- logo banner grande e centrato soltanto nell'app, mai sovrapposto al video;
- Hero fisso durante lo scorrimento delle righe e aggiornato dal focus;
- card poster in proporzione, card Live orizzontali con logo `contain` e griglia
  Sfoglia/Ricerca a cinque colonne;
- dettagli fullscreen per film, serie e dirette, episodi scorrevoli e stati
  loading/errore leggibili a distanza;
- player fullscreen con titolo, timeline, comandi focalizzabili, auto-hide,
  Return e distinzione VOD/Live;
- cache Home, rendering progressivo e fallback TMDB per non lasciare una
  schermata vuota quando StreamingCommunity cambia dominio;
- Continue Watching locale (massimo 30 contenuti) con avanzamento, ripresa e
  rimozione; i live sono sempre esclusi;
- per le serie, proposta dell'episodio successivo nell'ultimo minuto con
  `Guarda subito`/`Annulla` e autoplay naturale a fine episodio.

Audit reale completato su Home, Cerca, Sfoglia, Live, Download, Impostazioni,
dettaglio film/serie/live, episodi e player. Nell'emulatore il flusso Rai 1
corrente restituisce `PLAYER_ERROR_NOT_SUPPORTED_FORMAT` anche dopo il fallback
AVPlay → video HTML: è un limite sorgente/codec da verificare sul TV reale, non
un errore di geometria del player. Sky/Sport resta da validare sulla TV reale
per ClearKey e per i fallback Daddy.

Il player Live conserva la riga corrente e intercetta Channel+/âˆ’ soltanto
durante una diretta: applica debounce, impedisce cambi concorrenti, salta le
sorgenti non risolvibili e ricomincia dall'inizio alla fine della riga. Film ed
episodi continuano a usare i tasti di seek e la timeline normale.

La revisione 12 pubblica ogni nuova riga Home appena pronta, fino alle 30 righe
StreamingCommunity previste dalla 2.0, senza aspettare insieme archivi, anime e
cataloghi ufficiali. Corregge inoltre i titoli episodio e aggiunge Continue
Watching e passaggio all'episodio successivo. Include inoltre le protezioni per
provider ufficiali, cambio dominio SC, timer autoplay e quota dello storage. La build è verificabile senza
aprire o controllare l'emulatore.

Sugli emulatori x86 gli HLS SC/VixCloud vengono riprodotti con HLS.js Light e
Media Source Extensions. La libreria è inclusa nel WGT, non richiede CDN ed
esclude sottotitoli/audio alternativi che provocano il `SIGABRT` interno di
AVPlay/PlusPlayer. Il fallback AVPlay resta attivo sui televisori reali.

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
