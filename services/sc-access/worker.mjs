// Credentials are Worker Secrets, never application data or a client response.
const ORIGIN = 'https://streamingunity-premium.to';
const HEADERS = {'content-type':'application/json', 'cache-control':'no-store', 'x-content-type-options':'nosniff'};
const json = (value, status=200) => new Response(JSON.stringify(value), {status, headers:HEADERS});
const unavailable = reason => ({available:false, reason});
export function contentPath(input) {
  if (!input || !/^[1-9][0-9]{0,8}$/.test(String(input.title_id))) throw new Error('invalid_content');
  let path = '/it/iframe/' + input.title_id;
  if (input.episode_id != null && input.episode_id !== '') {
    if (!/^[1-9][0-9]{0,9}$/.test(String(input.episode_id))) throw new Error('invalid_content');
    path += '?episode_id=' + input.episode_id;
  }
  return path;
}
const decodeEntities = value => value.replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&#039;|&#39;/g,"'");
export function authorizedEmbed(body) {
  const match = /<iframe\b[^>]*\bsrc=["']([^"']+)["']/i.exec(body);
  if (!match) return null;
  let url;
  try { url = new URL(decodeEntities(match[1]), ORIGIN); } catch { return null; }
  if (url.protocol !== 'https:' || !/^vixcloud\.[a-z]{2,10}$/.test(url.hostname) ||
      !/^\/embed\/[0-9]+$/.test(url.pathname) || url.username || url.password ||
      url.searchParams.get('canPlayFHD') !== '1' || !url.searchParams.get('token')) return null;
  const expires = Number(url.searchParams.get('expires'));
  if (!Number.isSafeInteger(expires) || expires * 1000 <= Date.now()) return null;
  return url.href;
}
export function mergeCookies(jar, values) {
  const result = {...jar};
  for (const value of values) {
    const first = value.split(';',1)[0];
    const at = first.indexOf('=');
    if (at < 1) continue;
    const name = first.slice(0, at).trim();
    if (!/^[A-Za-z0-9_-]+$/.test(name)) continue;
    if (/;\s*max-age=0(?:;|$)/i.test(value)) delete result[name];
    else result[name] = first.slice(at+1);
  }
  return result;
}
const setCookies = response => response.headers.getSetCookie?.() || response.headers.getAll('Set-Cookie');
async function safeEqual(left, right) {
  if (typeof left !== 'string' || typeof right !== 'string') return false;
  const hash = value => crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  const [a,b] = await Promise.all([hash(left),hash(right)]);
  const aa=new Uint8Array(a), bb=new Uint8Array(b);
  let difference=0;
  for(let i=0;i<aa.length;i++) difference |= aa[i]^bb[i];
  return difference===0;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/health' && request.method === 'GET') return json({ok:true, version:1});
    if (url.pathname !== '/v1/playback' || request.method !== 'POST') return json(unavailable('not_found'),404);
    if (!env.CLIENT_KEY || !env.SC_USERNAME || !env.SC_PASSWORD) return json(unavailable('not_configured'),503);
    if (!await safeEqual(request.headers.get('authorization'), 'Bearer ' + env.CLIENT_KEY))
      return json(unavailable('unauthorized'),401);
    if (Number(request.headers.get('content-length') || 0)>1024) return json(unavailable('invalid_content'),400);
    let raw;
    try {
      const text=await request.text();
      if(text.length>1024) throw new Error();
      raw=JSON.parse(text);
      contentPath(raw);
    } catch { return json(unavailable('invalid_content'),400); }
    // Do not forward arbitrary URLs, cookies, client headers or query parameters.
    const internal = new Request('https://session.internal/resolve', {
      method:'POST', headers:{'content-type':'application/json', 'x-client-ip':request.headers.get('CF-Connecting-IP') || 'unknown'},
      body:JSON.stringify({title_id:String(raw.title_id),episode_id:raw.episode_id ? String(raw.episode_id) : null})
    });
    return env.SESSION.get(env.SESSION.idFromName('shared-authorized-account')).fetch(internal);
  }
};

