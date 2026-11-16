const rules = /^[a-z0-9_]{1,128}:(channel|iptv|dedi|mediahosting|freeshot)$/;
const response = (data, status = 200) => Response.json(data, {
  status, headers: {"cache-control": "no-store", "x-content-type-options": "nosniff"},
});

async function authorized(req, secret) {
  if (!secret) return false;
  const input = req.headers.get("authorization") || "";
  if (input.length > 128) return false;
  const bytes = new TextEncoder();
  const hash = value => crypto.subtle.digest("SHA-256", bytes.encode(value));
  const [a, b] = await Promise.all([hash(input), hash("Bearer " + secret)]);
  return crypto.subtle.timingSafeEqual(a, b);
}

export default {
  async fetch(req, env) {
    const path = new URL(req.url).pathname;
    const role = {"/v1/play": "client", "/v1/play/poll": "vm", "/v1/play/reply": "vm"}[path];
    if (role) {
      if (req.method !== (path.endsWith("/poll") ? "GET" : "POST")) return response({}, 405);
      if (!await authorized(req, role === "client" ? env.PLAY_TOKEN : env.WRITER_TOKEN))
        return response({}, 401);
      return env.CATALOG.getByName("play").fetch(req);
    }
    if (path !== "/v1/catalog") return response({}, 404);
    if (!["GET", "PUT"].includes(req.method)) return response({}, 405);
    if (!await authorized(req, req.method === "PUT" ? env.WRITER_TOKEN : env.CLIENT_TOKEN))
      return response({}, 401);
    return env.CATALOG.getByName("live").fetch(req);
  },
};

export function validate(payload) {
  if (!payload || payload.version !== 1 || !payload.rules || Array.isArray(payload.rules) ||
      typeof payload.rules !== "object") return null;
  const pairs = Object.entries(payload.rules);
  if (pairs.length > 5000 || pairs.some(([key, value]) => !rules.test(key) || value !== false))
    return null;
  const channels = payload.channels ?? [];
  if (!Array.isArray(channels) || channels.length > 1500) return null;
  const clean = [];
  for (const row of channels) {
    if (!row || !/^[a-z0-9_]{1,128}$/.test(row.id) ||
        typeof row.title !== "string" || row.title.length > 128 || /https?:|plugin:/i.test(row.title) ||
        !["dedi", "freeshot", "mediahosting", "iptv"].includes(row.route) ||
        !/^[A-Za-z0-9_-]{1,128}$/.test(row.code) ||
        (row.route === "iptv" && row.code !== row.id) || !["sky", "sport"].includes(row.group))
      return null;
    clean.push({id: row.id, title: row.title, route: row.route, code: row.code, group: row.group});
  }
  return {version: 1, rules: Object.fromEntries(pairs), channels: clean};
}

export class LiveCatalog {
  constructor(ctx) {
    this.ctx = ctx;
    this.pending = new Map();
    this.queued = [];
    this.poller = null;
  }
  async play(req, path) {
    if (path === "/v1/play/poll") {
      while (this.queued.length) {
        const job = this.queued.shift();
        if (this.pending.has(job.id)) return response(job);
      }
      if (this.poller) return response({}, 409);
      return new Promise(resolve => {
        const wake = job => {
          clearTimeout(timer);
          this.poller = null;
          resolve(job ? response(job) : new Response(null, {status: 204}));
        };
        const timer = setTimeout(() => wake(null), 20000);
        this.poller = wake;
      });
    }
    if (!Number.isFinite(Number(req.headers.get("content-length"))) ||
        Number(req.headers.get("content-length")) > 8192) return response({}, 413);
    const raw = await req.text();
    if (raw.length > 8192) return response({}, 413);
    let data;
    try { data = JSON.parse(raw); } catch (_) { return response({}, 400); }
    if (!data || typeof data !== "object") return response({}, 400);
    if (path === "/v1/play/reply") {
      const done = this.pending.get(data.id);
      if (!done) return response({}, 410);
      if (data.status === "ok") {
        if (typeof data.url !== "string" || data.url.length > 4096 ||
            !/^https?:\/\/[^\s|\\]+$/.test(data.url) ||
            !/^[0-9a-f]{64}$/.test(data.slot) || !/^[\w-]{32}$/.test(data.lease))
          return response({}, 400);
        done(response({url: data.url, slot: data.slot, lease: data.lease}));
      } else {
        done(response({status: data.status === "not_listed" ? "not_listed" : "unavailable"},
                      data.status === "not_listed" ? 409 : 503));
      }
      return new Response(null, {status: 204});
    }
    const {channel, rejected = [], release = null} = data;
    if (typeof channel !== "string" || !(channel === "-" || /^[a-z0-9_]{1,128}$/.test(channel)) ||
        !Array.isArray(rejected) || rejected.length > 26 ||
        rejected.some(x => typeof x !== "string" || !/^[0-9a-f]{64}$/.test(x)) ||
        (release !== null && (typeof release !== "string" || !/^[\w-]{32}$/.test(release))))
      return response({}, 400);
    if (this.pending.size >= 8) return response({}, 429);
    const id = crypto.randomUUID();
    return new Promise(resolve => {
      this.pending.set(id, result => {
        clearTimeout(timer);
        this.pending.delete(id);
        this.queued = this.queued.filter(x => x.id !== id);
        resolve(result);
      });
      const timer = setTimeout(() => this.pending.get(id)?.(response({}, 504)), 11000);
      const job = {id, channel, rejected, release};
      if (this.poller) this.poller(job);
      else this.queued.push(job);
    });
  }
  async fetch(req) {
    const path = new URL(req.url).pathname;
    if (path.startsWith("/v1/play")) return this.play(req, path);
    if (req.method === "GET") {
      const catalog = await this.ctx.storage.get("catalog");
      return catalog ? response(catalog) : response({}, 404);
    }
    if (Number(req.headers.get("content-length")) > 524288) return response({}, 413);
    const reader = req.body?.getReader();
    if (!reader) return response({}, 400);
    const decoder = new TextDecoder();
    let length = 0, body = "";
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > 524288) { await reader.cancel(); return response({}, 413); }
      body += decoder.decode(value, {stream: true});
    }
    let payload;
    try { payload = validate(JSON.parse(body + decoder.decode())); }
    catch (_) { return response({}, 400); }
    if (!payload) return response({}, 400);
    await this.ctx.storage.put("catalog", {...payload, updated: new Date().toISOString()});
    return response({ok: true});
  }
}
