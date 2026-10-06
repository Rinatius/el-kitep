#!/usr/bin/env python3
"""Pages for search engines (Google, Yandex), written into dist/ by tools/build_cloudflare.sh.

The reader is one page that draws everything with JavaScript, so search engines see almost nothing in it. This adds
plain pages that need no script, in the language of each school:
  /ky/, /ru/            the books for Kyrgyz-medium and Russian-medium schools, by grade
  /book/<id>/           one page per book: title, authors, grade, contents, the beginning of the text, a "Read" button
                        that opens the book in the reader (/#/read/<id>)
  /sitemap.xml          every page above, for Search Console and Yandex Webmaster
Only for elkitep.com (the old github.io copy points search engines here with rel=canonical in site/index.html).

Usage: python3 tools/build_seo.py dist
"""
import html, json, os, re, sys
from datetime import date

SITE = 'https://elkitep.com'
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'site')

T = {
    'ky': {'app': 'Мектеп китептери', 'school': {'ky': 'Кыргыз тилинде окутуу', 'ru': 'Окутуу орус тилинде'}, 'grade': '{}-класс', 'part': '{}-бөлүк', 'other_school': 'окутуу орус тилинде', 'read': 'Окуу',
           'catalog': 'Мектеп китептери онлайн: окутуу кыргыз тилинде жүргүзүлгөн мектептер үчүн окуу китептери',
           'catalog_short': 'Кыргыз тилинде окутулган мектептер үчүн окуу китептери',
           'catalog_sub': 'Кыргызстандын окуу китептери телефондо окууга ыңгайлуу. Жүктөп алгандан кийин интернетсиз иштейт. Акысыз, каттоосуз.',
           'other': 'Русский язык обучения: учебники', 'all': 'Бардык китептер', 'contents': 'Мазмуну', 'start': 'Китептин башталышы',
           'online': 'онлайн окуу', 'desc': '{t}, {g}: окуу китеби онлайн. Телефондо окууга ыңгайлуу, жүктөп алгандан кийин интернетсиз иштейт. {a}',
           'exact': 'Так текст (санариптик нускадан)', 'proofread': 'Скан, ЖИ текшерген', 'ocr': 'Скан, текшерилген эмес',
           'free': 'Акысыз, каттоосуз.', 'more': 'Китепти толугу менен окуу'},
    'ru': {'app': 'Школьные учебники', 'school': {'ky': 'Обучение на кыргызском языке', 'ru': 'Обучение на русском языке'}, 'grade': '{} класс', 'part': 'часть {}', 'other_school': 'обучение на кыргызском языке', 'read': 'Читать',
           'catalog': 'Школьные учебники Кыргызстана онлайн: для школ с русским языком обучения',
           'catalog_short': 'Учебники для школ с русским языком обучения',
           'catalog_sub': 'Учебники Кыргызстана, удобные для телефона. Работают без интернета после скачивания. Бесплатно и без регистрации.',
           'other': 'Кыргыз тилинде окутуу: окуу китептери', 'all': 'Все учебники', 'contents': 'Содержание', 'start': 'Начало книги',
           'online': 'читать онлайн', 'desc': '{t}, {g}: учебник онлайн. Удобно читать на телефоне, после скачивания работает без интернета. {a}',
           'exact': 'Точный текст (из цифровой версии)', 'proofread': 'Скан, вычитан ИИ', 'ocr': 'Скан, без вычитки',
           'free': 'Бесплатно и без регистрации.', 'more': 'Читать книгу целиком'},
}
CSS = """body{font:17px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;margin:0 auto;max-width:720px;padding:16px;color:#1b1b1b;background:#fff}
a{color:#1f6feb}header a{text-decoration:none;font-weight:600}h1{font-size:26px;line-height:1.25;margin:18px 0 6px}h2{font-size:20px;margin:26px 0 8px}
.m{color:#6b6b6b;font-size:15px}.btn{display:inline-block;background:#1f6feb;color:#fff;padding:12px 26px;border-radius:12px;text-decoration:none;font-weight:600;margin:14px 0}
img{max-width:100%;height:auto;border-radius:8px;border:1px solid #e3e3e3}ul{padding-left:20px}li{margin:4px 0}.ex p{margin:.5em 0}
nav a{margin-right:14px}.g a{white-space:nowrap;margin-right:10px}footer{margin-top:32px;font-size:14px;color:#6b6b6b}
@media (prefers-color-scheme:dark){body{background:#111315;color:#d8d8d8}a{color:#6ea8ff}.btn{background:#6ea8ff;color:#0b0b0b}img{border-color:#2a2d31}}"""


