# elkitep.com on Cloudflare: the site, book pictures, error reports and uploaded books

One Cloudflare Worker (`src/worker.js`, config `wrangler.toml`). The reader app and book texts are static assets
(`dist/`, built by `tools/build_cloudflare.sh` from `site/` without the pictures); book pictures come from the R2
bucket `el-kitep-books` at img.elkitep.com, because the free plan allows 20,000 asset files; `/api` stores reports and upload records
in a D1 database (SQLite, `schema.sql`) and uploaded files in the R2 bucket `el-kitep-uploads`.
Free tier: 100,000 requests a day, 5 GB database, 10 GB of files. Nothing to patch or keep running.

The server, under `/api`:
- `POST /reports`: a reader selected text in a book and reported an error (book id, chapter, block, printed page,
  the selected text, the text around it, the reader's correction).
- `POST /uploads`, then per file `POST /uploads/<id>/files`, `PUT /uploads/<id>/files/<file>/<n>` (8 MB pieces),
  `POST /uploads/<id>/files/<file>/done`: a reader sends a missing textbook (PDF or photos, up to 500 MB a file).
- `POST /hits`: reading counts from the app (the site was opened, a book was opened or downloaded), batched, sent
  later when offline. Only daily totals per book are stored (table `hits`), nothing about the reader; a phone's first
  open of a book (and first visit of the day) is flagged by the app itself, so totals of phones need no id. Unknown
  book ids are dropped; at most 50,000 events a day are counted. The admin page shows them under "Чтение".
- `GET /admin` (so elkitep.com/api/admin): a page to read reports (mark them fixed or not an error) and download uploaded files.
- `GET /admin/reports?status=new` with `Authorization: Bearer <ADMIN_KEY>`: the reports as JSON, for fixing books.

Readers need no account. Each reader may send 60 reports and 10 uploads an hour (counted by a salted hash of the
IP address; addresses themselves are not stored), and all readers together 2,000 reports, 100 uploads and 500 files
a day (`DAILY` in `src/worker.js`), so nobody can fill the database or run up R2 operations from many addresses.
All uploaded files together may take up to 5 GB (`MAX_TOTAL` in `src/worker.js`, counted from the `files` table,
unfinished files included, and each piece may hold no more than the declared size leaves for it); after that the
form tells readers it can't take more for now. R2 is free up to 10 GB, so readers can't run up a bill. To make room,
raise `MAX_TOTAL` or delete handled files from the bucket and their rows from `files`.
The admin key travels only in the `Authorization` header (never in the address, which would end up in logs); the
admin page downloads files with that header too. Answers carry security headers (`SECURE` in `src/worker.js`, a
hashed Content-Security-Policy on the admin page); the static assets get theirs from `_headers`, which the build
copies into `dist/`. Workers Logs are on (`[observability]` in `wrangler.toml`): free, kept 3 days, read by the
project's daily security review. The security checklist lives in the project files, `security/CHECKLIST.md`.

## Deploy
`.github/workflows/cloudflare.yml` deploys on every merge into the live branch, once its repository secrets are
set (listed at the top of that file). The tokens are narrow: the API token is scoped to the one Worker (role Editor)
and the R2 key to the one pictures bucket, so neither can touch other projects in the account.
Everything that needs account-wide rights is done once by hand in the dashboard:

1. D1: create a database `el-kitep` (its id goes into the secret `D1_DATABASE_ID`).
2. R2: create the buckets `el-kitep-uploads` and `el-kitep-books`.
3. Workers & Pages: create a Worker named `el-kitep` (any starter; the deploy replaces it), then under
   Settings > Domains & Routes add the custom domain `elkitep.com`.
4. Manage Account > Account API Tokens > Create: scope "Specified Workers" > `el-kitep`, role Editor.
5. R2 > Manage API tokens > Create: Object Read & Write, applied to the bucket `el-kitep-books` only.
6. R2 > `el-kitep-books` > Settings > Custom Domains: connect `img.elkitep.com`. On elkitep.com the app loads book
   pictures from there, so picture requests don't count against the Worker's 100,000 requests a day.
7. Same bucket > Settings > CORS policy, so the app may save pictures for offline reading:

       [{"AllowedOrigins": ["https://elkitep.com", "https://www.elkitep.com"],
         "AllowedMethods": ["GET", "HEAD"], "AllowedHeaders": ["*"], "MaxAgeSeconds": 86400}]

8. R2 > `el-kitep-uploads` > Settings > Object lifecycle rules: abort incomplete multipart uploads after 1 day
   (the default is 7), so pieces of abandoned uploads don't sit in the bucket.
9. Security > WAF > Rate limiting rules (one rule is free): requests to elkitep.com with a path starting `/api/`
   or containing `/img/`, more than 50 in 10 seconds from one address, block for 10 seconds. Keeps one abuser
   from using up the Worker's 100,000 free requests a day.
10. Once elkitep.com works: Worker > Settings > Domains & Routes > disable `workers.dev` (and set
    `workers_dev = false` in `wrangler.toml`), so the site has one address and the rules above cover all of it.

The Worker creates its tables on the first request (the same statements as `schema.sql`), so the deploy needs
no database rights. The "report an error" button and the upload form turn on by themselves on elkitep.com
(`API` at the top of `site/app.js`).

## Try it locally

    cd backend && npm install
    echo 'ADMIN_KEY=test-key' > .dev.vars
    npx wrangler d1 execute el-kitep --local --file schema.sql
    npm run dev                                  # http://localhost:8787, local database and files

The whole site then runs at http://localhost:8787 (after `tools/build_cloudflare.sh`). Pictures come from the local
R2 bucket: `npx wrangler r2 object put el-kitep-books/<id>/img/<file> --file ../site/books/<id>/img/<file> --local`.
