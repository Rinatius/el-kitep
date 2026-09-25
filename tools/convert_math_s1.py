#!/usr/bin/env python3
"""Maths converter, strategy 1: rebuild the page as real text; redraw diagrams as small SVGs.

Usage: python3 convert_math_s1.py /mnt/project-files/pilot-book/<book>.config.json

Differences from convert_math.py (which cropped busy areas as raster pictures):
  * every line of text stays text, also inside worked solutions: formulas keep their line
    breaks and their horizontal alignment ("= 3 1/2" under the expression);
  * framed notes, speech bubbles and side notes become text boxes;
  * grids of coloured cells become HTML tables;
  * number lines, bar models, graphs and arrows are redrawn as SVG from the PDF's own vector
    data (sharp at any zoom, a few KB each), with their small labels inside;
  * only photos and drawings made of raster images are cropped as WebP (at high resolution).
"""
import collections, html as htmlmod, json, os, re, sys

import pymupdf
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_layout import Flow, esc, merge_rects, load_config, LETTERS, SENT_END  # noqa: E402
from convert_math import (open_doc, page_content, mark_fractions, style_of, is_prose, is_math_line, clean,  # noqa: E402
                          MLine, is_badge, is_number_badge, light, CYR_WORD)

ONLY = {int(x) for x in os.environ.get("PAGES", "").split(",") if x}
DEBUG = bool(os.environ.get("DEBUG"))


def hexcol(c):
    if c is None:
        return "none"
    if isinstance(c, int):
        return "#%06x" % c
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in c[:3])


def f1(v):
    s = "%.1f" % v
    return s[:-2] if s.endswith(".0") else s


# ---------------------------------------------------------------- SVG redraw

def path_d(items, ox, oy):
    d, cur = [], None
    for it in items:
        op = it[0]
        if op == "l":
            p, q = it[1], it[2]
            if cur is None or abs(cur.x - p.x) > 0.01 or abs(cur.y - p.y) > 0.01:
                d.append(f"M{f1(p.x - ox)} {f1(p.y - oy)}")
            d.append(f"L{f1(q.x - ox)} {f1(q.y - oy)}")
            cur = q
        elif op == "c":
            p, c1, c2, q = it[1], it[2], it[3], it[4]
            if cur is None or abs(cur.x - p.x) > 0.01 or abs(cur.y - p.y) > 0.01:
                d.append(f"M{f1(p.x - ox)} {f1(p.y - oy)}")
            d.append(f"C{f1(c1.x - ox)} {f1(c1.y - oy)} {f1(c2.x - ox)} {f1(c2.y - oy)} {f1(q.x - ox)} {f1(q.y - oy)}")
            cur = q
        elif op == "re":
            r = it[1]
            d.append(f"M{f1(r.x0 - ox)} {f1(r.y0 - oy)}h{f1(r.width)}v{f1(r.height)}h{f1(-r.width)}Z")
            cur = None
        elif op == "qu":
            q = it[1]
            d.append(f"M{f1(q.ul.x - ox)} {f1(q.ul.y - oy)}L{f1(q.ur.x - ox)} {f1(q.ur.y - oy)}"
                     f"L{f1(q.lr.x - ox)} {f1(q.lr.y - oy)}L{f1(q.ll.x - ox)} {f1(q.ll.y - oy)}Z")
            cur = None
    return "".join(d)


