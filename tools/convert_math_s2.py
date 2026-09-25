#!/usr/bin/env python3
"""Maths converter, strategy 2: text where the page is plain text; every region with a drawing is
redrawn as an inline vector picture that keeps its own text as real (selectable, sharp) SVG text.

Usage: python3 convert_math_s2.py /mnt/project-files/pilot-book/<book>.config.json

Unlike strategy 1 (which pulls every sentence out of diagrams and rebuilds tables in HTML), this one
keeps each diagram, worked solution and table exactly as laid out in the book, but as vector
graphics instead of screenshots: they stay sharp at any zoom and cost a few KB. Wide regions are cut at
empty vertical gutters into narrow pieces and stacked, so they fit a phone screen at a readable size.
Plain paragraphs, exercises and headings are real HTML text, as in strategy 1.
"""
import collections, json, os, re, sys

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_layout import Flow, esc, merge_rects, load_config, LETTERS  # noqa: E402
from convert_math import open_doc, page_content, mark_fractions, style_of  # noqa: E402
from convert_math_s1 import (svg_redraw, trim_spans, analyse, photo_areas, Emitter, Saver,  # noqa: E402
                             is_wordy, merge_near)

ONLY = {int(x) for x in os.environ.get("PAGES", "").split(",") if x}
DEBUG = bool(os.environ.get("DEBUG"))


def cut(elems, gy, gx):
    """One level of XY-cut; returns groups or None."""
    for axis, gap in ((1, gy), (0, gx)):
        es = sorted(elems, key=lambda e: e[1][axis])
        groups, cur, end = [], [es[0]], es[0][1][axis + 2]
        for e in es[1:]:
            if e[1][axis] > end + gap:
                groups.append(cur)
                cur = []
            cur.append(e)
            end = max(end, e[1][axis + 2])
        groups.append(cur)
        if len(groups) > 1:
            return groups
    return None


def regions(elems, gy=1.0, gx=10):
    """Reading order; a leaf that holds a drawing becomes one vector region (headings kept out)."""
    if len(elems) <= 1:
        if elems and elems[0][0] == "g":
            return [("fig", elems[0][1], [elems[0]])]
        return elems
    groups = cut(elems, gy, gx) or cut(elems, gy, 1.5)
    if groups:
        return [x for g in groups for x in regions(g, gy, gx)]
    if any(e[0] == "g" for e in elems):
        # sentences stay text; everything else in this leaf is drawn, cut where a sentence runs between
        gs = [e[1] for e in elems if e[0] == "g"]
        out, grp = [], []

        def flush():
            if grp:
                r = pymupdf.Rect(grp[0][1])
                for e in grp[1:]:
                    r |= e[1]
                out.append(("fig", r, list(grp)))
                grp.clear()
        for e in sorted(elems, key=lambda e: (e[1].y0, e[1].x0)):
            is_text = e[0] == "head" or e[0] == "ans" or (
                e[0] == "line" and is_wordy(e[2]) and e[2].size >= 9.5 and
                not any((e[1] & g).get_area() > 0.5 * e[1].get_area() for g in gs))
            if is_text:
                flush()
                out.append(e)
            else:
                grp.append(e)
        flush()
        return out
    return sorted(elems, key=lambda e: (round(e[1].y0 / 4), e[1].x0))


def narrow(rect, members, max_w):
    """Cut a wide region at empty vertical gutters (a / б parts, picture | note); stack the pieces."""
    if rect.width <= max_w or len(members) < 2:
        return [rect]
    for gx in (8,):
        es = sorted(members, key=lambda e: e[1].x0)
        groups, cur, end = [], [es[0]], es[0][1].x1
        for e in es[1:]:
            if e[1].x0 > end + gx:
                groups.append(cur)
                cur = []
            cur.append(e)
            end = max(end, e[1].x1)
        groups.append(cur)
        if len(groups) > 1 and all(max(e[1].x1 for e in g) - min(e[1].x0 for e in g) >= 50 for g in groups):
            out = []
            for g in groups:
                r = pymupdf.Rect(g[0][1])
                for e in g[1:]:
                    r |= e[1]
                out += narrow(r & rect, g, max_w)
            return out
    return [rect]


