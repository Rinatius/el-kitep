# Мектеп китептери: mobile textbook reader

A small offline-first web app for reading Kyrgyz school textbooks on cheap Android phones.
Plain HTML, CSS and JavaScript. No build step, no libraries, no external requests.

Live: https://rinatius.github.io/el-kitep/

## Layout
- `site/`: the app that gets published (index.html, style.css, app.js, sw.js, manifest, icons, books/).
- `site/books/<id>/`: book.json, img/, and a single-file `<id>.html` per book.
- `tools/`: the PDF converters and `build_books.py`.
- `.github/workflows/pages.yml`: publishes `site/` to GitHub Pages on every push that changes it.

## Try it locally
    cd site && python3 -m http.server 8080
    open http://localhost:8080 on a phone or in desktop Chrome's phone mode

HTTPS (or localhost) is needed for the offline download (service worker).

## What the reader does
- Library page with each book: Read / Continue, "download for offline reading" (Cache Storage), and
  "save as one file" (books/<id>/<id>.html, one HTML file that works without internet; can be sent via WhatsApp/Telegram).
- Pages you swipe left/right (or tap the left/right edge); tap the middle for the menu.
- Font size, 4 backgrounds (white, sepia, dark, high contrast), serif/sans, line spacing, Kyrgyz/Russian interface.
- Contents with sections, authors and every poem/story; "go to textbook page N" so "open page 45" in class still works.
  Original page numbers appear as small grey badges in the text.
- Reading position is remembered per book.
- Tap a picture (middle of the screen) to see it full screen; tap it again to enlarge 2.5x and scroll around.

## Adding a book
There are two converters (both need `pip install pymupdf pillow`):
- `tools/convert_pdf.py <config>` for scans with an OCR text layer (e.g. pilot-book/kyrgyz-adabiyaty-7.config.json).
  Output: book.json, img/, corrections.tsv.
- `tools/convert_layout.py <config>` for typeset (born-digital) PDFs such as the new kitep.edu.kg editions
  (e.g. pilot-book/chelovek-i-obshchestvo-7.config.json). It copies the real text, crops pictures and diagrams
  (with the labels drawn on them) as WebP, turns framed boxes into text boxes and ruled tables into HTML tables.
  The config's "layout" block gives the text column, font sizes and colours; "chapters" gives page ranges.
Then `python3 tools/build_books.py <output folder> [more folders]` copies books into site/books/ and updates site/books/index.json.

Books in the library: Кыргыз адабияты 7 (Алымов, Муратов 2015), Человек и общество 7 (Азимова и др. 2024), Математика 7 часть 1 (kitep.edu.kg/book/444, version 3: pages re-typeset).

## Maths books (convert_math.py)

`python3 tools/convert_math.py <pilot-book>/matematika-7.config.json` converts the new kitep maths books (Lato/Bahnschrift layout).
Running text, exercise lists and one-line formulas stay text (fractions become HTML fractions from the PDF's fraction bars,
а/б/в badges become small labels). Number lines, diagrams, photos and labelled pictures are cropped (recursive XY-cut of the page).
Busy worked solutions (white cards with bar models or fractions) are kept whole as one picture; tap to zoom.
Upside-down answers under «Попробуйте!» become tap-to-open «Ответ». Tables with text in most cells become HTML tables.
Pictures carry `dw` (display width in em, 10 pt = 1 em) so their text matches the body size when there is room.
Debug: `PAGES=4,5 DEBUG=1 python3 tools/convert_math.py ...` (page indexes are 0-based; printed page = index + 6 for part 1).
