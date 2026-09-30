/* The whole site at elkitep.com, as one Cloudflare Worker:
 * - the reader app and book texts (site/ without the pictures) are static assets, served by Cloudflare
 *   before this code runs (see wrangler.toml and tools/build_cloudflare.sh);
 * - book pictures (site/books/<id>/img/) live in the R2 bucket BOOKS, because the free plan allows
 *   20,000 asset files and the pictures alone are more;
 * - /api/...: text-error reports and books that readers upload, in a D1 database (SQLite) and the R2 bucket FILES.
 * Readers need no account. The admin page (/api/admin) and the admin API need the ADMIN_KEY secret. See README.md. */

const SITES = ['https://elkitep.com', 'https://www.elkitep.com', 'https://rinatius.github.io', 'http://localhost:8080', 'http://localhost:8787'];
const MAX_FILE = 500 * 1048576, MAX_FILES = 40;
const LIMITS = { reports: 60, uploads: 10 }; // per reader (hashed IP) per hour
const TYPES = { webp: 'image/webp', svg: 'image/svg+xml', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg' };

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const img = url.pathname.match(/^\/books\/([\w.-]+)\/img\/([\w.-]+)$/);
    if (img) return picture(req, env, img[1] + '/img/' + img[2]);
    if (!/^\/api(\/|$)/.test(url.pathname)) return env.ASSETS.fetch(req); // not an asset either: its 404
    const path = url.pathname.slice(4).replace(/\/+$/, '') || '/';
    const origin = req.headers.get('Origin');
    const cors = {
      'Access-Control-Allow-Origin': SITES.includes(origin) ? origin : SITES[0],
      'Access-Control-Allow-Methods': 'GET, POST, PUT, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Max-Age': '86400',
      'Vary': 'Origin'
    };
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors });
    try {
      const res = await route(req, env, url, path);
      for (const [k, v] of Object.entries(cors)) res.headers.set(k, v);
      return res;
    } catch (e) {
      const status = e instanceof Fail ? e.status : 500;
      if (status === 500) console.error(e.stack || e);
      return json({ error: status === 500 ? 'server error' : e.message }, status, cors);
    }
  }
};

// A book picture from R2 (key "<book id>/img/<file>"), with revalidation so phones re-download only changed ones.
async function picture(req, env, key) {
  if (req.method !== 'GET' && req.method !== 'HEAD') return new Response(null, { status: 405 });
  const obj = await env.BOOKS.get(key, { onlyIf: req.headers });
  if (!obj) return new Response('Not found', { status: 404 });
  const h = new Headers({ 'ETag': obj.httpEtag, 'Cache-Control': 'public, max-age=3600',
    'Content-Type': TYPES[key.split('.').pop().toLowerCase()] || 'application/octet-stream' });
  if (!('body' in obj) || !obj.body) return new Response(null, { status: 304, headers: h });
  return new Response(req.method === 'HEAD' ? null : obj.body, { headers: h });
}

class Fail extends Error { constructor(status, msg) { super(msg); this.status = status; } }
function json(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json; charset=utf-8', ...headers } });
}
async function body(req) {
  try { return JSON.parse(await req.text()); } catch (e) { throw new Fail(400, 'bad json'); }
}
function str(v, max) { return v == null ? '' : String(v).slice(0, max); }
function int(v) { return Number.isInteger(v) ? v : null; }
function now() { return new Date().toISOString(); }
function newId() { return crypto.randomUUID().replace(/-/g, '').slice(0, 16); }

// Readers are told apart only by a salted hash of their IP address, for the hourly limits.
async function who(req, env) {
  const ip = req.headers.get('CF-Connecting-IP') || 'local';
  const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(ip + '|' + (env.ADMIN_KEY || '')));
  return [...new Uint8Array(h)].slice(0, 8).map(b => b.toString(16).padStart(2, '0')).join('');
}
async function limit(env, table, ip) {
  const hourAgo = new Date(Date.now() - 3600e3).toISOString();
  const r = await env.DB.prepare(`SELECT COUNT(*) AS n FROM ${table} WHERE ip = ? AND created > ?`).bind(ip, hourAgo).first();
  if (r.n >= LIMITS[table]) throw new Fail(429, 'too many requests, try again later');
}