class VecEmitter(Emitter):
    def run(self, items):
        for kind, rect, obj in items:
            if kind != "ans":
                self.flush_ans()
            if kind == "ans":
                if self.pend_ans and abs(obj["bbox"].y0 - self.pend_ans[-1]["bbox"].y0) > 30:
                    self.flush_ans()
                self.pend_ans.append(obj)
            elif kind == "fig":
                done = getattr(self, "done", [])
                self.done = done
                if any((rect & d).get_area() > 0.6 * rect.get_area() for d in done):
                    continue
                done.append(rect)
                for part in narrow(rect, obj, self.L.get("split_w", 300)):
                    self.flow.raw(self.saver.vector(part))
                self.prev = None
                self.ml_x0 = None
            elif kind in ("line", "head"):
                self.line(obj)
        self.flush_ans()


class VecSaver(Saver):
    def vector(self, clip):
        raster = any((clip & r).get_area() > 0.3 * min(r.get_area(), clip.get_area()) for r in self.rasters)
        if raster:
            b = self.picture(clip)
            return (f'<figure><img data-w="{b["w"]}" data-h="{b["ht"]}" style="width:{b["dw"]}em" '
                    f'src="{b["src"]}" alt=""></figure>')
        svg, c = svg_redraw(self.drawings, self.spans, clip, pad=1.5)
        svg = svg.replace(' xmlns="http://www.w3.org/2000/svg"', "")
        svg = re.sub(r' width="[\d.]+" height="[\d.]+"', f' style="width:{c.width / self.L["body_pt"]:.1f}em"', svg, count=1)
        self.stats["svg"] += 1
        self.stats["svg_bytes"] += len(svg)
        return f'<figure class="vec">{svg}</figure>'

    def prepare_render(self, text_rects):
        super().prepare_render(text_rects)


