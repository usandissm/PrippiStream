# Authorized SC playback access

Separate from the CW profile service. The shared subscription must permit the
intended users. This integration never extends an entitlement beyond what the
upstream service currently grants.

## Deployment

Use Wrangler 4.156.0 from this directory. Configure `SC_USERNAME`, `SC_PASSWORD`
and a random `CLIENT_KEY` using Worker Secrets (`wrangler secret bulk` via stdin).
Do not put their values in this repository, Wrangler vars or an APK.

The account credentials and session cookies stay in Cloudflare Secrets / the
Durable Object. Each playback requests a NEW authorized iframe from the official
account session. An expired login is renewed once; a rejected login is cooled
down. The service returns only the freshly signed playback embed, not account
cookies. No previous signed source is reused after expiration/revocation.

Limits: 30 requests/minute/IP and 5,000 playback requests/day overall. Logging
is disabled. All requests are restricted to numeric content IDs; the API cannot
fetch arbitrary URLs or perform account changes. GET `/health` does not contact
the upstream site. POST `/v1/playback` requires the client bearer key.

## Android

Deployment configuration is read from
`../../../Riservato/Android/premium-client.properties` (outside both repositories),
or `PRIPPI_SC_ACCESS_ENDPOINT` / `PRIPPI_SC_ACCESS_CLIENT_KEY` at build time.
The properties are `endpoint` and `clientKey`. Missing configuration leaves the
existing public playback unchanged. There are no login screens or Premium labels.

The client key is a LIMITED, revocable playback API key; it can be extracted
from an APK and is NOT a safe place for the account password. Never substitute
the account credentials for this key. Removing or rotating the Worker key
disables this path; installed clients transparently return to public playback.

Signed URLs stay in the player request, not in CW metadata or profile storage.
The public fallback is resolved lazily to avoid using an already-stale URL.
Quality preferences remain in force: a user-selected 720p cap is not overridden.
Android resolves authorization only when the player actually starts (not while
the user is choosing quality or another source plays). New SC downloads can use
the authorized 1080p variant. Only NEW download entries opt into this resolver;
existing files/partials retain their old source and resume contract. Queue delay
and expired tokens trigger fresh authorization. Each new download locks its
actual rendition height: if that height disappears, the partial is retained and
the job reports an error instead of appending incompatible 720p data to 1080p.

## Checks

`node --test worker.test.mjs`

Live integration checked on 2026-11-08: normal CSRF login requires `username`,
not `email`; server-issued FHD iframe accepted from a different network client;
episode master returned HTTP 200 with 1920x1080, 1280x720 and 854x480 variants.
This verifies source availability, not playback on every Android device.
No download of a complete film/episode was performed for these checks.
