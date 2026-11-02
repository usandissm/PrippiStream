// Name-only profiles, explicitly requested by the owner. No list/search endpoint.
// Anyone knowing a profile name can read/write it: this is not authentication.
const MAX_BODY = 256 * 1024;
const MAX_RECORD_BYTES = 12 * 1024;
const encoder = new TextEncoder();

export function profileName(value) {
  const name = String(value || '').normalize('NFKC').trim().replace(/\s+/gu, ' ').toLowerCase();
  if (name.length < 2 || name.length > 40 || !/^[\p{L}\p{N} ._-]+$/u.test(name)) throw Error('invalid_profile');
  return name;
}

function json(value, status = 200) {
  return new Response(JSON.stringify(value), {status, headers: {
    'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  }});
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/health' && request.method === 'GET') return json({service: 'prippistream-profiles', schema: 1});
    const match = /^\/v1\/profiles\/([^/]+)$/.exec(url.pathname);
    if (!match || !['GET', 'POST'].includes(request.method)) return json({error: 'not_found'}, 404);
    let name;
    try { name = profileName(decodeURIComponent(match[1])); } catch { return json({error: 'invalid_profile'}, 400); }
    if (!env.PROFILES) return json({error: 'not_configured'}, 503);
    const id = env.PROFILES.idFromName(name);
    return env.PROFILES.get(id).fetch(request);
  },
};

function validateOperation(op, now) {
  if (!op || !/^(movie|series):[a-z0-9:_-]{1,180}$/.test(op.id || '') ||
      !/^[a-f0-9-]{36}$/.test(op.op_id || '') || typeof op.deleted !== 'boolean' ||
      !Number.isSafeInteger(op.modified_at) || op.modified_at < 0 || op.modified_at > now + 120000) throw Error('invalid_operation');
  if (!op.deleted) {
    const value = op.value;
    if (!value || typeof value !== 'object' || Array.isArray(value) || !value.item ||
        !Number.isSafeInteger(value.position_ms) || value.position_ms < 0 ||
        !Number.isSafeInteger(value.duration_ms) || value.duration_ms < 0 ||
        value.position_ms > 30 * 24 * 3600000 || value.duration_ms > 30 * 24 * 3600000 ||
        encoder.encode(JSON.stringify(value)).length > MAX_RECORD_BYTES) throw Error('invalid_record');
    // Only a launchable metadata Item, never credentials, local paths or media URLs.
    const inspect = (v, depth = 0) => {
      if (depth > 12) throw Error('invalid_record');
      if (typeof v === 'string') {
        if (/^(?:file:|content:|special:|[a-z]:\\|https?:\/\/(?:localhost|127\.0\.0\.1)(?::|\/))/i.test(v)) throw Error('local_path');
        if (/https?:\/\/\S+\.(?:m3u8|mpd)(?:[?#|]|$)/i.test(v)) throw Error('media_url');
      } else if (v && typeof v === 'object') {
        for (const [key, child] of Object.entries(v)) {
          if (/cookie|authorization|license|password|token|headers|_app_media|_app_episode_queue|_app_offline_download_key/i.test(key)) throw Error('private_field');
          inspect(child, depth + 1);
        }
      }
    };
    inspect(value);
  }
}

export class Profile {
  constructor(ctx) {
    this.ctx = ctx;
    this.sql = ctx.storage.sql;
    this.sql.exec('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)');
    this.sql.exec('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, payload TEXT, deleted INTEGER NOT NULL, modified INTEGER NOT NULL, revision INTEGER NOT NULL, operation TEXT NOT NULL)');
    this.requests = [];
  }
  snapshot() {
    const meta = this.sql.exec("SELECT value FROM meta WHERE key='revision'").toArray();
    return {schema: 1, exists: meta.length > 0, revision: meta[0]?.value || 0, server_time: Date.now(),
      records: this.sql.exec('SELECT * FROM records ORDER BY modified DESC').toArray().map(row => ({
        id: row.id, deleted: Boolean(row.deleted), modified_at: row.modified, version: row.revision,
        op_id: row.operation, value: row.payload ? JSON.parse(row.payload) : null,
      }))};
  }
  async fetch(request) {
    const now = Date.now();
    this.requests = this.requests.filter(t => t > now - 60000);
    if (this.requests.length >= 120) return json({error: 'rate_limited'}, 429);
    this.requests.push(now);
    if (request.method === 'GET') return json(this.snapshot());
    if (Number(request.headers.get('content-length') || 0) > MAX_BODY) return json({error: 'too_large'}, 413);
    let body;
    try {
      const bytes = await request.arrayBuffer();
      if (bytes.byteLength > MAX_BODY) return json({error: 'too_large'}, 413);
      body = JSON.parse(new TextDecoder().decode(bytes));
      if (body.schema !== 1 || !Array.isArray(body.operations) || body.operations.length > 100) throw Error('invalid_batch');
      body.operations.forEach(op => validateOperation(op, now));
    } catch (error) { return json({error: String(error.message || 'invalid_json')}, 400); }
    let response;
    try {
      this.ctx.storage.transactionSync(() => {
        const before = this.snapshot();
        if (body.require_new === true && before.exists) { response = json({error: 'profile_exists'}, 409); return; }
        if (!before.exists && body.create !== true) { response = json({error: 'profile_missing'}, 404); return; }
        if (!before.exists) this.sql.exec("INSERT INTO meta VALUES ('revision', 0)");
        const count = this.sql.exec('SELECT COUNT(*) AS n FROM records').toArray()[0].n;
        const newIds = new Set(body.operations.filter(op => !before.records.some(r => r.id === op.id)).map(op => op.id));
        if (count + newIds.size > 1000) { response = json({error: 'profile_full'}, 409); return; }
        let revision = before.revision;
        const accepted = [], ignored = [];
        for (const op of body.operations) {
          const old = this.sql.exec('SELECT * FROM records WHERE id=?', op.id).toArray()[0];
          // Offline events keep their original event time, not the reconnection time.
          // Equal-time removals win; stale/retried snapshots cannot resurrect CW.
          if (old && (old.operation === op.op_id || op.modified_at < old.modified ||
              (op.modified_at === old.modified && (old.deleted > Number(op.deleted) ||
               (old.deleted === Number(op.deleted) && op.op_id <= old.operation))))) {
            ignored.push(op.op_id); continue;
          }
          revision++;
          this.sql.exec('INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?, ?, ?)',
            op.id, op.deleted ? null : JSON.stringify(op.value), Number(op.deleted), op.modified_at, revision, op.op_id);
          accepted.push(op.op_id);
        }
        this.sql.exec("UPDATE meta SET value=? WHERE key='revision'", revision);
        response = json({...this.snapshot(), accepted, ignored});
      });
    } catch { return json({error: 'storage_error'}, 503); }
    return response;
  }
}