def main():
    cfg = load_config(sys.argv[1])
    L = cfg["layout"]
    doc = open_doc(cfg["pdf"])
    saver = VecSaver(cfg, doc)
    words = collections.Counter(w.lower() for p in doc for w in re.findall(r"[" + LETTERS + r"]+(?:-[" + LETTERS + r"]+)*", p.get_text()))
    chap_starts = {c["from"]: c for c in cfg["chapters"]}
    chapters = []
    flow = chap = None
    for pi in range(len(doc)):
        if pi in chap_starts:
            if flow:
                flow.close()
                chapters[-1]["blocks"] = flow.blocks
            chap = chap_starts[pi]
            chapters.append({"title": chap["title"], "section": chap.get("section"),
                             "pages": [pi + 1 + cfg["page_offset"], chap["to"] + 1 + cfg["page_offset"]], "sub": [], "blocks": []})
            flow = Flow(cfg, words)
            flow.heading(2, esc(chap["title"]))
        if flow is None or pi > chap["to"] or (ONLY and pi not in ONLY):
            continue
        page = doc[pi]
        flow.pg_mark(pi + 1 + cfg["page_offset"])
        drawings = page.get_drawings()
        page.get_drawings = lambda d=drawings: d
        lines, answers, _ = page_content(page)
        lines = [ln for ln in lines if L["top"] < ln.bbox.y1 and ln.bbox.y0 < L["bottom"] and "kitep" not in ln.text]
        uniq = []
        for ln in lines:
            if not any((u.text == ln.text and (u.bbox & ln.bbox).get_area() > 0.7 * ln.bbox.get_area()) or
                       ((u.bbox & ln.bbox).get_area() > 0.85 * max(u.bbox.get_area(), ln.bbox.get_area()) and
                        (ln.text.replace(" ", "") in u.text.replace(" ", "") or u.text.replace(" ", "") in ln.text.replace(" ", "")))
                       for u in uniq):
                uniq.append(ln)
        lines = uniq
        answers = [a for a in answers if L["top"] < a["bbox"].y1 and a["bbox"].y0 < L["bottom"] + 10]
        kinds = {id(ln): style_of(ln, cfg) for ln in lines}
        for ln in lines:
            if kinds[id(ln)] in ("h3", "title") and ln.bbox.x0 > 200:
                kinds[id(ln)] = None
        lines = [ln for ln in lines if kinds[id(ln)] != "skip"]
        heads = [ln for ln in lines if kinds[id(ln)] in ("ex", "try", "h3", "h4", "title")]
        bars, pieces, boxes, cells = analyse(page, lines, heads, cfg, drawings)
        rasters = [pymupdf.Rect(im["bbox"]) & page.rect for im in page.get_image_info()
                   if 3000 < (pymupdf.Rect(im["bbox"]) & page.rect).get_area() < 0.4 * page.rect.get_area()]
        pa = photo_areas(page, drawings)
        rasters += pa
        saver.set_page(pi, page, drawings, trim_spans(page), rasters)
        if pi == chap["from"] and L.get("header_bottom"):
            hb = L["header_bottom"]
            pieces = [pymupdf.Rect(r.x0, max(r.y0, hb), r.x1, r.y1) for r in pieces + pa if r.y1 > hb + 3]
            boxes = [b for b in boxes if b.y0 >= hb - 2]
            goal = sorted([ln for ln in lines if ln.bbox.y1 <= hb and ln not in heads], key=lambda l: (l.bbox.y0, l.bbox.x0))
            lines = [ln for ln in lines if ln not in goal]
            if goal:
                flow.raw('<p class="goal"><b>%s</b> %s</p>' % (esc(cfg.get("goal_label", "Цель обучения:")), " ".join(g.html() for g in goal)))
        else:
            pieces = pieces + pa
        mark_fractions(page, lines, bars)
        # every drawing (diagram, frame, table grid, speech bubble) is a graphic region
        cellr = [r for r, _ in cells]
        if pi == chap["from"] and L.get("header_bottom"):
            cellr = [r for r in cellr if r.y0 >= L["header_bottom"] - 2]
        graphics = pieces + boxes + cellr
        graphics = [g for g in merge_rects(graphics, 2) if g.get_area() > 150 and g.width > 4 and g.height > 4]
        # labels, formulas and big numbers around a drawing belong to it; nearby drawings join up
        label = [ln for ln in lines if ln not in heads and not (is_wordy(ln) and ln.size >= 9.5)]
        changed = True
        while changed:
            changed = False
            for k, g in enumerate(graphics):
                for ln in label:
                    if not g.contains(ln.bbox) and ln.bbox.intersects(g + (-12, -12, 12, 12)):
                        graphics[k] = g | ln.bbox
                        g = graphics[k]
                        changed = True
            graphics = merge_near(merge_rects(graphics, 4), hgap=22, vgap=10)
        # lines that are ordinary sentences and only brush a frame edge stay outside it
        elems = [("g", g, None) for g in graphics]
        for ln in lines:
            elems.append(("head" if ln in heads else "line", ln.bbox, ln))
        elems += [("ans", a["bbox"], a) for a in answers]
        ordered = regions(elems)
        in_fig = [ln.bbox for k, _, m in ordered if k == "fig" for kk, _, ln in m if kk == "line"]
        saver.prepare_render([e[1] for e in ordered if e[0] == "line"] + [a["bbox"] for a in answers])
        if DEBUG:
            print(pi, [(k, [round(v) for v in r]) for k, r, _ in ordered if k == "fig"])
        VecEmitter(cfg, flow, saver, kinds, chapters, chap, pi).run(ordered)
    if flow:
        flow.close()
        chapters[-1]["blocks"] = flow.blocks
    for c in chapters:
        for b in c["blocks"]:
            b.pop("_h3", None)
    book = {k: cfg[k] for k in ("id", "title", "subtitle", "author", "grade", "lang", "langName", "subject", "year",
                                "publisher", "school", "source", "notes") if k in cfg}
    book.update(format=2, images=saver.images, chapters=chapters)
    with open(os.path.join(saver.out, "book.json"), "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, separators=(",", ":"))
    size = sum(os.path.getsize(os.path.join(saver.imgdir, x)) for x in os.listdir(saver.imgdir))
    print(dict(saver.stats), f"images {size / 1048576:.2f} MB", f"book.json {os.path.getsize(os.path.join(saver.out, 'book.json')) / 1048576:.2f} MB")


if __name__ == "__main__":
    main()
