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
The deploy token is limited to this one Worker (Cloudflare's per-Worker API tokens), so it cannot touch other
projects in the account. Everything that needs account-wide rights is done once by hand in the dashboard:

1. D1: create a database `el-kitep`; put its id into `wrangler.toml` (`database_id`).
2. R2: create a bucket `el-kitep-uploads`.
3. Workers & Pages: create a Worker named `el-kitep-api` (any starter; the deploy replaces its code).
   Optional: Settings → Domains & Routes → add the custom domain `api.elkitep.com`.
4. Manage Account → Account API Tokens → Create: scope "Specified Workers" → `el-kitep-api`, role Editor.

Then, with `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` set:

    cd backend && npm install
    npx wrangler secret put ADMIN_KEY            # the password for /admin
    npx wrangler deploy

The Worker creates its tables on the first request (the same statements as `schema.sql`), so the token needs
no database rights. Then set `API` at the top of `site/app.js` to the Worker's address and add that site's
address to `SITES` in `src/worker.js`. The "report an error" button in the reader and the upload form on the
missing textbooks page appear once `API` is set.

## Try it locally

    cd backend && npm install
    echo 'ADMIN_KEY=test-key' > .dev.vars
    npx wrangler d1 execute el-kitep --local --file schema.sql
    npm run dev                                  # http://localhost:8787, local database and files

and serve `site/` on http://localhost:8080 with `API = 'http://localhost:8787'`.
