#!/usr/bin/env python3
"""Link the books on the site to the Ministry's list of approved textbooks (site/ministry.json).

site/ministry.json has one row per book on the Ministry's list for 2026-27 (edu.gov.kg/posts/5164, 373 books):
  s     school: "ky" (Kyrgyz-medium) or "ru" (Russian-medium)
  g     grade
  subj, t, a, y   subject, title, authors and year as the list gives them
  f     what we found online (research/availability, 2026-10-01): "full" = the whole book somewhere,
        "part" = only a sample or part, behind a login or payment, or only in the other language; "none" = nowhere
  ids   ids of our books (site/books/index.json) that are this book, in the listed or another edition by the same authors
  no    optional: ids that are NOT this book although the matching below would add them (e.g. a co-author of
        another book on the same subject); set by hand, never removed by this script
The statistics page (#/stats) and the "N of M" counts on the library page come from it.

Run after adding books:  python3 tools/ministry_map.py
It adds every book whose authors and title match a row of its school and grade (any year), keeps ids added by hand
that still exist, skips ids listed in the row's "no", and prints the books it could not place (books not on the list, or names that differ: add those
by hand to the right row's "ids" if they are the same book).
"""
import json, os, re
from difflib import SequenceMatcher

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'site')
TR = str.maketrans('ёөүңһіїєўЁӨҮҢ', 'еоуннииеуЕОУН')
STOP = set('учебник адаптирован адаптированный и др авторы автор под редакцией ред жб ж.б составитель составители коллектив'.split())


def norm(s):
    return re.sub(r'\s+', ' ', str(s or '').lower().translate(TR))


def surnames(a):
    a = re.split(r'[Уу]чебник адаптир|[Аа]даптир', str(a or ''))[0]
    return [norm(w) for w in re.findall(r'[A-Za-zА-Яа-яЁёӨөҮүҢң\-]{3,}', a) if w.lower() not in STOP and w[0].isupper()]


def grades(s):
    m = [int(x) for x in re.findall(r'\d+', str(s))]
    return list(range(m[0], m[-1] + 1)) if m else []


def same(row, b):
    if row['s'] != b.get('school') or row['g'] not in grades(b['grade']):
        return False
    text = norm(b['author'] + ' ' + b['title'] + ' ' + b.get('subtitle', ''))
    if not any((s[:6] if len(s) > 6 else s) in text for s in surnames(row['a'])):
        return False
    lt = norm(b['title'])
    at = re.sub(r'\(.*?\)|\d+\s*[–-]\s*\d+[^ ]*|кл\.?|класс\w*', '', norm(row['t'])).strip(' .:')
    return at in lt or lt in at or SequenceMatcher(None, at, lt).ratio() >= 0.6


def main():
    rows = json.load(open(os.path.join(ROOT, 'ministry.json')))
    books = json.load(open(os.path.join(ROOT, 'books', 'index.json')))
    have = {b['id'] for b in books}
    for r in rows:
        r['ids'] = sorted(({i for i in r['ids'] if i in have} | {b['id'] for b in books if same(r, b)}) - set(r.get('no', [])))
    with open(os.path.join(ROOT, 'ministry.json'), 'w') as f:
        f.write('[\n' + ',\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n]\n')
    used = {i for r in rows for i in r['ids']}
    on = sum(1 for r in rows if r['ids'])
    print('%d of %d listed books are on the site (%d of our %d books placed)' % (on, len(rows), len(used), len(books)))
    for b in books:
        if b['id'] not in used:
            print('  not on the list:', b['id'], b['grade'], b['year'], b['author'], '-', b['title'])


if __name__ == '__main__':
    main()