def e(s):
    return html.escape(str(s or ''), quote=True)


def text(h):
    h = re.sub(r'<span class="pg"[^>]*>.*?</span>', ' ', h or '')
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h))).strip()


def grades(g):
    m = [int(x) for x in re.findall(r'\d+', str(g))]
    return list(range(m[0], m[-1] + 1)) if m else []


def page(lang, title, desc, path, body, alternates=None, extra=''):
    alt = ''.join(f'<link rel="alternate" hreflang="{k}" href="{SITE}{v}">' for k, v in (alternates or {}).items())
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}"><link rel="canonical" href="{SITE}{path}">{alt}
<meta property="og:type" content="website"><meta property="og:site_name" content="Мектеп китептери / Школьные учебники">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{SITE}{path}">
<link rel="icon" href="/icons/icon.svg" type="image/svg+xml">{extra}<style>{CSS}</style></head>
<body>{body}</body></html>
"""


def header(ui):
    t = T[ui]
    return f'<header><a href="/">📚 {e(t["app"])}</a></header>'


def footer(ui):
    t = T[ui]
    return f'<footer><nav><a href="/ky/">{e(T["ky"]["catalog_short"])}</a><a href="/ru/">{e(T["ru"]["catalog_short"])}</a></nav><p>{e(t["free"])}</p></footer>'


def part(b):
    m = re.search(r'(\d)\s*-?\s*я?\s*част|част\w*\s*(\d)|(\d)\s*-\s*(?:бөлүк|китеп)|(?:бөлүк|китеп)\s*(\d)', b.get('subtitle') or '')
    return next((x for x in m.groups() if x), None) if m else None


def full_name(b):
    """Title, grade, part, and the school when the book is not in its school's language (Кыргыз тили for Russian-medium schools)."""
    t = T[b['_lang']]
    g = t['grade'].format(b.get('grade')) if b.get('grade') else ''
    return b['title'] + (', ' + g if g else '') + (', ' + t['part'].format(part(b)) if part(b) else '') + \
        (f' ({t["other_school"]})' if b.get('school') != b['_lang'] else '')


def book_page(b, book, name):
    # in the language of the book's text; the school (language of instruction) is said in it too
    ui = book.get('lang') if book.get('lang') in T else b.get('school') if b.get('school') in T else 'ru'
    school = b.get('school') if b.get('school') in T else ui
    t = T[ui]
    g = t['grade'].format(b.get('grade')) if b.get('grade') else ''
    authors = b.get('author') or ''
    desc = t['desc'].format(t=b['title'], g=g, a=(authors + (', ' + str(b['year']) if b.get('year') else '')).strip(', '))
    chapters = [c.get('title') for c in book.get('chapters', []) if c.get('title')]
    # the beginning of the text: real paragraphs, up to about 2,500 characters
    ex, n = [], 0
    for c in book.get('chapters', []):
        for bl in c.get('blocks', []):
            s = text(bl.get('h')) if bl.get('t') in ('p', 'h3') else ' '.join(bl.get('l', [])) if bl.get('t') == 'v' else ''
            if len(s) < 40 and bl.get('t') != 'h3':
                continue
            ex.append(('h3' if bl.get('t') == 'h3' else 'p', s)); n += len(s)
            if n > 2500:
                break
        if n > 2500:
            break
    # the first picture, when it is on the first pages (the cover); pictures are served from img.elkitep.com/<id>/img/...
    cover = next((i for i in book.get('images', [])[:1] if re.search(r'/p00[1-3]\b|/p00[1-3]-', i)), None)
    img = f'<p><img src="https://img.elkitep.com/{e(b["id"])}/{e(cover)}" alt="{e(name)}" width="320" loading="lazy"></p>' if cover else ''
    q = t.get(b.get('quality') or '', '')
    ld = {'@context': 'https://schema.org', '@type': 'Book', 'name': b['title'], 'url': f'{SITE}/book/{b["id"]}/',
          'inLanguage': book.get('lang') or ui, 'bookFormat': 'https://schema.org/EBook', 'isAccessibleForFree': True,
          'educationalLevel': g, 'learningResourceType': 'textbook'}
    if authors:
        ld['author'] = [{'@type': 'Person', 'name': a.strip()} for a in re.split(r',(?![^()]*\))', authors) if a.strip() and a.strip() not in ('и др.', 'ж.б.')]
    if b.get('year'):
        ld['datePublished'] = str(b['year'])
    extra = '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace('</', '<\\/') + '</script>'
    body = (header(ui) + f'<main><h1>{e(name)}</h1>' + (f'<p>{e(b.get("subtitle"))}</p>' if b.get('subtitle') else '') +
            f'<p class="m">{e(authors)}{", " + e(b["year"]) if b.get("year") else ""} · {e(t["school"][school])}' + (f' · {e(q)}' if q else '') + '</p>' +
            f'<a class="btn" href="/#/read/{e(b["id"])}">{e(t["read"])}</a>' + img +
            (f'<h2>{e(t["contents"])}</h2><ul>' + ''.join(f'<li>{e(c)}</li>' for c in chapters) + '</ul>' if chapters else '') +
            (f'<h2>{e(t["start"])}</h2><div class="ex">' + ''.join(f'<{k}>{e(s)}</{k}>' for k, s in ex) + '</div>' +
             f'<p><a class="btn" href="/#/read/{e(b["id"])}">{e(t["more"])}</a></p>' if ex else '') +
            f'<p><a href="/{school}/#g{grades(b.get("grade"))[0] if grades(b.get("grade")) else ""}">{e(t["all"])}: {e(g)}</a></p></main>' + footer(ui))
    return page(book.get('lang') or ui, f'{name}: {t["online"]} | {t["app"]}', desc, f'/book/{b["id"]}/', body, extra=extra)