// The tables are created by the Worker itself on its first request, so deploying needs no database rights
// (the deploy token can be limited to this one Worker). Same statements as schema.sql.
let ready = null;
function schema(env) {
  if (!ready) {
    ready = env.DB.batch(SCHEMA.split(';').map(q => q.trim()).filter(Boolean).map(q => env.DB.prepare(q)));
    ready.catch(() => { ready = null; });
  }
  return ready;
}

async function route(req, env, url, path) {
  const m = req.method;
  let p;
  await schema(env);
  if (m === 'GET' && path === '/') return json({ ok: true });

  // ---- a reader reports a text error: {book, v, ch, b, page, quote, context, fix, lang}
  if (m === 'POST' && path === '/reports') {
    const r = await body(req), ip = await who(req, env);
    const book = str(r.book, 100), quote = str(r.quote, 1000);
    if (!/^[\w.-]+$/.test(book) || !quote.trim()) throw new Fail(400, 'book and quote are required');
    await limit(env, 'reports', ip);
    const res = await env.DB.prepare(
      'INSERT INTO reports (created, book, v, ch, b, page, quote, context, fix, lang, ip) VALUES (?,?,?,?,?,?,?,?,?,?,?)'
    ).bind(now(), book, str(r.v, 40), int(r.ch), int(r.b), int(r.page), quote, str(r.context, 1500), str(r.fix, 1000), str(r.lang, 5), ip).run();
    return json({ id: res.meta.last_row_id });
  }

  // ---- a reader sends a book: {book, contact, comment, lang}, then each file in pieces
  if (m === 'POST' && path === '/uploads') {
    const r = await body(req), ip = await who(req, env);
    await limit(env, 'uploads', ip);
    const id = newId();
    await env.DB.prepare('INSERT INTO uploads (id, created, book, contact, comment, lang, ip) VALUES (?,?,?,?,?,?,?)')
      .bind(id, now(), str(r.book, 300), str(r.contact, 200), str(r.comment, 2000), str(r.lang, 5), ip).run();
    return json({ id });
  }
  if (m === 'POST' && (p = path.match(/^\/uploads\/(\w+)\/files$/))) { // {name, size, type}
    const r = await body(req), up = await getUpload(env, p[1]);
    const size = Number(r.size) || 0;
    if (size <= 0 || size > MAX_FILE) throw new Fail(413, 'file too big');
    const count = await env.DB.prepare('SELECT COUNT(*) AS n FROM files WHERE upload_id = ?').bind(up.id).first();
    if (count.n >= MAX_FILES) throw new Fail(413, 'too many files');
    const fid = newId(), name = str(r.name, 200).replace(/[^\p{L}\p{N} ._()-]/gu, '_') || 'file';
    const key = `uploads/${up.created.slice(0, 10)}-${up.id}/${fid}-${name}`, type = str(r.type, 100) || 'application/octet-stream';
    const mp = await env.FILES.createMultipartUpload(key, { httpMetadata: { contentType: type } });
    await env.DB.prepare('INSERT INTO files (id, upload_id, created, name, size, type, r2key, r2upload) VALUES (?,?,?,?,?,?,?,?)')
      .bind(fid, up.id, now(), name, size, type, key, mp.uploadId).run();
    return json({ file: fid });
  }
  if (m === 'PUT' && (p = path.match(/^\/uploads\/(\w+)\/files\/(\w+)\/(\d+)$/))) { // one piece (body = bytes)
    const f = await getFile(env, p[1], p[2]), n = +p[3];
    if (f.done || n < 1 || n > 10000) throw new Fail(400, 'bad part');
    const part = await env.FILES.resumeMultipartUpload(f.r2key, f.r2upload).uploadPart(n, await req.arrayBuffer());
    return json({ etag: part.etag });
  }
  if (m === 'POST' && (p = path.match(/^\/uploads\/(\w+)\/files\/(\w+)\/done$/))) { // {parts: [{n, etag}]}
    const r = await body(req), f = await getFile(env, p[1], p[2]);
    if (f.done) return json({ ok: true });
    const parts = (r.parts || []).map(x => ({ partNumber: +x.n, etag: String(x.etag) })).sort((a, b) => a.partNumber - b.partNumber);
    const obj = await env.FILES.resumeMultipartUpload(f.r2key, f.r2upload).complete(parts);
    await env.DB.prepare('UPDATE files SET done = 1, size = ? WHERE id = ?').bind(obj.size, f.id).run();
    return json({ ok: true });
  }

  // ---- admin: the page, and the data it (or a Claude session) reads with the key
  if (m === 'GET' && path === '/admin') return new Response(ADMIN_HTML, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
  if (path.startsWith('/admin/')) {
    const key = (req.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '') || url.searchParams.get('key');
    if (!env.ADMIN_KEY || key !== env.ADMIN_KEY) throw new Fail(401, 'wrong key');
    if (m === 'GET' && path === '/admin/reports') { // ?status=new|fixed|rejected|all
      const st = url.searchParams.get('status') || 'new';
      const q = st === 'all' ? env.DB.prepare('SELECT * FROM reports ORDER BY id DESC LIMIT 2000')
        : env.DB.prepare('SELECT * FROM reports WHERE status = ? ORDER BY id DESC LIMIT 2000').bind(st);
      return json((await q.all()).results);
    }
    if (m === 'POST' && (p = path.match(/^\/admin\/reports\/(\d+)$/))) { // {status, note}
      const r = await body(req);
      if (!['new', 'fixed', 'rejected'].includes(r.status)) throw new Fail(400, 'bad status');
      await env.DB.prepare('UPDATE reports SET status = ?, note = ? WHERE id = ?').bind(r.status, str(r.note, 1000), +p[1]).run();
      return json({ ok: true });
    }
    if (m === 'GET' && path === '/admin/uploads') {
      const ups = (await env.DB.prepare('SELECT * FROM uploads ORDER BY created DESC LIMIT 500').all()).results;
      const files = (await env.DB.prepare('SELECT id, upload_id, name, size, type, done FROM files').all()).results;
      ups.forEach(u => { u.files = files.filter(f => f.upload_id === u.id); });
      return json(ups.filter(u => u.files.length));
    }
    if (m === 'GET' && (p = path.match(/^\/admin\/files\/(\w+)$/))) {
      const f = await env.DB.prepare('SELECT * FROM files WHERE id = ?').bind(p[1]).first();
      const obj = f && await env.FILES.get(f.r2key);
      if (!obj) throw new Fail(404, 'no such file');
      return new Response(obj.body, { headers: { 'Content-Type': f.type, 'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent(f.name)}` } });
    }
  }
  throw new Fail(404, 'not found');
}

async function getUpload(env, id) {
  const up = await env.DB.prepare('SELECT * FROM uploads WHERE id = ?').bind(id).first();
  if (!up) throw new Fail(404, 'no such upload');
  if (Date.now() - Date.parse(up.created) > 24 * 3600e3) throw new Fail(410, 'upload expired');
  return up;
}
async function getFile(env, uid, fid) {
  const f = await env.DB.prepare('SELECT * FROM files WHERE id = ? AND upload_id = ?').bind(fid, uid).first();
  if (!f) throw new Fail(404, 'no such file');
  return f;
}

const SCHEMA = `CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created TEXT NOT NULL,
  book TEXT NOT NULL,
  v TEXT,
  ch INTEGER, b INTEGER,
  page INTEGER,
  quote TEXT NOT NULL,
  context TEXT,
  fix TEXT,
  lang TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  note TEXT,
  ip TEXT
);
CREATE INDEX IF NOT EXISTS reports_status ON reports (status, id);
CREATE INDEX IF NOT EXISTS reports_ip ON reports (ip, created);

CREATE TABLE IF NOT EXISTS uploads (
  id TEXT PRIMARY KEY,
  created TEXT NOT NULL,
  book TEXT, contact TEXT, comment TEXT, lang TEXT,
  ip TEXT
);
CREATE INDEX IF NOT EXISTS uploads_ip ON uploads (ip, created);

CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  upload_id TEXT NOT NULL REFERENCES uploads (id),
  created TEXT NOT NULL,
  name TEXT, size INTEGER, type TEXT,
  r2key TEXT NOT NULL, r2upload TEXT,
  done INTEGER NOT NULL DEFAULT 0
);`;

const ADMIN_HTML = `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Отчёты об ошибках</title><style>
body{font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:900px;padding:12px 16px 40px;color:#1b1b1b;background:#fff}
h1{font-size:20px}nav button,.st button,form button{font:inherit;padding:8px 12px;border-radius:8px;border:1px solid #ccc;background:#f6f6f6;margin:0 6px 6px 0}
nav button.on{background:#1f6feb;color:#fff;border-color:#1f6feb}.it{border-bottom:1px solid #e3e3e3;padding:10px 0}
.m{color:#6b6b6b;font-size:13px}q{display:block;background:#f6f6f6;border-left:3px solid #1f6feb;padding:6px 10px;margin:6px 0;quotes:none}
.ctx{font-size:13px;color:#444}.fix{color:#0a7a2f}input{font:inherit;padding:8px;border-radius:8px;border:1px solid #ccc}a{color:#1f6feb}
</style></head><body><h1>Мектеп китептери: отчёты</h1>
<form id="login"><input id="key" type="password" placeholder="Ключ администратора" autocomplete="current-password"> <button>Войти</button></form>
<nav hidden><button data-v="new" class="on">Новые ошибки</button><button data-v="fixed">Исправленные</button><button data-v="rejected">Отклонённые</button><button data-v="uploads">Присланные книги</button></nav>
<div id="out"></div>
<script>
var SITE='/', key=localStorage.getItem('key')||'', view='new';
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function get(p,o){o=o||{};o.headers={Authorization:'Bearer '+key};return fetch(p,o).then(function(r){if(r.status===401){document.getElementById('login').hidden=false;throw new Error('key')}return r.json()})}
function mb(n){return (n/1048576).toFixed(1)+' МБ'}
function show(){var out=document.getElementById('out');out.textContent='…';
 if(view==='uploads')return get('/api/admin/uploads').then(function(l){out.innerHTML=l.length?l.map(function(u){return '<div class="it"><b>'+esc(u.book)+'</b><div class="m">'+esc(u.created.slice(0,16).replace('T',' '))+(u.contact?' · '+esc(u.contact):'')+'</div>'+(u.comment?'<div>'+esc(u.comment)+'</div>':'')+u.files.map(function(f){return '<div>'+(f.done?'<a href="/api/admin/files/'+f.id+'?key='+encodeURIComponent(key)+'">'+esc(f.name)+'</a>':esc(f.name)+' (не докачан)')+' · '+mb(f.size)+'</div>'}).join('')+'</div>'}).join(''):'Пока ничего нет.'});
 get('/api/admin/reports?status='+view).then(function(l){out.innerHTML=l.length?l.map(function(r){return '<div class="it" data-id="'+r.id+'"><div class="m">'+esc(r.created.slice(0,16).replace('T',' '))+' · <a href="'+SITE+'#/read/'+esc(r.book)+'" target="_blank">'+esc(r.book)+'</a>'+(r.page!=null?' · стр. '+r.page:'')+' · глава '+r.ch+', блок '+r.b+'</div><q>'+esc(r.quote)+'</q>'+(r.fix?'<div class="fix">Как правильно: '+esc(r.fix)+'</div>':'')+'<div class="ctx">'+esc(r.context)+'</div><div class="st">'+(view!=='fixed'?'<button data-s="fixed">Исправлено</button>':'')+(view!=='rejected'?'<button data-s="rejected">Не ошибка</button>':'')+(view!=='new'?'<button data-s="new">Вернуть в новые</button>':'')+'</div></div>'}).join(''):'Пока ничего нет.'})}
document.getElementById('out').onclick=function(e){var b=e.target.closest('button[data-s]');if(!b)return;var it=b.closest('.it');
 get('/api/admin/reports/'+it.getAttribute('data-id'),{method:'POST',body:JSON.stringify({status:b.getAttribute('data-s')})}).then(function(){it.remove()})};
document.querySelector('nav').onclick=function(e){var b=e.target.closest('button');if(!b)return;view=b.getAttribute('data-v');
 [].forEach.call(this.children,function(x){x.classList.toggle('on',x===b)});show()};
document.getElementById('login').onsubmit=function(e){e.preventDefault();key=document.getElementById('key').value;localStorage.setItem('key',key);start()};
function start(){get('/api/admin/reports?status=new').then(function(){document.getElementById('login').hidden=true;document.querySelector('nav').hidden=false;show()},function(){})}
if(key)start();
</script></body></html>`;
