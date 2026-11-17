import {test} from 'node:test';
import assert from 'node:assert/strict';
import {timingSafeEqual} from 'node:crypto';
import worker, {LiveCatalog} from './worker.mjs';

crypto.subtle.timingSafeEqual ??= (a,b) => timingSafeEqual(Buffer.from(a),Buffer.from(b));

function fixture() {
  const devices = new Map();
  const storage = {
    get: async key => devices.get(key),
    put: async (key,value) => devices.set(key,value),
    list: async () => new Map(devices),
    delete: async keys => keys.forEach(key => devices.delete(key)),
    transaction: async fn => fn(storage),
  };
  const pair = new LiveCatalog({storage});
  const env = {WRITER_TOKEN:'W'.repeat(43), CLIENT_TOKEN:'C'.repeat(43), PLAY_TOKEN:'P'.repeat(43),
    CATALOG:{getByName(name) {
      return {fetch(req, options) {
        if (name === 'devices') return pair.fetch(typeof req === 'string' ? new Request(req,options) : req);
        return Response.json({name});
      }};
    }}};
  const call = (path, token, data, method = data ? 'POST' : 'GET') => worker.fetch(
    new Request('https://example.test' + path, {
      method, headers:{authorization:'Bearer ' + token}, body:data ? JSON.stringify(data) : undefined
    }), env);
  return {call, env, devices};
}
const req = '/v1/devices/request';
const status = '/v1/devices/status';
const admin = '/v1/devices';
const decision = '/v1/devices/decision';
const catalog = '/v1/catalog';
const play = '/v1/play';

test('device cannot access playback or catalog until owner approval; revoke is immediate', async () => {
  const {call, env, devices} = fixture();
  const a = 'A'.repeat(43), b = 'B'.repeat(43);
  assert.equal((await call(req,a,{label:'Samsung Tablet'})).status,200);
  assert.equal((await (await call(status,a)).json()).state,'pending');
  assert.equal((await (await call(status,b)).json()).state,'not_requested');
  assert.equal((await call(catalog,a)).status,401);
  assert.equal((await call(play,a,{})).status,401);
  assert.equal((await call(admin,a)).status,401);
  const [record] = (await (await call(admin,env.WRITER_TOKEN)).json()).devices;
  assert.equal(record.label,'Samsung Tablet');
  assert.ok(!JSON.stringify([...devices]).includes(a));
  assert.equal((await call(decision,b,{id:record.id,action:'approve'})).status,401);
  assert.equal((await call(decision,env.WRITER_TOKEN,{id:record.id,action:'approve'})).status,200);
  assert.equal((await call(catalog,a)).status,200);
  assert.equal((await call(catalog,b)).status,401);
  assert.equal((await call(play,a,{})).status,200);
  assert.equal((await call('/v1/play/poll',a)).status,401);
  assert.equal((await call(catalog,a,{},'PUT')).status,401);
  assert.equal((await call(decision,env.WRITER_TOKEN,{id:record.id,action:'revoke'})).status,200);
  assert.equal((await call(catalog,a)).status,401);
  assert.equal((await call(play,a,{})).status,401);
  assert.equal((await (await call(req,a,{label:'Samsung Tablet'})).json()).state,'revoked');
  assert.equal((await call(catalog,env.CLIENT_TOKEN)).status,200);
  assert.equal((await call(play,env.PLAY_TOKEN,{})).status,200);
});
test('internal lookups cannot be called by external clients and enrollment is rate limited', async () => {
  const {call} = fixture();
  for (const c of 'ABC') assert.equal((await call(req,c.repeat(43),{label:'Tablet'})).status,200);
  assert.equal((await call(req,'D'.repeat(43),{label:'Tablet'})).status,429);
  assert.equal((await call('/v1/devices/check','A'.repeat(43))).status,404);
  assert.equal((await call(req,'E'.repeat(43),{label:'https://example.test'})).status,400);
});
