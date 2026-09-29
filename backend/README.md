# Server for error reports and uploaded books

One small Cloudflare Worker (`src/worker.js`) with a D1 database (SQLite, `schema.sql`) and an R2 bucket for files.
Free tier: 100,000 requests a day, 5 GB database, 10 GB of files. Nothing to patch or keep running.

What it does:
- `POST /reports`: a reader selected text in a book and reported an error (book id, chapter, block, printed page,
  the selected text, the text around it, the reader's correction).
- `POST /uploads`, then per file `POST /uploads/<id>/files`, `PUT /uploads/<id>/files/<file>/<n>` (8 MB pieces),
  `POST /uploads/<id>/files/<file>/done`: a reader sends a missing textbook (PDF or photos, up to 500 MB a file).
- `GET /admin`: a page to read reports (mark them fixed or not an error) and download uploaded files.
- `GET /admin/reports?status=new` with `Authorization: Bearer <ADMIN_KEY>`: the reports as JSON, for fixing books.

Readers need no account. Each reader may send 60 reports and 10 uploads an hour (counted by a salted hash of the
IP address; addresses themselves are not stored).

## Deploy (once)
Needs a free Cloudflare account with R2 turned on (Cloudflare asks for a card to turn on R2, even on the free plan),
and `CLOUDFLARE_API_TOKEN` with Workers Scripts, D1 and R2 edit rights.

    cd backend && npm install
    npx wrangler d1 create el-kitep              # put the database_id it prints into wrangler.toml
    npx wrangler r2 bucket create el-kitep-uploads
    npx wrangler d1 execute el-kitep --remote --file schema.sql
    npx wrangler secret put ADMIN_KEY            # the password for /admin
    npx wrangler deploy                          # prints https://el-kitep-api.<account>.workers.dev

Then set `API` at the top of `site/app.js` to that address. The "report an error" button in the reader and the
upload form on the missing textbooks page appear once `API` is set.

## Try it locally

    cd backend && npm install
    echo 'ADMIN_KEY=test-key' > .dev.vars
    npx wrangler d1 execute el-kitep --local --file schema.sql
    npm run dev                                  # http://localhost:8787, local database and files

and serve `site/` on http://localhost:8080 with `API = 'http://localhost:8787'`.
