# elkitep.com on Cloudflare: the site, book pictures, error reports and uploaded books

One Cloudflare Worker (`src/worker.js`, config `wrangler.toml`). The reader app and book texts are static assets
(`dist/`, built by `tools/build_cloudflare.sh` from `site/` without the pictures); book pictures come from the R2
bucket `el-kitep-books`, because the free plan allows 20,000 asset files; `/api` stores reports and upload records
in a D1 database (SQLite, `schema.sql`) and uploaded files in the R2 bucket `el-kitep-uploads`.
Free tier: 100,000 requests a day, 5 GB database, 10 GB of files. Nothing to patch or keep running.

The server, under `/api`:
- `POST /reports`: a reader selected text in a book and reported an error (book id, chapter, block, printed page,
  the selected text, the text around it, the reader's correction).
- `POST /uploads`, then per file `POST /uploads/<id>/files`, `PUT /uploads/<id>/files/<file>/<n>` (8 MB pieces),
  `POST /uploads/<id>/files/<file>/done`: a reader sends a missing textbook (PDF or photos, up to 500 MB a file).
- `GET /admin` (so elkitep.com/api/admin): a page to read reports (mark them fixed or not an error) and download uploaded files.
- `GET /admin/reports?status=new` with `Authorization: Bearer <ADMIN_KEY>`: the reports as JSON, for fixing books.

Readers need no account. Each reader may send 60 reports and 10 uploads an hour (counted by a salted hash of the
IP address; addresses themselves are not stored).

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