def catalog(ui, books):
    t = T[ui]
    mine = [b for b in books if b.get('school') == ui]
    by = {}
    for b in mine:
        for g in grades(b.get('grade'))[:1]:
            by.setdefault(g, []).append(b)
    body = header(ui) + f'<main><h1>{e(t["catalog_short"])}</h1><p>{e(t["catalog_sub"])}</p>'
    body += '<p class="g">' + ''.join(f'<a href="#g{g}">{e(t["grade"].format(g))}</a>' for g in sorted(by)) + '</p>'
    for g in sorted(by):
        body += f'<h2 id="g{g}">{e(t["grade"].format(g))}</h2><ul>' + ''.join(
            f'<li><a href="/book/{e(b["id"])}/">{e(b["title"])}{", " + e(T[b["_lang"]]["part"].format(part(b))) if part(b) else ""}</a> <span class="m">{e(b.get("author"))}{", " + e(b["year"]) if b.get("year") else ""}</span></li>'
            for b in sorted(by[g], key=lambda b: (b['title'], part(b) or '', -int(b.get('year') or 0)))) + '</ul>'
    other = 'ru' if ui == 'ky' else 'ky'
    body += f'<p><a href="/{other}/">{e(t["other"])}</a></p></main>' + footer(ui)
    alts = {'ky': '/ky/', 'ru': '/ru/', 'x-default': '/'}
    return page(ui, t['catalog'], t['catalog_sub'], f'/{ui}/', body, alternates=alts)


def main(dist):
    books = json.load(open(os.path.join(ROOT, 'books', 'index.json')))
    full = {}
    for b in books:
        full[b['id']] = json.load(open(os.path.join(ROOT, 'books', b['id'], 'book.json')))
        b['_lang'] = full[b['id']].get('lang') if full[b['id']].get('lang') in T else b.get('school') if b.get('school') in T else 'ru'
    names = {b['id']: full_name(b) for b in books}
    seen = {}
    for b in books:
        seen.setdefault(names[b['id']], []).append(b)
    for same in seen.values():   # other editions of the same book: add the first author and the year
        if len(same) > 1:
            for b in same:
                first = re.split(r',', b.get('author') or '')[0].strip()
                names[b['id']] += ' — ' + ', '.join(x for x in (first, str(b.get('year') or '')) if x)
    for b in books:
        book = full[b['id']]
        os.makedirs(os.path.join(dist, 'book', b['id']), exist_ok=True)
        with open(os.path.join(dist, 'book', b['id'], 'index.html'), 'w') as f:
            f.write(book_page(b, book, names[b['id']]))
    for ui in ('ky', 'ru'):
        os.makedirs(os.path.join(dist, ui), exist_ok=True)
        with open(os.path.join(dist, ui, 'index.html'), 'w') as f:
            f.write(catalog(ui, books))
    today = date.today().isoformat()
    urls = ['/', '/ky/', '/ru/'] + [f'/book/{b["id"]}/' for b in books]
    with open(os.path.join(dist, 'sitemap.xml'), 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
                ''.join(f'<url><loc>{SITE}{u}</loc><lastmod>{today}</lastmod></url>\n' for u in urls) + '</urlset>\n')
    print(f'seo: {len(books)} book pages, 2 catalogs, sitemap with {len(urls)} addresses')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'dist')
