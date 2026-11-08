import {test} from 'node:test';
import assert from 'node:assert/strict';
import worker, {contentPath, authorizedEmbed, mergeCookies, PremiumSession} from './worker.mjs';

const embed = () => 'https://vixcloud.co/embed/12?canPlayFHD=1&token=authorized&expires=' + Math.floor(Date.now()/1000+600);
test('only content identifiers, no arbitrary upstream URLs', () => {
  assert.equal(contentPath({title_id:12,episode_id:23}),'/it/iframe/12?episode_id=23');
  for (const title_id of ['https://example.org', '../12', 0, '12?admin=1']) assert.throws(()=>contentPath({title_id}));
});
test('accept fresh upstream FHD grants only', () => {
  assert.equal(authorizedEmbed(`<iframe src="${embed().replaceAll('&','&amp;')}"></iframe>`),embed());
  for(const url of [embed().replace('canPlayFHD=1','canPlayFHD=0'),embed().replace('vixcloud.co','evil.org'),embed().replace(/expires=\d+/,'expires=1')])
    assert.equal(authorizedEmbed(`<iframe src="${url}"></iframe>`),null);
});
test('cookie rotation and expiry', () => {
  assert.deepEqual(mergeCookies({old:'x'},['old=; Max-Age=0','session=new; Secure; HttpOnly']),{session:'new'});
});
test('health does not contact upstream; playback is authenticated', async () => {
  assert.equal((await worker.fetch(new Request('https://local/health'),{})).status,200);
  const response=await worker.fetch(new Request('https://local/v1/playback',{method:'POST'}),{CLIENT_KEY:'k',SC_USERNAME:'u',SC_PASSWORD:'p'});
  assert.equal(response.status,401);
});
function fixture(responses) {
  const data=new Map(); const calls=[];
  const instance=new PremiumSession({storage:{get:async k=>data.get(k),put:async(k,v)=>data.set(k,v),delete:async k=>data.delete(k)}},{SC_USERNAME:'u',SC_PASSWORD:'p',UPSTREAM_FETCH:async(url,options)=>{
    calls.push({url,options}); const next=responses.shift(); assert.ok(next,'unexpected extra upstream request'); return next;
  }});
  const request=()=>new Request('https://local/resolve',{method:'POST',body:JSON.stringify({title_id:12}),headers:{'x-client-ip':'local'}});
  return {instance,data,calls,request};
}
const loginPage=()=>new Response('login',{headers:{'Set-Cookie':'XSRF-TOKEN=csrf; Secure'}});
const loginOk=()=>new Response(null,{status:302,headers:{Location:'/it','Set-Cookie':'streamingcommunity_session=session; HttpOnly'}});
test('login then fresh grant on EVERY playback, expiry falls back',async()=>{
  const f=fixture([loginPage(),loginOk(),new Response(`<iframe src="${embed()}"></iframe>`),new Response('no longer authorized')]);
  assert.equal((await (await f.instance.fetch(f.request())).json()).available,true);
  assert.deepEqual(await (await f.instance.fetch(f.request())).json(),{available:false,reason:'fhd_not_authorized'});
  assert.equal(f.calls.length,4);
  assert.equal(f.calls[1].options.headers['X-XSRF-TOKEN'],'csrf');
});
test('expired session reauthenticates once; no infinite retry',async()=>{
  const f=fixture([new Response(null,{status:302,headers:{Location:'/login'}}),loginPage(),loginOk(),new Response(`<iframe src="${embed()}"></iframe>`)]);
  f.data.set('cookies',{streamingcommunity_session:'expired'});
  assert.equal((await (await f.instance.fetch(f.request())).json()).available,true);
  assert.equal(f.calls.length,4);
});
test('failed login is cooled down and secrets never returned',async()=>{
  const f=fixture([loginPage(),new Response('sensitive upstream error',{status:422})]);
  const result=await (await f.instance.fetch(f.request())).text();
  assert.equal(JSON.parse(result).available,false);
  assert.equal(result.includes('sensitive'),false);
  assert.equal((await (await f.instance.fetch(f.request())).json()).available,false);
  assert.equal(f.calls.length,2);
});
