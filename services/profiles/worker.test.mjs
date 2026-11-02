import {DatabaseSync} from 'node:sqlite';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker, {Profile, profileName} from './worker.js';
import {randomUUID} from 'node:crypto';

function profile() {
  const db = new DatabaseSync(':memory:');
  const ctx = {storage: {
    sql: {exec(query, ...args) { const s=db.prepare(query); if (/^SELECT/i.test(query)) return {toArray:()=>s.all(...args)}; s.run(...args); return {toArray:()=>[]}; }},
    transactionSync(fn) {db.exec('BEGIN'); try {const r=fn();db.exec('COMMIT');return r;} catch(e){db.exec('ROLLBACK');throw e;}}
  }};
  return new Profile(ctx);
}
const op = (extra={}) => ({id:'series:tmdb:100', op_id:randomUUID(), deleted:false, modified_at:Date.now()-1000,
  value:{item:{title:'Synthetic', channel:'example', contentType:'episode'}, position_ms:10000,duration_ms:100000}, ...extra});
const post = async (p, operations, create=true) => p.fetch(new Request('https://example.invalid/v1/profiles/test',
  {method:'POST',body:JSON.stringify({schema:1,create,operations})}));

test('profile name normalization is deterministic and validates input',()=>{
  assert.equal(profileName('  MICHELE   TV '), 'michele tv');
  assert.throws(()=>profileName('../bad/name'));
});
test('unknown profiles are not created by reads',async()=>{
  const p=profile(); assert.equal((await (await p.fetch(new Request('https://example.invalid'))).json()).exists,false);
  assert.equal((await post(p,[],false)).status,404);
});
test('two devices update distinct titles without overwriting the profile',async()=>{
  const p=profile(); await post(p,[op()]); const data=await (await post(p,[op({id:'movie:tmdb:2'})])).json();
  assert.equal(data.records.length,2); assert.equal(data.revision,2);
});
test('retry is idempotent',async()=>{
  const p=profile(), operation=op(); await post(p,[operation]); const data=await (await post(p,[operation])).json();
  assert.equal(data.revision,1);assert.equal(data.ignored.length,1);
});
test('creating an already claimed name is rejected atomically',async()=>{
  const p=profile(); await post(p,[op()]);
  const result=await p.fetch(new Request('https://example.invalid', {method:'POST',
    body:JSON.stringify({schema:1,create:true,require_new:true,operations:[]})}));
  assert.equal(result.status,409); assert.equal(p.snapshot().records.length,1);
});
test('offline stale progress cannot overwrite a newer episode or deletion',async()=>{
  const p=profile(), old=op({modified_at:Date.now()-5000}); await post(p,[old]);
  const removed=op({deleted:true, modified_at:Date.now()-1000}); await post(p,[removed]);
  const data=await (await post(p,[{...old,op_id:randomUUID()}])).json();
  assert.equal(data.records[0].deleted,true);
});
test('new explicit watching can restore a removed title',async()=>{
  const p=profile();await post(p,[op({deleted:true,modified_at:Date.now()-5000})]);
  assert.equal((await (await post(p,[op()])).json()).records[0].deleted,false);
});
test('invalid batches are rejected atomically and no credentials are stored',async()=>{
  const p=profile(); const secret=op(); secret.value.item.headers={Cookie:'do-not-store'};
  assert.equal((await post(p,[op(),secret])).status,400);
  assert.equal(p.snapshot().records.length,0);
});
test('future timestamps are rejected rather than pinning profile forever',async()=>{
  assert.equal((await post(profile(),[op({modified_at:Date.now()+3600000})])).status,400);
});
test('there is no list-profiles endpoint',async()=>{
  assert.equal((await worker.fetch(new Request('https://example.invalid/v1/profiles'),{})).status,404);
});