export class PremiumSession {
  constructor(ctx, env) {
    this.ctx=ctx; this.env=env; this.queue=Promise.resolve(); this.rates=new Map();
  }
  async fetch(request) {
    // Serialize session rotation; do not run overlapping logins.
    const job=this.queue.then(()=>this.resolve(request));
    this.queue=job.catch(()=>{});
    try { return await job; } catch { return json(unavailable('upstream_unavailable')); }
  }
  async fetchPage(path, jar, body=null) {
    const url=new URL(path,ORIGIN);
    if(url.origin!==ORIGIN) throw new Error('invalid_origin');
    const headers={'Accept':'text/html,application/xhtml+xml', 'User-Agent':'PrippiStream/1.0',
      'Referer':ORIGIN+'/login', 'Origin':ORIGIN, 'Cookie':Object.entries(jar).map(([k,v])=>k+'='+v).join('; ')};
    if (body) {
      headers['Content-Type']='application/json'; headers.Accept='application/json';
      headers['X-Requested-With']='XMLHttpRequest';
      if(jar['XSRF-TOKEN']) headers['X-XSRF-TOKEN']=decodeURIComponent(jar['XSRF-TOKEN']);
    }
    const response=await (this.env.UPSTREAM_FETCH || fetch)(url.href, {
      method:body?'POST':'GET',headers,body:body?JSON.stringify(body):undefined,
      redirect:'manual',signal:AbortSignal.timeout(8000)
    });
    const cookies=mergeCookies(jar,setCookies(response));
    const text=await response.text();
    if(text.length>2*1024*1024) throw new Error('oversized_response');
    return {status:response.status,location:response.headers.get('location') || '',cookies,text};
  }
  async login() {
    const last=await this.ctx.storage.get('last_failed_login') || 0;
    if(Date.now()-last<60000) return null;
    const start=await this.fetchPage('/login',{});
    if(start.status!==200 || !start.cookies['XSRF-TOKEN']) {
      await this.ctx.storage.put('login_failure',{stage:'csrf',status:start.status});
      await this.ctx.storage.put('last_failed_login',Date.now());
      return null;
    }
    const result=await this.fetchPage('/login',start.cookies,{
      username:this.env.SC_USERNAME,password:this.env.SC_PASSWORD,remember:true
    });
    if(![200,204,302,303].includes(result.status) || /\/login(?:\?|$)/.test(result.location)) {
      await this.ctx.storage.put('last_failed_login',Date.now());
      let fields=[];
      try {fields=Object.keys(JSON.parse(result.text).errors || {}).filter(k=>/^[a-z_]{1,30}$/.test(k));} catch {}
      await this.ctx.storage.put('login_failure',{stage:'submit',status:result.status,fields});
      return null;
    }
    if(!result.cookies.streamingcommunity_session) return null;
    await this.ctx.storage.put('cookies', result.cookies);
    return result.cookies;
  }
  async resolve(request) {
    const now=Date.now(); const day=new Date(now).toISOString().slice(0,10);
    const ip=request.headers.get('x-client-ip') || 'unknown';
    for(const [key,entry] of this.rates) if(now-entry.start>60000) this.rates.delete(key);
    const rate=this.rates.get(ip) || {start:now,count:0};
    if(++rate.count>30 || this.rates.size>2000) return json(unavailable('rate_limited'),429);
    this.rates.set(ip,rate);
    let quota=await this.ctx.storage.get('quota') || {day,count:0};
    if(quota.day!==day) quota={day,count:0};
    if(++quota.count>5000) return json(unavailable('daily_limit'),429);
    await this.ctx.storage.put('quota',quota);
    const input=await request.json();
    const path=contentPath(input);
    let cookies=await this.ctx.storage.get('cookies');
    if(!cookies) cookies=await this.login();
    if(!cookies) return json(unavailable('login_unavailable'));
    let page=await this.fetchPage(path,cookies);
    if([301,302,303,307,308].includes(page.status) && /\/login(?:\?|$)/.test(page.location)) {
      await this.ctx.storage.delete('cookies');
      cookies=await this.login();
      if(!cookies) return json(unavailable('login_unavailable'));
      page=await this.fetchPage(path,cookies);
    }
    if(page.status!==200) return json(unavailable('upstream_unavailable'));
    await this.ctx.storage.put('cookies',page.cookies);
    const embed=authorizedEmbed(page.text);
    // The server must still grant FHD NOW. Never recycle an old signed embed.
    if(!embed) return json(unavailable('fhd_not_authorized'));
    return json({available:true,embed_url:embed});
  }
}
