#!/usr/bin/env python3
"""Add to site/ministry.json the address where each approved book can be read online ("u"), for the library's
placeholder rows of books that are not on the site yet (their "Оригинал" button).

Source: the availability research of 2026-10-01 (research/availability/availability_links.csv in the project files:
one row per copy found, with its site, whether it is the whole book and which edition).
Picked per book: the whole book before a part or sample, the approved edition before another one, official sites
(the ministry's kitep.edu.kg and stem.edu.gov.kg, publishers) before others. Unofficial copies of Russian publishers'
books (lib.uchebnik.academy, obuchalka.org and the like) and our own reader are never linked.

Usage: python3 tools/ministry_links.py [/mnt/project-files/research/availability/availability_links.csv]
"""
import csv, json, os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'site')
LINKS = '/mnt/project-files/research/availability/availability_links.csv'
SCHOOL = {'Kyrgyz-medium': 'ky', 'Russian-medium': 'ru'}
SITES = ['kitep.edu.kg (ministry)', 'stem.edu.gov.kg (ministry)', 'arcus.kg (publisher)', 'arcus.kg', 'prosv.ru (publisher)',
         'jasulib.org.kg', 'mektep.o.kg', 'okuma.kg', 'bilim.akipress.org', 'biblioteka.kg', 'bizdin.kg', 'bizdin.kg app',
         'new.bizdin.kg', 'search.rsl.ru', 'web.archive.org']   # in this order; any other site is not linked


def key(s, g, t, a):
    return (s, str(g), t.strip(), a.strip())


def main(path):
    best = {}
    for l in csv.DictReader(open(path, encoding='utf-8')):
        if l['Site'] not in SITES or not l['Link'].startswith('https://'):
            continue
        rank = (l['Full book'] != 'yes', l['Edition'] != 'approved edition', SITES.index(l['Site']))
        k = key(SCHOOL.get(l['School'], l['School']), l['Grade'], l['Title'], l['Authors'])
        if k not in best or rank < best[k][0]:
            best[k] = (rank, l['Link'])
    p = os.path.join(ROOT, 'ministry.json')
    rows = json.load(open(p, encoding='utf-8'))
    n = 0
    for r in rows:
        b = best.get(key(r['s'], r['g'], r['t'], r['a']))
        r.pop('u', None)
        if b:
            r['u'] = b[1]; n += 1
    with open(p, 'w', encoding='utf-8') as f:
        f.write('[\n' + ',\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n]\n')
    print(f'{n} of {len(rows)} books have a link')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else LINKS)
