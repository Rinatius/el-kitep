/* The whole site at elkitep.com, as one Cloudflare Worker:
 * - the reader app and book texts (site/ without the pictures) are static assets, served by Cloudflare
 *   before this code runs (see wrangler.toml and tools/build_cloudflare.sh);
 * - book pictures (site/books/<id>/img/) live in the R2 bucket BOOKS, because the free plan allows
 *   20,000 asset files and the pictures alone are more. On elkitep.com the app loads them straight from the bucket's
 *   own address img.elkitep.com (no Worker request, so they don't count against the daily limit); the route below
 *   serves them for the workers.dev address and local testing;
 * - /api/...: text-error reports and books that readers upload, in a D1 database (SQLite) and the R2 bucket FILES.
 * Readers need no account. The admin page (/api/admin) and the admin API need the ADMIN_KEY secret; the read-only
 * STATS_KEY opens GET /api/admin/hits and /api/admin/reports only. See README.md.
 * Security notes: /mnt/project-files/security/CHECKLIST.md in the project (abuse limits, headers, what the dashboard must have). */

const SITES = ['https://elkitep.com', 'https://www.elkitep.com', 'https://rinatius.github.io', 'http://localhost:8080', 'http://localhost:8787'];
const MAX_FILE = 500 * 1048576, MAX_FILES = 40, PIECE = 8 * 1048576; // PIECE: CHUNK in site/app.js
// All uploaded files together, finished or not: past this the form says it can't take more for now. R2 is free up
// to 10 GB (then billed), so readers can't run up a bill. Counted from the files table (declared sizes).
const MAX_TOTAL = 5 * 1024 ** 3;
const LIMITS = { reports: 60, uploads: 10 }; // per reader (hashed IP) per hour
// For all readers together per day, so nobody can fill the database (D1 Free: 100,000 rows written a day) or run
// up R2 operations with many addresses. Past these the form says it can't take more for now.
const DAILY = { reports: 2000, uploads: 100, files: 500 };
// Reading counts (POST /hits): at most this many counted events a day for the whole site (D1 writes are shared with
// reports and uploads), per request, and per book and event in one request.
const HITS_DAY = 20000, HITS_REQ = 50, HITS_EACH = 10, HIT_EVENTS = ['app', 'open', 'dl'];
// On every answer the Worker itself writes (static assets get theirs from ../_headers).
const SECURE = { 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'strict-origin-when-cross-origin', 'X-Frame-Options': 'DENY' };
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
      for (const [k, v] of Object.entries({ ...SECURE, ...cors })) res.headers.set(k, v);
      if (!res.headers.has('Cache-Control')) res.headers.set('Cache-Control', 'no-store');
      return res;
    } catch (e) {
      const status = e instanceof Fail ? e.status : 500;
      if (status === 500) console.error(e.stack || e);
      return json({ error: status === 500 ? 'server error' : e.message }, status, { ...SECURE, ...cors, 'Cache-Control': 'no-store' });
    }
  }
};

