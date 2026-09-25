#!/usr/bin/env python3
"""Copy converted books into the app and build the library index and single-file books.

Usage: python3 build_books.py /mnt/project-files/pilot-book/kyrgyz-adabiyaty-7 [more book folders...]

For each book folder (output of convert_pdf.py) this:
  * copies book.json and img/ to site/books/<id>/,
  * writes a standalone <id>.html (app + book + pictures in one file, to share via messengers),
  * rebuilds site/books/index.json.
"""
import re
import base64, hashlib, json, os, shutil, sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site")
BOOKS = os.path.join(APP, "books")


def data_uri(path):
    mime = {"webp": "image/webp", "svg": "image/svg+xml", "png": "image/png"}.get(path.rsplit(".", 1)[-1], "image/jpeg")
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def standalone(book, src_dir):
    emb = dict(book)
    emb["chapters"] = []
    for ch in book["chapters"]:
        ch = dict(ch)
        blocks = []
        for b in ch["blocks"]:
            if b["t"] == "img":
                b = dict(b)
                b["src"] = data_uri(os.path.join(src_dir, b["src"]))
            elif 'src="img/' in b.get("h", ""):
                b = dict(b)
                b["h"] = re.sub(r'src="(img/[^"]+)"', lambda m: 'src="' + data_uri(os.path.join(src_dir, m.group(1))) + '"', b["h"])
            blocks.append(b)
        ch["blocks"] = blocks
        emb["chapters"].append(ch)
    emb["images"] = []
    with open(os.path.join(APP, "style.css"), encoding="utf-8") as f:
        css = f.read()
    with open(os.path.join(APP, "app.js"), encoding="utf-8") as f:
        js = f.read()
    data = json.dumps(emb, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    title = book["title"] + (f" {book['grade']}" if book.get("grade") else "")
    return f"""<!doctype html>
<html lang="{book.get('lang', 'ru')}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div id="app"></div>
<script>window.EMBEDDED_BOOK = {data};</script>
<script>{js}</script>
</body>
</html>
"""


def main(dirs):
    index_path = os.path.join(BOOKS, "index.json")
    index = []
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
    for src in dirs:
        with open(os.path.join(src, "book.json"), encoding="utf-8") as f:
            book = json.load(f)
        bid = book["id"]
        dst = os.path.join(BOOKS, bid)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        os.makedirs(dst)
        shutil.copy(os.path.join(src, "book.json"), dst)
        shutil.copytree(os.path.join(src, "img"), os.path.join(dst, "img"))
        single = f"{bid}.html"
        with open(os.path.join(dst, single), "w", encoding="utf-8") as f:
            f.write(standalone(book, src))
        h = hashlib.sha1()
        size = 0
        for root, _, files in os.walk(dst):
            for fn in sorted(files):
                if fn == single:
                    continue
                p = os.path.join(root, fn)
                size += os.path.getsize(p)
                with open(p, "rb") as f:
                    h.update(f.read())
        school = book.get("school") or ""
        if school not in ("ru", "ky"):
            school = "ru" if ("русск" in school.lower() or "орус" in school.lower()) else ("ky" if school else None)
        entry = {"id": bid, "v": h.hexdigest()[:10], "title": book["title"], "subtitle": book.get("subtitle"), "school": school,
                 "author": book.get("author"), "year": book.get("year"), "grade": book.get("grade"),
                 "langName": book.get("langName"), "size": size, "standalone": single}
        index = [e for e in index if e["id"] != bid] + [entry]
        print(f"{bid}: {size / 1048576:.2f} MB online, single file {os.path.getsize(os.path.join(dst, single)) / 1048576:.2f} MB")
    # library order: grade, then school, then subject
    def grade_key(e):
        m = re.match(r"\d+", str(e.get("grade") or ""))
        return int(m.group(0)) if m else 99
    index.sort(key=lambda e: (grade_key(e), e.get("school") or "", e.get("title") or ""))
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1:])
