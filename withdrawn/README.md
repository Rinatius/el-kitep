# Books taken off the site

Books we took off elkitep.com under our principles (site: «Наши принципы», `#/principles/2`). Their files are kept here,
outside `site/`, so they are not deployed (neither GitHub Pages nor the Cloudflare Worker serves anything outside `site/`).

Each book keeps its entry in `site/books/index.json` with an `"off"` field, so the library still shows its card: why it was
taken off, where the printed book can be bought, and the state-printed book of the Ministry's list that replaces it
(see `offRow` in `site/app.js`). Statistics count the Ministry's row as «Убраны по нашим принципам», not as on the site.

To put a book back: `git mv withdrawn/books/<id> site/books/<id>` and delete the `"off"` field from its index entry.

| id | taken off |
|---|---|
| ru-english-10 | 2026-11-04 |
| ru-matematika-1-moro-1, ru-matematika-1-moro-2 | 2026-11-04 |
| ru-matematika-3-moro-1, ru-matematika-3-moro-2 | 2026-11-04 |
| ru-matematika-4-moro-1, ru-matematika-4-moro-2 | 2026-11-04 |