// A book picture from R2 (key "<book id>/img/<file>"), with revalidation so phones re-download only changed ones.
async function picture(req, env, key) {
  if (req.method !== 'GET' && req.method !== 'HEAD') return new Response(null, { status: 405 });
  const obj = await env.BOOKS.get(key, { onlyIf: req.headers });
  if (!obj) return new Response('Not found', { status: 404 });
  const h = new Headers({ 'ETag': obj.httpEtag, 'Cache-Control': 'public, max-age=3600', 'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox", // an SVG opened on its own can't run scripts
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
async function room(env, add) {
  const r = await env.DB.prepare('SELECT COALESCE(SUM(size), 0) AS n FROM files').first();
  if (r.n >= MAX_TOTAL || r.n + add > MAX_TOTAL) throw new Fail(507, 'no room for uploads now');
}
// The hourly limit for one reader, then the daily limit for everyone (table is one of our own names, never input).
async function limit(env, table, ip) {
  const since = ms => new Date(Date.now() - ms).toISOString();
  if (ip) {
    const r = await env.DB.prepare(`SELECT COUNT(*) AS n FROM ${table} WHERE ip = ? AND created > ?`).bind(ip, since(3600e3)).first();
    if (r.n >= LIMITS[table]) throw new Fail(429, 'too many requests, try again later');
  }
  const d = await env.DB.prepare(`SELECT COUNT(*) AS n FROM ${table} WHERE created > ?`).bind(since(86400e3)).first();
  if (d.n >= DAILY[table]) {
    if (table === 'reports') throw new Fail(429, 'too many requests, try again later');
    throw new Fail(507, 'no room for uploads now');
  }
}
const STATS_PATHS = ['/admin/hits', '/admin/reports'];
// The admin key, compared in constant time (both sides hashed, so the lengths match).
async function keyOk(given, want) {
  if (!given || !want) return false;
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([crypto.subtle.digest('SHA-256', enc.encode(given)), crypto.subtle.digest('SHA-256', enc.encode(want))]);
  return crypto.subtle.timingSafeEqual(a, b);
}
// Content-Security-Policy for the admin page: only its own inline script and style may run.
let adminCsp = null;
async function adminHeaders() {
  if (!adminCsp) {
    const hash = async s => "'sha256-" + btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))))) + "'";
    const script = await hash(ADMIN_HTML.match(/<script>([\s\S]*?)<\/script>/)[1]), style = await hash(ADMIN_HTML.match(/<style>([\s\S]*?)<\/style>/)[1]);
    adminCsp = `default-src 'none'; script-src ${script}; style-src ${style}; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`;
  }
  return { 'Content-Type': 'text/html; charset=utf-8', 'Content-Security-Policy': adminCsp };
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

  // ---- reading counts: [{b: book id ("" for "the app was opened"), e: "app"|"open"|"dl", f: 1 if this phone's
  // first (book: ever; app: today), d: "YYYY-MM-DD" when it happened}]. Only daily totals per book are kept:
  // no address, no device id, nothing that tells readers apart. Opens made offline arrive later with their day.
  if (m === 'POST' && path === '/hits') {
    const r = await body(req);
    if (!Array.isArray(r) || r.length > HITS_REQ) throw new Fail(400, 'bad hits');
    const ids = await bookIds(env, url), today = now().slice(0, 10), oldest = new Date(Date.now() - 30 * 86400e3).toISOString().slice(0, 10);
    const sum = new Map();
    for (const h of r) {
      const e = h && h.e, b = e === 'app' ? '' : str(h && h.b, 80);
      if (!HIT_EVENTS.includes(e) || (e !== 'app' && !ids.has(b))) continue; // only books that exist: no junk rows
      const d = /^\d{4}-\d\d-\d\d$/.test(h.d) && h.d >= oldest && h.d <= today ? h.d : today;
      const k = d + '|' + b + '|' + e, c = sum.get(k) || { d, b, e, n: 0, f: 0 };
      if (c.n >= HITS_EACH) continue;
      c.n++; if (h.f === 1) c.f++;
      sum.set(k, c);
    }
    if (!sum.size) return json({ ok: true });
    const n = [...sum.values()].reduce((a, c) => a + c.n, 0);
    const day = await env.DB.prepare('SELECT n FROM hitdays WHERE day = ?').bind(today).first();
    if (day && day.n >= HITS_DAY) return json({ ok: true }); // past the daily cap: accepted but not counted (no writes)
    await env.DB.batch([env.DB.prepare('INSERT INTO hitdays (day, n) VALUES (?, ?) ON CONFLICT (day) DO UPDATE SET n = n + excluded.n').bind(today, n)]
      .concat([...sum.values()].map(c => env.DB.prepare(
      'INSERT INTO hits (day, book, ev, n, firsts) VALUES (?,?,?,?,?) ON CONFLICT (day, book, ev) DO UPDATE SET n = n + excluded.n, firsts = firsts + excluded.firsts'
    ).bind(c.d, c.b, c.e, c.n, c.f))));
    return json({ ok: true });
  }

  // ---- a reader sends a book: {book, contact, comment, lang}, then each file in pieces
  if (m === 'POST' && path === '/uploads') {
    const r = await body(req), ip = await who(req, env);
    await room(env, 0);
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
    await limit(env, 'files', null);
    await room(env, size);
    const fid = newId(), name = str(r.name, 200).replace(/[^\p{L}\p{N} ._()-]/gu, '_') || 'file';
    const key = `uploads/${up.created.slice(0, 10)}-${up.id}/${fid}-${name}`, type = str(r.type, 100) || 'application/octet-stream';
    const mp = await env.FILES.createMultipartUpload(key, { httpMetadata: { contentType: type } });
    await env.DB.prepare('INSERT INTO files (id, upload_id, created, name, size, type, r2key, r2upload) VALUES (?,?,?,?,?,?,?,?)')
      .bind(fid, up.id, now(), name, size, type, key, mp.uploadId).run();
    return json({ file: fid });
  }
  if (m === 'PUT' && (p = path.match(/^\/uploads\/(\w+)\/files\/(\w+)\/(\d+)$/))) { // one piece (body = bytes)
    const f = await getFile(env, p[1], p[2]), n = +p[3];
    // no more pieces, and no bigger ones, than the declared size needs, so the total above holds:
    // piece n may hold at most what is left of the declared size after the pieces before it
    if (f.done || n < 1 || n > Math.ceil(f.size / PIECE)) throw new Fail(400, 'bad part');
    const max = Math.min(PIECE, f.size - (n - 1) * PIECE);
    if (+req.headers.get('Content-Length') > max) throw new Fail(413, 'piece too big');
    const bytes = await req.arrayBuffer();
    if (bytes.byteLength > max) throw new Fail(413, 'piece too big');
    const part = await env.FILES.resumeMultipartUpload(f.r2key, f.r2upload).uploadPart(n, bytes);
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
  if (m === 'GET' && path === '/admin') return new Response(ADMIN_HTML, { headers: await adminHeaders() });
  if (path.startsWith('/admin/')) {
    // the key travels only in this header, never in the address (addresses end up in logs and browser history)
    const key = (req.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '');
    // STATS_KEY is a second, read-only key for Claude sessions and routines: it reads the daily counters and the
    // error reports, nothing else (no uploads, which can hold contacts, and no changes)
    const ok = (await keyOk(key, env.ADMIN_KEY)) || (m === 'GET' && STATS_PATHS.includes(path) && (await keyOk(key, env.STATS_KEY)));
    if (!ok) throw new Fail(401, 'wrong key');
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
    if (m === 'GET' && path === '/admin/hits') { // ?days=30: daily totals, newest first
      const days = Math.min(Math.max(parseInt(url.searchParams.get('days'), 10) || 30, 1), 400);
      const since = new Date(Date.now() - days * 86400e3).toISOString().slice(0, 10);
      return json((await env.DB.prepare('SELECT day, book, ev, n, firsts FROM hits WHERE day > ? ORDER BY day DESC, n DESC LIMIT 20000').bind(since).all()).results);
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

// The ids of the books on the site (books/index.json from the static assets), kept for a few minutes.
let books = null;
async function bookIds(env, url) {
  if (!books || Date.now() - books.at > 300e3) {
    const r = await env.ASSETS.fetch(new Request(new URL('/books/index.json', url)));
    if (!r.ok) throw new Fail(503, 'book list unavailable');
    books = { at: Date.now(), ids: new Set((await r.json()).map(b => b.id)) };
  }
  return books.ids;
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
CREATE INDEX IF NOT EXISTS reports_created ON reports (created);

CREATE TABLE IF NOT EXISTS uploads (
  id TEXT PRIMARY KEY,
  created TEXT NOT NULL,
  book TEXT, contact TEXT, comment TEXT, lang TEXT,
  ip TEXT
);
CREATE INDEX IF NOT EXISTS uploads_ip ON uploads (ip, created);
CREATE INDEX IF NOT EXISTS uploads_created ON uploads (created);

CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  upload_id TEXT NOT NULL REFERENCES uploads (id),
  created TEXT NOT NULL,
  name TEXT, size INTEGER, type TEXT,
  r2key TEXT NOT NULL, r2upload TEXT,
  done INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS files_created ON files (created);

CREATE TABLE IF NOT EXISTS hits (
  day TEXT NOT NULL,
  book TEXT NOT NULL,
  ev TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  firsts INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, book, ev)
);
CREATE TABLE IF NOT EXISTS hitdays (
  day TEXT PRIMARY KEY,
  n INTEGER NOT NULL DEFAULT 0
);`;

const ADMIN_HTML = `<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Отчёты об ошибках</title><style>
body{font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:900px;padding:12px 16px 40px;color:#1b1b1b;background:#fff}
h1{font-size:20px}nav button,.st button,form button{font:inherit;padding:8px 12px;border-radius:8px;border:1px solid #ccc;background:#f6f6f6;margin:0 6px 6px 0}
nav button.on{background:#1f6feb;color:#fff;border-color:#1f6feb}.it{border-bottom:1px solid #e3e3e3;padding:10px 0}
.m{color:#6b6b6b;font-size:13px}q{display:block;background:#f6f6f6;border-left:3px solid #1f6feb;padding:6px 10px;margin:6px 0;quotes:none}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:4px 6px;border-bottom:1px solid #e3e3e3;text-align:right}td:first-child,th:first-child{text-align:left}
.ctx{font-size:13px;color:#444}.fix{color:#0a7a2f}input{font:inherit;padding:8px;border-radius:8px;border:1px solid #ccc}a{color:#1f6feb}
</style></head><body><h1>Мектеп китептери: отчёты</h1>
<form id="login"><input id="key" type="password" placeholder="Ключ администратора" autocomplete="current-password"> <button>Войти</button></form>
<nav hidden><button data-v="new" class="on">Новые ошибки</button><button data-v="fixed">Исправленные</button><button data-v="rejected">Отклонённые</button><button data-v="uploads">Присланные книги</button><button data-v="hits">Чтение</button></nav>
<div id="out"></div>
<script>
var SITE='/', key=localStorage.getItem('key')||'', view='new';
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function get(p,o){o=o||{};o.headers={Authorization:'Bearer '+key};return fetch(p,o).then(function(r){if(r.status===401){document.getElementById('login').hidden=false;throw new Error('key')}return r.json()})}
function mb(n){return (n/1048576).toFixed(1)+' МБ'}
function hits(out){return Promise.all([get('/api/admin/hits?days=30'),fetch('/books/index.json').then(function(r){return r.json()},function(){return[]})]).then(function(r){
 var title={};r[1].forEach(function(b){title[b.id]=b.title+(b.grade?', '+b.grade+' кл.':'')+(b.school==='ky'?' (кырг.)':b.school==='ru'?' (рус.)':'')});
 var days={},bk={};r[0].forEach(function(h){if(h.ev==='app'){var d=days[h.day]=days[h.day]||{n:0,f:0};d.n+=h.n;d.f+=h.firsts;return}
  var b=bk[h.book]=bk[h.book]||{open:0,readers:0,dl:0};if(h.ev==='open'){b.open+=h.n;b.readers+=h.firsts}else b.dl+=h.n});
 var dl=Object.keys(days).sort().reverse(),bl=Object.keys(bk).sort(function(a,b){return bk[b].open-bk[a].open});
 out.innerHTML='<p class="m">За 30 дней, числа приблизительные (их присылают сами телефоны). Считаются только итоги за день, без данных о читателях. «Телефонов» — сколько разных телефонов открыли сайт в этот день; «новых читателей» — сколько телефонов открыли книгу впервые.</p>'+
  '<h3>По дням</h3><table><tr><th>День</th><th>Телефонов</th><th>Открытий сайта</th></tr>'+dl.map(function(d){return '<tr><td>'+esc(d)+'</td><td>'+days[d].f+'</td><td>'+days[d].n+'</td></tr>'}).join('')+'</table>'+
  '<h3>Книги</h3><table><tr><th>Книга</th><th>Открытий</th><th>Новых читателей</th><th>Скачиваний</th></tr>'+bl.map(function(id){var b=bk[id];return '<tr><td>'+esc(title[id]||id)+'</td><td>'+b.open+'</td><td>'+b.readers+'</td><td>'+b.dl+'</td></tr>'}).join('')+'</table>'+
  (dl.length||bl.length?'':'<p>Пока ничего нет.</p>')})}
function show(){var out=document.getElementById('out');out.textContent='…';
 if(view==='hits')return hits(out);
 if(view==='uploads')return get('/api/admin/uploads').then(function(l){out.innerHTML=l.length?l.map(function(u){return '<div class="it"><b>'+esc(u.book)+'</b><div class="m">'+esc(u.created.slice(0,16).replace('T',' '))+(u.contact?' · '+esc(u.contact):'')+'</div>'+(u.comment?'<div>'+esc(u.comment)+'</div>':'')+u.files.map(function(f){return '<div>'+(f.done?'<a href="#" data-f="'+esc(f.id)+'" data-n="'+esc(f.name)+'">'+esc(f.name)+'</a>':esc(f.name)+' (не докачан)')+' · '+mb(f.size)+'</div>'}).join('')+'</div>'}).join(''):'Пока ничего нет.'});
 get('/api/admin/reports?status='+view).then(function(l){out.innerHTML=l.length?l.map(function(r){return '<div class="it" data-id="'+r.id+'"><div class="m">'+esc(r.created.slice(0,16).replace('T',' '))+' · <a href="'+SITE+'#/read/'+esc(r.book)+'" target="_blank">'+esc(r.book)+'</a>'+(r.page!=null?' · стр. '+r.page:'')+' · глава '+r.ch+', блок '+r.b+'</div><q>'+esc(r.quote)+'</q>'+(r.fix?'<div class="fix">Как правильно: '+esc(r.fix)+'</div>':'')+'<div class="ctx">'+esc(r.context)+'</div><div class="st">'+(view!=='fixed'?'<button data-s="fixed">Исправлено</button>':'')+(view!=='rejected'?'<button data-s="rejected">Не ошибка</button>':'')+(view!=='new'?'<button data-s="new">Вернуть в новые</button>':'')+'</div></div>'}).join(''):'Пока ничего нет.'})}
document.getElementById('out').onclick=function(e){var a=e.target.closest('a[data-f]');
 if(a){e.preventDefault();a.textContent=a.getAttribute('data-n')+' …';
  fetch('/api/admin/files/'+a.getAttribute('data-f'),{headers:{Authorization:'Bearer '+key}}).then(function(r){if(!r.ok)throw new Error(r.status);return r.blob()}).then(function(b){
   var u=URL.createObjectURL(b),l=document.createElement('a');l.href=u;l.download=a.getAttribute('data-n');document.body.appendChild(l);l.click();l.remove();setTimeout(function(){URL.revokeObjectURL(u)},60000);a.textContent=a.getAttribute('data-n')},
   function(){a.textContent=a.getAttribute('data-n')+' (не удалось скачать)'});return}
 var b=e.target.closest('button[data-s]');if(!b)return;var it=b.closest('.it');
 get('/api/admin/reports/'+it.getAttribute('data-id'),{method:'POST',body:JSON.stringify({status:b.getAttribute('data-s')})}).then(function(){it.remove()})};
document.querySelector('nav').onclick=function(e){var b=e.target.closest('button');if(!b)return;view=b.getAttribute('data-v');
 [].forEach.call(this.children,function(x){x.classList.toggle('on',x===b)});show()};
document.getElementById('login').onsubmit=function(e){e.preventDefault();key=document.getElementById('key').value;localStorage.setItem('key',key);start()};
function start(){get('/api/admin/reports?status=new').then(function(){document.getElementById('login').hidden=true;document.querySelector('nav').hidden=false;show()},function(){})}
if(key)start();
</script></body></html>`;
