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

const deviceToken = /^[A-Za-z0-9_-]{43}$/;
const deviceId = /^[a-f0-9]{64}$/;
const devicePaths = {
  "/v1/devices/request": "POST", "/v1/devices/status": "GET",
  "/v1/devices": "GET", "/v1/devices/decision": "POST",
};
const pendingMs = 15 * 60 * 1000;
const deviceBearer = req => {
  const auth = req.headers.get("authorization") || "";
  return auth.startsWith("Bearer ") && deviceToken.test(auth.slice(7)) ? auth.slice(7) : null;
};
async function deviceKey(token) {
  const hash = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token)));
  return Array.from(hash, n => n.toString(16).padStart(2, "0")).join("");
}

async function deviceAuthorized(req, env) {
  const token = deviceBearer(req);
  if (!token) return false;
  const r = await env.CATALOG.getByName("devices").fetch("https://internal/v1/devices/check", {
    headers: {authorization: "Bearer " + token},
  });
  return r.ok;
}

export default {
  async fetch(req, env) {
    const path = new URL(req.url).pathname;
    if (Object.hasOwn(devicePaths, path)) {
      if (req.method !== devicePaths[path]) return response({}, 405);
      const admin = path === "/v1/devices" || path === "/v1/devices/decision";
      if (admin ? !await authorized(req, env.WRITER_TOKEN) : !deviceBearer(req))
        return response({}, 401);
      return env.CATALOG.getByName("devices").fetch(req);
    }
    const role = {"/v1/play": "client", "/v1/play/poll": "vm", "/v1/play/reply": "vm"}[path];
    if (role) {
      if (req.method !== (path.endsWith("/poll") ? "GET" : "POST")) return response({}, 405);
      if (!await authorized(req, role === "client" ? env.PLAY_TOKEN : env.WRITER_TOKEN) &&
          !(role === "client" && await deviceAuthorized(req, env)))
        return response({}, 401);
      return env.CATALOG.getByName("play").fetch(req);
    }
    if (path !== "/v1/catalog") return response({}, 404);
    if (!["GET", "PUT"].includes(req.method)) return response({}, 405);
    if (!await authorized(req, req.method === "PUT" ? env.WRITER_TOKEN : env.CLIENT_TOKEN) &&
        !(req.method === "GET" && await deviceAuthorized(req, env)))
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
  async devices(req, path) {
    const now = Date.now();
    const store = this.ctx.storage;
    const adminList = path === "/v1/devices";
    const decision = path === "/v1/devices/decision";
    const token = adminList || decision ? null : deviceBearer(req);
    if (!adminList && !decision && !token) return response({}, 401);
    const id = token ? await deviceKey(token) : null;
    const publicRecord = (id, value) => ({id, label: value.label, state: value.state, at: value.at});
    if (path === "/v1/devices/check" || path === "/v1/devices/status") {
      const value = await store.get("device:" + id);
      const state = !value || (value.state === "pending" && now - value.at >= pendingMs)
        ? "not_requested" : value.state;
      return path.endsWith("/check") ? response({}, state === "approved" ? 200 : 401)
        : response({state, hint: id.slice(-6).toUpperCase()});
    }
    if (adminList) {
      const rows = await store.list({prefix:"device:"});
      return response({devices:[...rows].filter(([,v]) => v.state !== "pending" || now - v.at < pendingMs)
        .map(([k,v]) => publicRecord(k.slice(7), v))});
    }
    const reader = req.body?.getReader();
    if (!reader) return response({}, 400);
    if (Number(req.headers.get("content-length")) > 1024) return response({}, 413);
    const decoder = new TextDecoder();
    let size = 0, raw = "";
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      if ((size += value.byteLength) > 1024) { await reader.cancel(); return response({}, 413); }
      raw += decoder.decode(value, {stream:true});
    }
    let data;
    try { data = JSON.parse(raw + decoder.decode()); } catch (_) { return response({}, 400); }
    if (!data || typeof data !== "object") return response({}, 400);
    if (decision) {
      if (typeof data.id !== "string" || !deviceId.test(data.id) ||
          !["approve", "revoke"].includes(data.action)) return response({}, 400);
      const key = "device:" + data.id;
      return store.transaction(async tx => {
        const value = await tx.get(key);
        if (!value || (data.action === "approve" && (value.state !== "pending" || now - value.at >= pendingMs)))
          return response({}, 409);
        await tx.put(key, {...value, state:data.action === "approve" ? "approved" : "revoked",
          ...(data.action === "revoke" ? {revokedAt:now} : {})});
        return response({ok:true});
      });
    }
    if (typeof data.label !== "string" || !/^[\p{L}\p{N} ._()-]{1,60}$/u.test(data.label))
      return response({}, 400);
    const source = await deviceKey("pairing-source:" + (req.headers.get("cf-connecting-ip") || "unknown"));
    return store.transaction(async tx => {
      const key = "device:" + id;
      const rows = await tx.list({prefix:"device:"});
      const existing = rows.get(key);
      if (existing && (existing.state !== "pending" || now - existing.at < pendingMs))
        return response({state:existing.state, hint:id.slice(-6).toUpperCase()});
      let pending = 0, retained = 0, pendingFromSource = 0;
      const expired = [];
      for (const [k,v] of rows) {
        if ((v.state === "pending" && now - v.at >= pendingMs) ||
            (v.state === "revoked" && now - (v.revokedAt ?? v.at) >= 30 * 86400000)) expired.push(k);
        else {
          retained++;
          if (v.state === "pending") {
            pending++;
            if (v.source === source) pendingFromSource++;
          }
        }
      }
      for (let i = 0; i < expired.length; i += 64) await tx.delete(expired.slice(i,i+64));
      if (pending >= 20 || pendingFromSource >= 3 || retained >= 100) return response({}, 429);
      await tx.put(key, {label:data.label, state:"pending", at:now, source});
      return response({state:"pending", hint:id.slice(-6).toUpperCase()});
    });
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
    if (path.startsWith("/v1/devices")) return this.devices(req, path);
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
