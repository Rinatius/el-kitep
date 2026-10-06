-- Database for backend/src/worker.js (Cloudflare D1, SQLite).
-- The Worker runs these itself on its first request (SCHEMA in src/worker.js); keep the two in step.
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created TEXT NOT NULL,          -- ISO time, UTC
  book TEXT NOT NULL,             -- book id, as in site/books/index.json
  v TEXT,                         -- book version the reader had
  ch INTEGER, b INTEGER,          -- chapter and block index in book.json
  page INTEGER,                   -- printed page number
  quote TEXT NOT NULL,            -- the text the reader selected
  context TEXT,                   -- text around it
  fix TEXT,                       -- what the reader thinks it should say
  lang TEXT,                      -- interface language: ru or ky
  status TEXT NOT NULL DEFAULT 'new', -- new, fixed, rejected
  note TEXT,
  ip TEXT                         -- salted hash, only for the hourly limit
);
CREATE INDEX IF NOT EXISTS reports_status ON reports (status, id);
CREATE INDEX IF NOT EXISTS reports_ip ON reports (ip, created);
CREATE INDEX IF NOT EXISTS reports_created ON reports (created); -- the daily limit for everyone

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
  r2key TEXT NOT NULL, r2upload TEXT, -- object key in the bucket and its multipart upload id
  done INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS files_created ON files (created);