def svg_redraw(drawings, spans, clip, pad=3):
    """SVG of the vector drawings and text inside clip (coordinates in PDF points)."""
    c = pymupdf.Rect(clip.x0 - pad, clip.y0 - pad, clip.x1 + pad, clip.y1 + pad)
    out = []
    for dr in drawings:
        r = pymupdf.Rect(dr["rect"])
        if not r.intersects(c) or r.get_area() > 4 * c.get_area():
            continue
        if dr.get("fill") is not None and max(dr["fill"]) < 0.1 and (dr.get("fill_opacity") or 1) < 0.6 and "s" not in dr["type"]:
            continue  # soft shadow (drawn with a blur mask in the PDF)
        d = path_d(dr["items"], c.x0, c.y0)
        if not d:
            continue
        if dr.get("closePath") and not d.endswith("Z"):
            d += "Z"
        a = [f'd="{d}"']
        fill, col = dr.get("fill"), dr.get("color")
        if "f" in dr["type"] and fill is not None:
            a.append(f'fill="{hexcol(fill)}"')
            if (dr.get("fill_opacity") or 1) < 0.99:
                a.append(f'fill-opacity="{dr["fill_opacity"]:.2f}"')
            if dr.get("even_odd"):
                a.append('fill-rule="evenodd"')
        else:
            a.append('fill="none"')
        if "s" in dr["type"] and col is not None:
            a.append(f'stroke="{hexcol(col)}" stroke-width="{f1(dr.get("width") or 1)}"')
            if (dr.get("stroke_opacity") or 1) < 0.99:
                a.append(f'stroke-opacity="{dr["stroke_opacity"]:.2f}"')
            dash = dr.get("dashes") or ""
            m = re.match(r"\[\s*([\d.\s]+)\]", dash)
            if m and m.group(1).strip():
                a.append(f'stroke-dasharray="{m.group(1).strip()}"')
            if dr.get("lineCap") and max(dr["lineCap"]) == 1:
                a.append('stroke-linecap="round"')
        out.append("<path " + " ".join(a) + "/>")
    for sp in spans:
        t = clean(sp["text"]).replace(" ", " ").strip()
        if not t:
            continue
        b = pymupdf.Rect(sp["bbox"])
        ctr = pymupdf.Point((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)
        if not c.contains(ctr):
            continue
        f = sp["font"]
        st = []
        if "Italic" in f:
            st.append('font-style="italic"')
        if any(k in f for k in ("Bold", "Black", "SemiBold", "Heavy")):
            st.append('font-weight="bold"')
        fam = "Bahnschrift, 'Arial Narrow', Roboto, Arial, sans-serif" if f.startswith("Bahnschrift") else "Lato, Roboto, Arial, sans-serif"
        x, y = sp["origin"]
        dirx, diry = sp.get("_dir", (1, 0))
        tr = ""
        if abs(dirx - 1) > 0.02:
            import math
            ang = math.degrees(math.atan2(diry, dirx))
            tr = f' transform="rotate({f1(ang)} {f1(x - c.x0)} {f1(y - c.y0)})"'
        width = b.width if abs(dirx - 1) < 0.02 else b.height
        tl = f' textLength="{f1(width)}" lengthAdjust="spacingAndGlyphs"' if len(t) > 1 and width > 2 else ""
        lead = len(sp["text"]) - len(sp["text"].lstrip())
        if lead and len(t) > 0:
            x = b.x0 + (b.width - width) if False else x
        out.append(f'<text x="{f1(x - c.x0)}" y="{f1(y - c.y0)}" font-size="{f1(sp["size"])}" fill="{hexcol(sp["color"])}" '
                   f'font-family="{fam}" {" ".join(st)}{tl}{tr}>{htmlmod.escape(t)}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {f1(c.width)} {f1(c.height)}" '
            f'width="{f1(c.width)}" height="{f1(c.height)}">' + "".join(out) + "</svg>"), c


def all_spans(page):
    """All text spans with their line direction (for SVG labels)."""
    res = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            for s in l["spans"]:
                if s["text"].strip() and "kitep" not in s["text"]:
                    s = dict(s)
                    s["_dir"] = l["dir"]
                    # the span's origin is on the baseline of its first glyph; trim leading blanks
                    if s["text"] != s["text"].lstrip() and l["dir"][0] > 0.9:
                        chars = None
                    res.append(s)
    return res


def trim_spans(page):
    """Spans re-read char by char so leading blanks don't shift the SVG labels."""
    res = []
    for b in page.get_text("rawdict")["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            for s in l["spans"]:
                chars = [ch for ch in s["chars"]]
                txt = "".join(ch["c"] for ch in chars)
                if not txt.strip() or "kitep" in txt:
                    continue
                k = 0
                while k < len(chars) and not chars[k]["c"].strip():
                    k += 1
                j = len(chars)
                while j > k and not chars[j - 1]["c"].strip():
                    j -= 1
                cs = chars[k:j]
                bb = pymupdf.Rect(cs[0]["bbox"])
                for ch in cs[1:]:
                    bb |= pymupdf.Rect(ch["bbox"])
                res.append({"text": "".join(ch["c"] for ch in cs), "font": s["font"], "size": s["size"], "color": s["color"],
                            "bbox": tuple(bb), "origin": cs[0]["origin"], "_dir": l["dir"]})
    return res


# ---------------------------------------------------------------- page analysis

WORD3 = re.compile(r"[А-Яа-яЁёҢңӨөҮү]{3,}")


def is_wordy(ln):
    return len(WORD3.findall(ln.text)) >= 2 and len(ln.text) >= 20


def rect_like(dr):
    its = dr["items"]
    return all(i[0] in ("re", "qu") for i in its) or (len(its) <= 8 and all(i[0] in ("l", "c") for i in its))


def analyse(page, lines, heads, cfg, drawings):
    """Split drawings into fraction bars, text boxes (containers), grid tables and diagram pieces."""
    L = cfg["layout"]
    body = pymupdf.Rect(0, L["top"], page.rect.width, L["bottom"])
    white_spans = [sp for ln in lines for sp in ln.spans if sp["color"] == 0xffffff and sp["text"].strip()]
    bars, pieces, boxes, cells, decor = [], [], [], [], []
    for dr in drawings:
        r = pymupdf.Rect(dr["rect"]) & page.rect
        fill, stroke = dr.get("fill"), dr.get("color")
        if (dr.get("fill_opacity") or 1) < 0.05:
            fill = None
        if not dr.get("width") and dr["type"] == "s":
            stroke = None
        if r.height < 1.0 and 3 < r.width < 70 and stroke is not None and max(stroke) < 0.4:
            bars.append(r)
            continue
        if r.is_empty and not (r.width > 3 or r.height > 3):
            continue
        if not r.intersects(body) or r.get_area() > 0.4 * page.rect.get_area():
            continue
        area = r.get_area()
        if fill is not None and light(fill) and stroke is None and area > 40000:
            continue  # panel background
        if fill is not None and min(fill) > 0.97 and stroke is None and area > 4000:
            continue  # white card behind a worked solution
        if fill is not None and max(fill) < 0.6 and any(
                (pymupdf.Rect(sp["bbox"]) & r).get_area() > 0.6 * pymupdf.Rect(sp["bbox"]).get_area() for sp in white_spans):
            continue  # dark tab or badge behind white text
        if r.width < 18 and r.height < 18 and any(
                len(sp["text"].strip()) == 1 and r.contains(pymupdf.Point((sp["bbox"][0] + sp["bbox"][2]) / 2, (sp["bbox"][1] + sp["bbox"][3]) / 2 + 2))
                for ln in lines for sp in ln.spans):
            continue  # round badge with a letter
        if fill is not None and any(r.intersects(h.bbox) for h in heads):
            continue  # banner or tab behind a heading
        if fill is not None and area < 6000 and any(0 <= r.x0 - h.bbox.x1 < 80 and r.y0 < h.bbox.y1 + 12 and r.y1 > h.bbox.y0 - 12
                                                    and h.size >= 14 for h in heads):
            continue  # shape at the end of a heading banner
        if area < 1500 and any((r + (-30, -30, 30, 30)).intersects(h.bbox) for h in heads):
            continue  # corner squares around the "Пример" tab
        if any(0 <= h.bbox.x0 - r.x1 < 40 and r.width < 90 and r.height < 70 and r.y0 < h.bbox.y1 + 10 and r.y1 > h.bbox.y0 - 25
               for h in heads):
            continue  # pictogram before a heading
        if fill is not None and any(max(abs(a - b) for a, b in zip(fill, dc)) < 0.04 for dc in L.get("decor_fills", [])) \
                and r.width < 130 and r.height < 110:
            decor.append(r)
            continue
        if any(dd.contains(r) for dd in decor):
            continue
        inside = [ln for ln in lines if r.contains(ln.bbox + (1, 1, -1, -1))]
        if (fill is not None or stroke is not None) and rect_like(dr):
            res = [pymupdf.Rect(i[1]) for i in dr["items"] if i[0] == "re"]
            if len(res) <= 1:
                res = [r]
            for rr in res:
                if 150 < rr.get_area() < 60000 and rr.width > 3 and rr.height > 3:
                    cells.append((rr, dr))
        if "f" in dr["type"] and area > 1200 and inside and sum(1 for ln in inside if is_wordy(ln)) >= 0.5 * len(inside):
            boxes.append(r)
            continue
        if dr["type"] == "s" and area > 1200 and any(is_prose(ln) for ln in inside):
            continue  # outline around sentences
        pieces.append(r)
    for im in page.get_image_info():
        r = pymupdf.Rect(im["bbox"]) & page.rect
        if r.is_empty or not r.intersects(body) or r.get_area() > 0.4 * page.rect.get_area():
            continue
        if any(0 <= h.bbox.x0 - r.x1 < 40 and r.width < 90 and r.height < 70 for h in heads):
            continue
        pieces.append(r)
    uniq = []
    for b in sorted(boxes, key=lambda b: -b.get_area()):
        if not any((b & u).get_area() > 0.6 * b.get_area() for u in uniq):
            uniq.append(b)
    return bars, pieces, uniq, cells


def grid_tables(cells, lines):
    """Groups of touching rectangles that tile an area and hold text -> table rows."""
    rects = [r for r, _ in cells]
    groups, seen = [], set()
    for i in range(len(rects)):
        if i in seen:
            continue
        comp, stack = [], [i]
        seen.add(i)
        while stack:
            k = stack.pop()
            comp.append(k)
            for j in range(len(rects)):
                if j not in seen and (rects[k] + (-2.5, -2.5, 2.5, 2.5)).intersects(rects[j]) and \
                        not rects[k].contains(rects[j]) and not rects[j].contains(rects[k]):
                    seen.add(j)
                    stack.append(j)
        groups.append([rects[k] for k in comp])
    tables, fallbacks = [], []
    for g in groups:
        if len(g) < 4:
            continue
        ga = g[0]
        for r in g[1:]:
            ga = ga | r
        if ga.width > 60 and ga.height > 25 and any(ga.contains(ln.bbox) for ln in lines):
            fallbacks.append(ga)
        ys = sorted({round(r.y0) for r in g})
        xs = sorted({round(r.x0) for r in g})
        rows_y = []
        for y in ys:
            if not rows_y or y - rows_y[-1] > 3:
                rows_y.append(y)
        cols_x = []
        for x in xs:
            if not cols_x or x - cols_x[-1] > 3:
                cols_x.append(x)
        if len(rows_y) < 2 or len(cols_x) < 2 or len(g) < 0.8 * len(rows_y) * len(cols_x) or len(cols_x) > 7:
            continue
        area = g[0]
        for r in g[1:]:
            area = area | r
        inside = [ln for ln in lines if area.contains(pymupdf.Point((ln.bbox.x0 + ln.bbox.x1) / 2, (ln.bbox.y0 + ln.bbox.y1) / 2))]
        if len(inside) < 3:
            continue
        # cell borders from row/column starts
        rb = rows_y + [area.y1]
        cb = cols_x + [area.x1]
        grid = [[[] for _ in cols_x] for _ in rows_y]
        for ln in inside:
            cy, cx = (ln.bbox.y0 + ln.bbox.y1) / 2, (ln.bbox.x0 + ln.bbox.x1) / 2
            ri = max(i for i in range(len(rows_y)) if rb[i] - 3 <= cy) if any(rb[i] - 3 <= cy for i in range(len(rows_y))) else 0
            ci = max(i for i in range(len(cols_x)) if cb[i] - 3 <= cx) if any(cb[i] - 3 <= cx for i in range(len(cols_x))) else 0
            grid[ri][ci].append(ln)
        filled = sum(1 for row in grid for c in row if c)
        if filled < 0.5 * len(rows_y) * len(cols_x):
            continue
        tables.append((area, grid, inside))
        fallbacks.pop()
    return tables, fallbacks


def merge_near(rects, hgap=22, vgap=8):
    """Join pieces of one diagram: side by side on a row, or stacked closely."""
    rects = [pymupdf.Rect(r) for r in rects]
    changed = True
    while changed:
        changed = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                vov = min(a.y1, b.y1) - max(a.y0, b.y0)
                hov = min(a.x1, b.x1) - max(a.x0, b.x0)
                hg = max(a.x0, b.x0) - min(a.x1, b.x1)
                vg = max(a.y0, b.y0) - min(a.y1, b.y1)
                if (vov >= 0.5 * min(a.height, b.height) and hg <= hgap) or (hov >= 0.5 * min(a.width, b.width) and vg <= vgap):
                    rects[i] = a | b
                    del rects[j]
                    changed = True
                    break
            if changed:
                break
    return rects


def xy_order(elems, gy=1.0, gx=10):
    """Recursive XY-cut giving reading order; leaves keep text and pictures apart (sorted by position)."""
    if len(elems) <= 1:
        return elems
    for axis, gap in ((1, gy), (0, gx), (0, 1.5), (1, -2.5)):
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
            return [x for g in groups for x in xy_order(g, gy, gx)]
    return sorted(elems, key=lambda e: (round(e[1].y0 / 4), e[1].x0))


# ---------------------------------------------------------------- output

class Emitter:
    """Turns ordered page elements into reader blocks (paragraphs, formula lines, boxes, pictures)."""

    def __init__(self, cfg, flow, saver, kinds, chapters, chap, pi):
        self.cfg, self.flow, self.saver, self.kinds = cfg, flow, saver, kinds
        self.chapters, self.chap, self.pi = chapters, chap, pi
        self.prev = None
        self.ml_x0 = None
        self.pend_ans = []
        self.L = cfg["layout"]

    def flush_ans(self):
        if self.pend_ans:
            txt = " ".join(a["text"] for a in sorted(self.pend_ans, key=lambda a: (-a["bbox"].y0, -a["bbox"].x0)))
            txt = re.sub(r"(?<![A-Za-z])a\)", "а)", txt)
            self.flow.raw(f'<details class="ans"><summary>{esc(self.cfg.get("answer_label", "Ответ"))}</summary>{esc(txt)}</details>')
            self.saver.stats["answers"] += 1
            self.pend_ans.clear()

    def run(self, items):
        for kind, rect, obj in items:
            if kind != "ans":
                self.flush_ans()
            if kind == "ans":
                if self.pend_ans and abs(obj["bbox"].y0 - self.pend_ans[-1]["bbox"].y0) > 30:
                    self.flush_ans()
                self.pend_ans.append(obj)
            elif kind == "fig":
                self.flow.img(self.saver.picture(rect))
                self.prev = None
                self.ml_x0 = None
            elif kind == "tbl":
                self.flow.raw(self.table_html(obj))
                self.prev = None
            elif kind == "box":
                self.flow.raw(self.box_html(obj))
                self.prev = None
            else:
                self.line(obj)
        self.flush_ans()

    def table_html(self, obj):
        self.saver.stats["tables"] += 1
        if obj[0] == "grid":
            grid = obj[1]
            cells = [["<br>".join(l.html() for l in sorted(c, key=lambda l: l.bbox.y0)) for c in row] for row in grid]
        else:
            cells = [[esc(re.sub(r"\s+", " ", clean(c or "")).strip()) for c in row] for row in obj[1]]
        ncol = max(len(r) for r in cells)
        long_cells = sum(1 for r in cells for c in r if len(re.sub(r"<[^>]+>", "", c)) > 25)
        cards = ncol >= 4 or (ncol == 3 and long_cells >= 3)
        head = [re.sub(r"<[^>]+>|<br>", " ", c).strip() for c in cells[0]]
        rows = ["<tr>" + "".join(f"<th>{c}</th>" for c in cells[0]) + "</tr>"]
        for r in cells[1:]:
            rows.append("<tr>" + "".join(f'<td data-l="{htmlmod.escape(head[i] if i < len(head) else "", quote=True)}">{c}</td>'
                                         for i, c in enumerate(r)) + "</tr>")
        return f'<div class="tbl{" cards" if cards else ""}"><table>' + "".join(rows) + "</table></div>"

    def box_html(self, inner):
        """A framed note: its lines as paragraphs (formula lines kept), pictures inline."""
        parts, cur, prev = [], [], None
        for kind, rect, obj in inner:
            if kind == "fig":
                if cur:
                    parts.append("<p>" + " ".join(cur) + "</p>")
                    cur = []
                b = self.saver.picture(rect)
                parts.append(f'<figure><img data-w="{b["w"]}" data-h="{b["ht"]}" style="width:{b["dw"]}em" src="{b["src"]}" alt=""></figure>')
                prev = None
                continue
            if kind != "line":
                continue
            ln = obj
            h = ln.html()
            if not h:
                continue
            math = is_math_line(ln.text)
            new = prev is None or math or getattr(prev, "_m", False) or ln.bbox.y0 - prev.bbox.y1 > ln.size * 0.6 \
                or bool(re.match(r"^(<b class=\"(bd|nb)\">|\d+[.)]\s|[–•-]\s|[а-г]\)\s)", h))
            if new and cur:
                parts.append("<p>" + " ".join(cur) + "</p>")
                cur = []
            if cur and cur[-1].endswith("-") and not cur[-1].endswith(" -"):
                cur[-1] = cur[-1][:-1] + h
            else:
                cur.append(h)
            ln._m = math
            prev = ln
        if cur:
            parts.append("<p>" + " ".join(cur) + "</p>")
        return '<div class="kbox">' + "".join(parts) + "</div>"

    def line(self, ln):
        flow, k, t = self.flow, self.kinds.get(id(ln)), ln.text
        if k == "title" and self.pi != self.chap["from"]:
            k = "h3"
        if k == "title":
            self.prev = None
            return
        if k in ("ex", "try"):
            flow.heading(4, esc(clean(ln.first()["text"]).strip()), k)
            rest = ln.html(skip_first=True)
            if rest:
                flow.line(rest, True)
                self.prev = ln
            else:
                self.prev = None
            return
        if k == "h3":
            if flow.blocks and flow.blocks[-1].get("_h3") and self.prev is not None and getattr(self.prev, "_h3", False) \
                    and ln.bbox.y0 - self.prev.bbox.y1 < 8:
                flow.blocks[-1]["h"] += " " + ln.html()
                self.chapters[-1]["sub"][-1]["title"] += " " + t
            else:
                flow.heading(3, ln.html())
                flow.blocks[-1]["_h3"] = True
                self.chapters[-1]["sub"].append({"title": t, "b": len(flow.blocks) - 1})
            ln._h3 = True
            self.prev = ln
            return
        if k == "h4":
            flow.heading(4, ln.html(), "mk")
            self.prev = None
            return
        h = ln.html()
        if not h:
            return
        math = is_math_line(t) or (not is_wordy(ln) and bool(re.search(r"[=<>≠≈]", t)))
        prev = self.prev
        if math:
            # formula lines keep their breaks; continuation lines keep their indent under the first one
            if self.ml_x0 is None or prev is None or not getattr(prev, "_math", False) or ln.bbox.y0 - prev.bbox.y1 > 12:
                self.ml_x0 = ln.bbox.x0
            ind = max(0.0, min(8.0, (ln.bbox.x0 - self.ml_x0) / 10))
            flow.close()
            style = f' style="padding-left:{1 + ind:.1f}em"' if ind > 0.2 else ""
            flow.raw(f'<p class="ml"{style}>{h}</p>')
            ln._math = True
            self.prev = ln
            return
        self.ml_x0 = None
        cls = "side" if 7.5 <= ln.size < 9.5 else None
        if prev is None or getattr(prev, "_h3", False):
            new = not (flow.continues() and not re.match(r"^(\S{1,2}\s)", t) and flow.cur is not None)
        else:
            gap = ln.bbox.y0 - prev.bbox.y1
            starts_item = bool(re.match(r"^<b class=\"(bd|nb)\">", h)) or bool(re.match(r"^(\d+[.)]|•)\s", t))
            new = (getattr(prev, "_math", False) or starts_item or gap > ln.size * 0.6 or gap < -4
                   or abs(ln.bbox.x0 - prev.bbox.x0) > 14 and prev.text.endswith(SENT_END)
                   or (prev.text.endswith(SENT_END) and prev.bbox.x1 < self.L["right"] - 45)
                   or cls != (flow.cur or {}).get("cls"))
        ln._math = False
        flow.line(h, new, cls)
        self.prev = ln


class Saver:
    def __init__(self, cfg, doc):
        self.cfg, self.doc = cfg, doc
        self.L = cfg["layout"]
        self.out = cfg["out"]
        self.imgdir = os.path.join(self.out, "img")
        os.makedirs(self.imgdir, exist_ok=True)
        for f in os.listdir(self.imgdir):
            os.remove(os.path.join(self.imgdir, f))
        self.images = []
        self.stats = collections.Counter()
        self.page = None

    def set_page(self, pi, page, drawings, spans, rasters):
        self.pi, self.page, self.drawings, self.spans, self.rasters = pi, page, drawings, spans, rasters
        self.n = 0

    def prepare_render(self, text_rects):
        """Photos are rendered from a copy of the page without the text we already give as text."""
        if not hasattr(self, "rdoc"):
            self.rdoc = pymupdf.open(stream=self.doc.tobytes(), filetype="pdf")
        rp = self.rdoc[self.pi]
        for r in text_rects:
            rp.add_redact_annot(r + (0.5, 0.5, -0.5, -0.5), fill=False)
        if text_rects:
            rp.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
        self.rpage = rp

    def picture(self, clip):
        self.n += 1
        base = f"p{self.pi + self.cfg['page_offset'] + 1:03d}-{self.n}"
        raster = any((clip & r).get_area() > 0.15 * min(r.get_area(), clip.get_area()) for r in self.rasters)
        if raster:
            clip = clip + (-2, -2, 2, 2)
            clip &= self.page.rect
            scale = self.L.get("photo_scale", 3)
            pix = self.rpage.get_pixmap(clip=clip, matrix=pymupdf.Matrix(scale, scale), alpha=False)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            mw = self.L.get("photo_max_w", 1100)
            if im.width > mw:
                im = im.resize((mw, round(im.height * mw / im.width)), Image.LANCZOS)
            name = base + ".webp"
            im.save(os.path.join(self.imgdir, name), "WEBP", quality=64, method=6)
            w, h = im.width, im.height
            dw = clip.width / self.L["body_pt"]
            self.stats["photos"] += 1
        else:
            svg, c = svg_redraw(self.drawings, self.spans, clip)
            name = base + ".svg"
            with open(os.path.join(self.imgdir, name), "w", encoding="utf-8") as f:
                f.write(svg)
            w, h = round(c.width * 3), round(c.height * 3)
            dw = c.width / self.L["body_pt"]
            self.stats["svg"] += 1
        self.images.append("img/" + name)
        return {"t": "img", "src": "img/" + name, "w": w, "ht": h, "dw": round(dw, 1)}


def main():
    cfg = load_config(sys.argv[1])
    L = cfg["layout"]
    doc = open_doc(cfg["pdf"])
    saver = Saver(cfg, doc)
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
        for ln in lines:  # the PDF sometimes draws a line twice (outline + fill)
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
                kinds[id(ln)] = None  # white words on a picture, not a banner
        lines = [ln for ln in lines if kinds[id(ln)] != "skip"]
        heads = [ln for ln in lines if kinds[id(ln)] in ("ex", "try", "h3", "h4", "title")]
        bars, pieces, boxes, cells = analyse(page, lines, heads, cfg, drawings)
        rasters = [pymupdf.Rect(im["bbox"]) & page.rect for im in page.get_image_info()
                   if 3000 < (pymupdf.Rect(im["bbox"]) & page.rect).get_area() < 0.4 * page.rect.get_area()]
        # full-page raster layers hold the photos; find where they actually have pictures
        pa = photo_areas(page, drawings)
        rasters += pa
        pieces += pa
        saver.set_page(pi, page, drawings, trim_spans(page), rasters)
        if pi == chap["from"] and L.get("header_bottom"):
            hb = L["header_bottom"]
            pieces = [pymupdf.Rect(r.x0, max(r.y0, hb), r.x1, r.y1) for r in pieces if r.y1 > hb + 3]
            boxes = [b for b in boxes if b.y0 >= hb - 2]
            goal = sorted([ln for ln in lines if ln.bbox.y1 <= hb and ln not in heads], key=lambda l: (l.bbox.y0, l.bbox.x0))
            lines = [ln for ln in lines if ln not in goal]
            if goal:
                flow.raw('<p class="goal"><b>%s</b> %s</p>' % (esc(cfg.get("goal_label", "Цель обучения:")), " ".join(g.html() for g in goal)))
        mark_fractions(page, lines, bars)

        # tables: ruled grids (find_tables) and tiled coloured cells
        elems = []
        used = set()
        for t in page.find_tables().tables:
            rows = t.extract()
            cl = [c for r in rows for c in r]
            full = [c for c in cl if c and c.strip()]
            tb = pymupdf.Rect(t.bbox)
            if t.col_count >= 2 and t.row_count >= 2 and len(full) >= 0.7 * len(cl) and tb.y0 >= L["top"] \
                    and sum(1 for c in rows[0] if c and c.strip()) >= 2 and not any(ln.bbox.intersects(tb) for ln in heads) \
                    and not any(re.search(r"Решение|Попробуйте", c or "") for c in cl):
                elems.append(("tbl", tb, ("rows", rows)))
                used |= {id(ln) for ln in lines if tb.contains(pymupdf.Point((ln.bbox.x0 + ln.bbox.x1) / 2, (ln.bbox.y0 + ln.bbox.y1) / 2))}
        gt, fallbacks = grid_tables(cells, [ln for ln in lines if id(ln) not in used and ln not in heads])
        for area, grid, inside in gt:
            if any((area & e[1]).get_area() > 0.3 * area.get_area() for e in elems):
                continue
            elems.append(("tbl", area, ("grid", grid)))
            used |= {id(ln) for ln in inside}
        # grids that are not clean tables: one picture, text inside it included
        fallbacks = [f for f in merge_rects(fallbacks, 1) if not any((f & e[1]).get_area() > 0.3 * f.get_area() for e in elems)]
        for f in fallbacks:
            used |= {id(ln) for ln in lines if f.contains(pymupdf.Point((ln.bbox.x0 + ln.bbox.x1) / 2, (ln.bbox.y0 + ln.bbox.y1) / 2))}
        boxes = [b for b in boxes if not any((b & f).get_area() > 0.5 * b.get_area() for f in fallbacks)]
        tabs = [e[1] for e in elems]
        pieces = [r for r in pieces if not any((r & tb).get_area() > 0.6 * max(r.get_area(), 0.01) for tb in tabs)]
        boxes = [b for b in boxes if not any((b & tb).get_area() > 0.5 * b.get_area() for tb in tabs)]
        lines = [ln for ln in lines if id(ln) not in used]

        # diagrams: vector pieces plus the labels on or right next to them (never sentences)
        base = merge_rects(pieces, 3)
        grabbed, extra = set(), []

        def label_like(ln):
            col = ln.first()["color"]
            return (ln.size <= 9.5 and col not in (0, 0xffffff) and len(ln.text) <= 40) or \
                (ln.size >= 14 and len(ln.text) <= 8 and ln not in heads)
        changed = True
        while changed:
            changed = False
            zones = base + extra
            for ln in lines:
                if ln in heads or id(ln) in grabbed:
                    continue
                wordy = is_wordy(ln)
                if wordy and not label_like(ln):
                    continue
                if ln.size >= 9.5 and "=" in ln.text and len(ln.text) >= 5 and not any(
                        (ln.bbox & g).get_area() > 0.5 * ln.bbox.get_area() for g in base):
                    continue  # a formula line next to a diagram stays text
                tiny = len(ln.text) <= 4 or bool(re.fullmatch(r"[\d\s\u2009\u2003–−+\-.,()xyабвг°]+", ln.text))
                for g in (zones if label_like(ln) else base):
                    near = 14 if label_like(ln) else (12 if tiny else (10 if ln.size <= 9 else 5))
                    if (ln.bbox & g).get_area() > 0.5 * ln.bbox.get_area() or ln.bbox.intersects(g + (-near, -near, near, near)):
                        grabbed.add(id(ln))
                        extra.append(ln.bbox)
                        changed = True
                        break
        atoms = merge_near(merge_rects(base + extra + fallbacks, 1))
        for ln in lines:
            if id(ln) not in grabbed and ln not in heads and not is_wordy(ln) and \
                    any((ln.bbox & g).get_area() > 0.6 * ln.bbox.get_area() for g in atoms):
                grabbed.add(id(ln))
        atoms = [r for r in atoms if r.get_area() > 150 and (r.get_area() > 1200 or any(r.intersects(e) for e in extra))]
        if DEBUG:
            print(pi, "atoms", [[round(v) for v in r] for r in atoms], "boxes", [[round(v) for v in r] for r in boxes])
        # photos: don't repeat text that sits at their top or bottom edge
        emitted = [ln for ln in lines if id(ln) not in grabbed and ln not in heads]
        for k, r in enumerate(atoms):
            if not any((r & q).get_area() > 0.15 * min(q.get_area(), r.get_area()) for q in rasters):
                continue
            for ln in emitted:
                ov = (ln.bbox & r)
                if ov.is_empty or ov.width < 0.5 * ln.bbox.width:
                    continue
                if (ln.bbox.y0 + ln.bbox.y1) / 2 < (r.y0 + r.y1) / 2:
                    r.y0 = max(r.y0, ln.bbox.y1)
                else:
                    r.y1 = min(r.y1, ln.bbox.y0)
            atoms[k] = r
        atoms = [r for r in atoms if r.height > 8]
        saver.prepare_render([ln.bbox for ln in lines if id(ln) not in grabbed] + [a["bbox"] for a in answers])
        if os.environ.get("DUMP_DIR"):
            dump_page(os.environ["DUMP_DIR"], pi, page, cfg, lines, kinds, answers, atoms, rasters, elems, boxes)
        for r in atoms:
            elems.append(("fig", r, None))
        elems += [("line", ln.bbox, ln) for ln in lines if id(ln) not in grabbed]
        elems += [("ans", a["bbox"], a) for a in answers]
        # text boxes collect what lies inside them
        top = []
        box_members = {i: [] for i in range(len(boxes))}
        for e in elems:
            ctr = pymupdf.Point((e[1].x0 + e[1].x1) / 2, (e[1].y0 + e[1].y1) / 2)
            hit = [i for i, b in enumerate(boxes) if b.contains(ctr) and e[0] in ("line", "fig")
                   and not (e[0] == "fig" and e[1].get_area() > 0.7 * b.get_area())]
            if hit:
                i = min(hit, key=lambda i: boxes[i].get_area())
                box_members[i].append(e)
            else:
                top.append(e)
        for i, b in enumerate(boxes):
            if box_members[i]:
                r = pymupdf.Rect(b)
                top.append(("box", r, xy_order(box_members[i])))
        ordered = xy_order(top)
        Emitter(cfg, flow, saver, kinds, chapters, chap, pi).run(ordered)
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


_NORASTER = {}


def dump_page(ddir, pi, page, cfg, lines, kinds, answers, atoms, rasters, elems, boxes):
    """Material for a person (or model) re-typesetting the page: text lines, picture candidates, a picture."""
    os.makedirs(ddir, exist_ok=True)
    printed = pi + 1 + cfg["page_offset"]
    rs = lambda r: [round(r.x0), round(r.y0), round(r.x1), round(r.y1)]
    regs = []
    for r in atoms:
        regs.append({"id": f"R{len(regs) + 1}", "bbox": rs(r),
                     "photo": any((r & q).get_area() > 0.15 * min(q.get_area(), r.get_area()) for q in rasters)})
    for k, r, obj in elems:
        if k == "tbl":
            regs.append({"id": f"R{len(regs) + 1}", "bbox": rs(r), "table": True})
    data = {"page_index": pi, "printed_page": printed, "page_size": [round(page.rect.width), round(page.rect.height)],
            "lines": [{"bbox": rs(ln.bbox), "size": ln.size, "font": ln.font, "color": "#%06x" % ln.first()["color"],
                       "style": kinds.get(id(ln)), "html": ln.html()} for ln in sorted(lines, key=lambda l: (l.bbox.y0, l.bbox.x0))],
            "answers_upside_down": [a["text"] for a in answers],
            "regions": regs, "frames": [rs(b) for b in boxes]}
    with open(os.path.join(ddir, f"p{printed:03d}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=0)
    # page picture with the candidate regions outlined and labelled
    from PIL import ImageDraw
    sc = 1.4
    pix = page.get_pixmap(matrix=pymupdf.Matrix(sc, sc), alpha=False)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    dr = ImageDraw.Draw(im)
    for g in regs:
        x0, y0, x1, y1 = [v * sc for v in g["bbox"]]
        dr.rectangle([x0, y0, x1, y1], outline=(230, 0, 120), width=2)
        dr.rectangle([x0, y0, x0 + 34, y0 + 16], fill=(230, 0, 120))
        dr.text((x0 + 3, y0 + 2), g["id"], fill=(255, 255, 255))
    im.save(os.path.join(ddir, f"p{printed:03d}.png"))


def photo_areas(page, drawings, scale=0.75):
    """Where the page-sized raster layers really show a picture: diff of the page with and without them."""
    doc = page.parent
    big = [im for im in page.get_image_info(xrefs=True)
           if (pymupdf.Rect(im["bbox"]) & page.rect).get_area() > 0.4 * page.rect.get_area() and im["xref"]]
    if not big:
        return []
    if id(doc) not in _NORASTER:
        _NORASTER[id(doc)] = pymupdf.open(stream=doc.tobytes(), filetype="pdf")
    d2 = _NORASTER[id(doc)]
    p2 = d2[page.number]
    for im in big:
        try:
            p2.delete_image(im["xref"])
        except Exception:
            pass
    m = pymupdf.Matrix(scale, scale)
    a = page.get_pixmap(matrix=m, alpha=False)
    b = p2.get_pixmap(matrix=m, alpha=False)
    ia = Image.frombytes("RGB", (a.width, a.height), a.samples)
    ib = Image.frombytes("RGB", (b.width, b.height), b.samples)
    from PIL import ImageChops, ImageFilter
    diff = ImageChops.difference(ia, ib).convert("L").point(lambda v: 255 if v > 45 else 0)
    diff = diff.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(9))  # drop thin watermark strokes
    bb = diff.getbbox()
    if not bb:
        return []
    W, H = diff.size
    cell = 8
    small = diff.resize((W // cell + 1, H // cell + 1), Image.BOX)
    px = small.load()
    rects = []
    for y in range(small.size[1]):
        for x in range(small.size[0]):
            if px[x, y] > 100:
                rects.append(pymupdf.Rect(x * cell / scale, y * cell / scale, (x + 1) * cell / scale, (y + 1) * cell / scale))
    return [r & page.rect for r in merge_rects(rects, 3) if r.get_area() > 1500]


if __name__ == "__main__":
    main()
