# Profili Continua a guardare

Servizio Cloudflare Workers + Durable Objects SQLite. Endpoint pubblico del progetto:
`https://prippistream-profiles.prippistream-profiles.workers.dev`.

## Come si usa

Al primo avvio APK e Kodi propongono **Ho già un profilo**, **Crea un profilo** e
**Solo su questo dispositivo**. Si può cambiare successivamente dalle impostazioni.
La creazione richiede un nome libero (controllo atomico sul servizio); l'accesso
richiede un nome già esistente. Maiuscole e spazi ripetuti sono normalizzati.

Un nuovo profilo copia i CW attuali. Il primo accesso da un dispositivo senza
profilo unisce i CW locali e quelli condivisi: titoli diversi conservati, stesso
titolo al punto più avanzato (stagione, episodio, minutaggio). Una rimozione cloud
più recente non viene annullata da una vecchia cronologia locale. Successivamente
la sincronizzazione normale permette anche rewind e rewatch. Cambiare fra due
profili con nome non ne mescola le cronologie. Ogni cronologia precedente resta
conservata sul dispositivo.

**Il nome non è autenticazione.** Per richiesta dell'utente non ci sono password
o codici: chi conosce o indovina un nome può leggere e modificare quel profilo.
Non usare dati personali. Non esiste un endpoint per elencare i profili.

## Sincronizzazione

- APK telefono/TV e Kodi condividono lo stesso protocollo Python (`profile_sync.py`).
- Controllo periodico ogni 20 secondi mentre l'app/addon è aperto; APK controlla
  anche al ritorno al primo piano. Non è un servizio in background a app terminata.
- Identità per film/serie (TMDB quando presente), episodio, posizione e durata.
  Senza identificativo comune si usa titolo/anno: cataloghi con metadati diversi
  possono richiedere un successivo miglioramento di riconciliazione.
- I salvataggi restano locali durante una disconnessione. Outbox persistente,
  eventi datati all'effettiva visione, rimozioni persistenti (tombstone), retry
  idempotenti e confronto dello snapshot prima dell'importazione.
- Per lo stesso titolo prevale l'evento più recente, non il massimo minutaggio:
  sono consentiti rewind e rewatch. Non viene unita automaticamente la visione
  simultanea di episodi diversi dello stesso profilo.
- I file scaricati, credenziali, header, token, link diretti di riproduzione e
  percorsi locali NON vengono condivisi. La ripresa risolve nuovamente la fonte.
- Il cambio profilo è bloccato durante la riproduzione/PiP.

## Gestione e limiti

Account Cloudflare del proprietario. Configurazione OAuth Wrangler fuori dal repo.
Non inserire token/API key nel codice o nelle app. Usare `npx wrangler deploy`
da questa cartella dopo il login del proprietario. Nessuna chiave Cloudflare
distribuita ai client.

Questa configurazione usa risorse compatibili con il piano gratuito, non un
server personale. Restano applicabili i limiti dell'account Cloudflare; non è una
garanzia di disponibilità illimitata. Limiti applicativi per profilo: 1.000 record
(incluse rimozioni), 120 richieste/minuto per istanza, 256 KiB per invio, 12 KiB per
record. I tombstone sono conservati per non far ricomparire progressi obsoleti.
Non è previsto un sistema di recupero account/autorizzazione: prima di un uso
pubblico più ampio occorre aggiungere autenticazione e difese anti-abuso.

## Test

`node --test worker.test.mjs` verifica storage e protocollo con SQLite reale.
Da Kodi: `python tools/test_profile_sync.py` verifica adattatori, conflitti,
offline e conservazione dei CW. Aggiungere `--live` per un roundtrip online
esclusivamente con dati sintetici e un nome QA casuale, mai con i CW dell'utente.
