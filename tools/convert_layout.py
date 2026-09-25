#!/usr/bin/env python3
"""Convert a born-digital (InDesign) textbook PDF into the reader's book.json.

Usage: python3 convert_layout.py /mnt/project-files/pilot-book/<book>.config.json

Unlike convert_pdf.py (scans with an OCR text layer), this reads the real text of a
typeset PDF. Pictures and diagrams (raster images plus vector drawings, with any labels
drawn on them) are cropped from the page as WebP. Framed text boxes become text boxes,
ruled tables become HTML tables, and everything else becomes headings and paragraphs.
Line-break hyphens are removed and running headers, page numbers and page ornaments
are dropped. Printed page numbers are kept as markers, like in the first book.
"""
import collections, json, os, re, sys

import pymupdf
from PIL import Image

LETTERS = "a-zA-Zа-яА-ЯёЁүҮөӨңҢ"
SENT_END = tuple(".:!?»;)…")


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    cfg["pdf"] = os.path.join(base, cfg["pdf"])
    cfg["out"] = os.path.join(base, cfg["out"])
    return cfg


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def weight(font):
    m = re.search(r"-(\d00)", font)
    return int(m.group(1)) if m else (700 if "Bold" in font else 500)


# ---------------------------------------------------------------- page model

class Line:
    def __init__(self, bbox, spans, block):
        self.bbox = pymupdf.Rect(bbox)
        self.spans = [s for s in spans if s["text"] != ""]
        self.block = block
        main = max(self.spans, key=lambda s: len(s["text"].strip()) or 0.1) if self.spans else None
        self.size = round(main["size"], 1) if main else 0
        self.font = main["font"] if main else ""
        self.w = weight(self.font)
        self.color = main["color"] if main else 0
        self.text_x0 = self.bbox.x0
        for k, s in enumerate(self.spans):
            if "Wingdings" in s["font"]:
                nxt = [x for x in self.spans[k + 1:] if x["text"].strip()]
                if nxt:
                    self.text_x0 = nxt[0]["bbox"][0] + (len(nxt[0]["text"]) - len(nxt[0]["text"].lstrip())) * nxt[0]["size"] * 0.25
                break

    @property
    def text(self):
        return "".join(s["text"] for s in self.spans).strip()

    def html(self):
        out = []
        base_y = max((s["origin"][1] for s in self.spans if s["size"] >= self.size - 0.5), default=None)
        for s in self.spans:
            t = s["text"]
            if "Wingdings" in s["font"] or s["font"] == "bullet":
                out.append(("", "• " if t.strip() else t))
                continue
            t = esc(t.replace("\xad", ""))
            tag = ""
            if base_y is not None and s["size"] < self.size * 0.8 and t.strip():
                tag = "sup" if s["origin"][1] < base_y - 1 else "sub"
            elif weight(s["font"]) >= 700 and t.strip() and self.w < 700:
                tag = "b"
            out.append((tag, t))
        # merge neighbours with the same tag
        res, cur_tag, buf = [], None, ""
        for tag, t in out:
            if tag == cur_tag or not t.strip() and cur_tag and tag == "":
                buf += t
            else:
                if buf:
                    res.append(f"<{cur_tag}>{buf}</{cur_tag}>" if cur_tag else buf)
                cur_tag, buf = tag, t
        if buf:
            res.append(f"<{cur_tag}>{buf}</{cur_tag}>" if cur_tag else buf)
        h = "".join(res)
        h = re.sub(r"</b>(\s*)<b>", r"\1", h)
        h = re.sub(r"^(•\s*)+", "• ", h.strip())
        return re.sub(r"\s+", " ", h).strip()


def page_lines(page):
    lines = []
    for bi, b in enumerate(page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES)["blocks"]):
        if b["type"] != 0:
            continue
        blines = []
        for l in b["lines"]:
            # a justified line can come out as several pieces: glue pieces on one baseline together
            if blines and abs(l["bbox"][1] - blines[-1]["bbox"][1]) < 1.5 and 0 <= l["bbox"][0] - blines[-1]["bbox"][2] < 14:
                last = blines[-1]
                last["spans"] = last["spans"] + [dict(l["spans"][0], text=" ")] + l["spans"] if l["spans"] else last["spans"]
                last["bbox"] = tuple(pymupdf.Rect(last["bbox"]) | pymupdf.Rect(l["bbox"]))
            else:
                blines.append({"bbox": l["bbox"], "spans": list(l["spans"])})
        for l in blines:
            ln = Line(l["bbox"], l["spans"], bi)
            if ln.text:
                lines.append(ln)
    # bullets drawn in a symbol font sit on their own "line": attach them to the text they mark
    bullets = [ln for ln in lines if all("Wingdings" in s["font"] or not s["text"].strip() for s in ln.spans)]
    rest = [ln for ln in lines if ln not in bullets]
    for bl in bullets:
        cy = (bl.bbox.y0 + bl.bbox.y1) / 2
        cands = [ln for ln in rest if ln.bbox.y0 - 2 < cy < ln.bbox.y1 + 2 and 0 <= ln.bbox.x0 - bl.bbox.x1 < 20]
        if cands:
            t = min(cands, key=lambda ln: ln.bbox.x0)
            if "Wingdings" not in t.spans[0]["font"]:
                t.spans.insert(0, {"text": "• ", "font": "bullet", "size": t.size, "origin": t.spans[0]["origin"], "color": t.color,
                                  "bbox": tuple(bl.bbox)})
                t.text_x0 = t.bbox.x0
            t.bbox |= bl.bbox
    return rest


def merge_rects(rects, tol):
    rects = [pymupdf.Rect(r) for r in rects]
    changed = True
    while changed:
        changed = False
        out = []
        while rects:
            r = rects.pop()
            grown = pymupdf.Rect(r.x0 - tol, r.y0 - tol, r.x1 + tol, r.y1 + tol)
            for o in rects[:]:
                if grown.intersects(o):
                    r |= o
                    rects.remove(o)
                    changed = True
                    grown = pymupdf.Rect(r.x0 - tol, r.y0 - tol, r.x1 + tol, r.y1 + tol)
            out.append(r)
        rects = out
    return rects


def inside(line, r, slack=2):
    b = line.bbox
    return b.x0 >= r.x0 - slack and b.x1 <= r.x1 + slack and b.y0 >= r.y0 - slack and b.y1 <= r.y1 + slack


def overlap(line, r):
    i = line.bbox & r
    return 0 if i.is_empty else i.get_area() / max(1, line.bbox.get_area())


# ---------------------------------------------------------------- analysis

class Book:
    def __init__(self, doc, cfg):
        self.doc, self.cfg = doc, cfg
        L = cfg["layout"]
        self.top, self.bottom = L["top"], L["bottom"]
        self.L = L
        self.set_page(1)
        self.body_size = L["body_size"]
        xc = collections.Counter()
        for p in doc:
            for im in p.get_images(full=True):
                xc[im[0]] += 1
        self.decor_xrefs = {x for x, n in xc.items() if n >= L.get("repeat_min", 4)}

    def set_page(self, printed):
        """Text column of this page: even and odd pages have different inner margins."""
        L = self.L
        self.left = L["left_odd"] if printed % 2 and "left_odd" in L else L["left"]
        self.right = self.left + (L["right"] - L["left"])

    def regions(self, page, lines):
        """Rectangles of graphics on the page (images and visible drawings), merged into figures."""
        rects = []
        for im in page.get_image_info(xrefs=True):
            if im["xref"] in self.decor_xrefs:
                continue
            rects.append(pymupdf.Rect(im["bbox"]))
        for dr in page.get_drawings():
            fill, stroke = dr.get("fill"), dr.get("color")
            if fill is not None and (min(fill) > 0.97 or (dr.get("fill_opacity") or 1) < 0.05):
                fill = None
            if stroke is not None and (min(stroke) > 0.97 or (dr.get("stroke_opacity") or 1) < 0.05 or not dr.get("width")):
                stroke = None
            if fill is None and stroke is None:
                continue
            rects.append(pymupdf.Rect(dr["rect"]))
        body = pymupdf.Rect(self.left - 6, self.top, self.right + 6, self.bottom)
        keep = []
        for r in rects:
            r = r & page.rect
            if r.is_empty or (r.width < 3 and r.height < 3):
                continue
            if not r.intersects(body) or (r & body).get_area() < 0.5 * max(r.get_area(), 0.1):
                continue  # page ornaments in the margins
            keep.append(r & pymupdf.Rect(self.left - 6, 0, self.right + 6, page.rect.height))
        regs = [r for r in merge_rects(keep, 3) if r.width >= 3 and r.height >= 3]

        def heading_icon(r):
            # the small pictogram and colour bar in front of a heading such as "ЗАДУМАЙТЕСЬ"
            if r.width > 60 or r.height > 36:
                return False
            for ln in lines:
                if ln.w >= 700 and 0 <= ln.bbox.x0 - r.x1 + 2 < 60 and ln.bbox.y0 < r.y1 and ln.bbox.y1 > r.y0 \
                        and not inside(ln, r):
                    return True
            return False

        regs = [r for r in regs if not heading_icon(r)]
        # join pieces of one diagram: graphic regions with no running text between them
        colw = self.right - self.left
        prose = [ln for ln in lines if abs(ln.size - self.body_size) < 0.6 and ln.bbox.width > 0.55 * colw]
        markers = tuple(self.cfg["box_markers"])

        def texty(r):
            return sum(1 for ln in prose if inside(ln, r)) >= 2 or \
                any(inside(ln, r) and ln.text.startswith(markers) for ln in lines)

        changed = True
        while changed:
            changed = False
            for a in regs:
                if texty(a):
                    continue
                for b in regs:
                    if b is a or texty(b):
                        continue
                    u = a | b
                    gap = max(b.y0 - a.y1, a.y0 - b.y1, 0)
                    if gap > 40:
                        continue
                    if any(ln.bbox.intersects(u) and not inside(ln, a) and not inside(ln, b) for ln in prose):
                        continue
                    regs.remove(a); regs.remove(b); regs.append(u)
                    changed = True
                    break
                if changed:
                    break
        return merge_rects(regs, 0)

    def classify(self, page, pi, lines):
        items = []  # (y, x, kind, payload)
        used = set()
        regs = self.regions(page, lines)
        caption_re = re.compile(self.cfg["caption_re"])
        for r in sorted(regs, key=lambda r: (r.y0, r.x0)):
            ins = [i for i, ln in enumerate(lines) if i not in used and (inside(ln, r) or overlap(ln, r) > 0.6)]
            if r.width < 50 and r.height < 32 and not any(len(lines[i].text) > 3 for i in ins):
                used.update(ins)  # an icon beside a marker heading
                continue
            if r.height < 6 or r.width < 6:
                continue
            if " ".join(lines[i].text for i in ins).strip() in self.cfg.get("drop_regions", []):
                used.update(ins)
                continue
            has_img = any(pymupdf.Rect(im["bbox"]).intersects(r) and im["xref"] not in self.decor_xrefs
                          for im in page.get_image_info(xrefs=True))
            txt = " ".join(lines[i].text for i in ins)
            # caption just below (or just above) the region
            cap = [i for i, ln in enumerate(lines) if i not in used and i not in ins and caption_re.match(ln.text)
                   and -4 < ln.bbox.y0 - r.y1 < 30 and ln.bbox.x0 < r.x1 and ln.bbox.x1 > r.x0]
            box_kind = None
            for key, kind in self.cfg["box_markers"].items():
                if txt.startswith(key):
                    box_kind = kind
            if box_kind:
                used.update(ins)
                items.append((r.y0, r.x0, "box", {"kind": box_kind, "lines": [lines[i] for i in ins]}))
                continue
            if not cap and not has_img and ins:
                tab = self.table(page, r, lines, ins)
                if tab:
                    used.update(tab["used"])
                    if tab["above"]:
                        items.append((r.y0 - 0.5, r.x0, "box", {"kind": "frame", "lines": tab["above"]}))
                    items.append((tab["grid"].y0, r.x0, "table", tab))
                    if tab["below"]:
                        items.append((tab["grid"].y1, r.x0, "box", {"kind": "frame", "lines": tab["below"]}))
                    continue
                prose = [i for i in ins if self.body_size - 1.6 < lines[i].size < self.body_size + 0.6]
                if len(prose) >= 0.7 * len(ins) and len(txt) > 60:
                    used.update(ins)
                    items.append((r.y0, r.x0, "box", {"kind": "frame", "lines": [lines[i] for i in ins]}))
                    continue
            # a figure: crop the graphics with every label drawn on them
            clip = pymupdf.Rect(r)
            for i in ins:
                clip |= lines[i].bbox
            # small labels touching the figure (names under portraits etc.)
            labels = []
            near = pymupdf.Rect(clip.x0 - 4, clip.y0 - 4, clip.x1 + 4, clip.y1 + 14)
            grow = True
            while grow:
                grow = False
                for i, ln in enumerate(lines):
                    if i in used or i in ins or i in cap or i in labels:
                        continue
                    if ln.size <= self.body_size - 0.9 and ln.bbox.intersects(near) and not caption_re.match(ln.text):
                        labels.append(i)
                        near |= pymupdf.Rect(ln.bbox.x0, ln.bbox.y0, ln.bbox.x1, ln.bbox.y1 + 6)
                        grow = True
            capl = [lines[i] for i in sorted(cap, key=lambda i: lines[i].bbox.y0)]
            # caption lines may continue on the next line(s)
            if capl:
                last = capl[-1]
                for i, ln in enumerate(lines):
                    if i not in used and i not in cap and i not in ins and ln.size == last.size and ln.w == last.w \
                            and 0 < ln.bbox.y0 - last.bbox.y1 < 4 and ln.bbox.x0 < clip.x1:
                        capl.append(ln); cap.append(i); last = ln
            used.update(ins); used.update(cap); used.update(labels)
            labl = [lines[i] for i in sorted(labels, key=lambda i: (lines[i].bbox.y0, lines[i].bbox.x0))]
            items.append((r.y0, r.x0, "fig", {"clip": clip, "cap": capl, "labels": labl}))
        rest = [ln for i, ln in enumerate(lines) if i not in used]
        return items, rest

    def table(self, page, r, lines, ins):
        try:
            tabs = page.find_tables(clip=r + (-2, -2, 2, 2)).tables
        except Exception:
            return None
        tabs = [t for t in tabs if t.row_count >= 2 and t.col_count >= 2]
        if not tabs:
            return None
        t = max(tabs, key=lambda t: t.bbox[2] * t.bbox[3])
        # split lines at cell borders (neighbouring cells can share one PDF line)
        allcells = [pymupdf.Rect(c) for row in t.rows for c in row.cells if c is not None]
        pieces = {}
        for i in ins:
            ln = lines[i]
            groups = collections.OrderedDict()
            for sp in ln.spans:
                b = pymupdf.Rect(sp["bbox"])
                cx, cy = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2
                k = next((j for j, cr in enumerate(allcells) if cr.contains(pymupdf.Point(cx, cy))), None)
                groups.setdefault(k, []).append(sp)
            if len(groups) == 1:
                pieces[i] = [(next(iter(groups)), ln)]
            else:
                pieces[i] = []
                for k, sps in groups.items():
                    sps = [x for x in sps if x["text"].strip()] and sps
                    bb = pymupdf.Rect(sps[0]["bbox"])
                    for x in sps:
                        bb |= pymupdf.Rect(x["bbox"])
                    pieces[i].append((k, Line(bb, sps, ln.block)))
        rows, n = [], 0
        covered = set()
        for row in t.rows:
            cells = []
            for c in row.cells:
                if c is None:
                    cells.append(None)
                    continue
                cells.append([pl for i in ins for k, pl in pieces[i] if k == n])
                covered.update(i for i in ins for k, pl in pieces[i] if k == n)
                n += 1
            rows.append(cells)
        grid = pymupdf.Rect(t.bbox)
        in_grid = [i for i in ins if overlap(lines[i], grid) > 0.6]
        if len(covered) < 0.8 * max(1, len(in_grid)):
            return None
        other = [i for i in ins if i not in covered]
        # a title just above the grid (inside the frame or right above it)
        title = [i for i in other if grid.y0 - 18 <= lines[i].bbox.y0 and lines[i].bbox.y1 <= grid.y0 + 2]
        for i, ln in enumerate(lines):
            if i not in ins and grid.y0 - 18 <= ln.bbox.y0 and ln.bbox.y1 <= grid.y0 + 2 and \
                    ln.bbox.x0 >= grid.x0 - 4 and ln.bbox.x1 <= grid.x1 + 4 and len(ln.text) < 90:
                title.append(i)
        above = [i for i in other if i not in title and lines[i].bbox.y1 <= grid.y0 + 2]
        below = [i for i in other if i not in title and i not in above]
        return {"rows": rows, "title": [lines[i] for i in sorted(title, key=lambda i: lines[i].bbox.y0)],
                "used": set(ins) | set(title), "above": [lines[i] for i in above], "below": [lines[i] for i in below],
                "grid": grid}


# ---------------------------------------------------------------- text flow

class Flow:
    def __init__(self, cfg, words):
        self.cfg = cfg
        self.words = words
        self.blocks = []
        self.cur = None      # open paragraph: {"t", "cls", "parts", "last"}
        self.pending_pg = None
        self.deferred = []

    def pg_mark(self, n):
        self.pending_pg = n

    def _pg(self):
        if self.pending_pg is None:
            return ""
        s = f'<span class="pg" data-n="{self.pending_pg}">{self.pending_pg}</span>'
        self.pending_pg = None
        return s

    def close(self):
        if self.cur:
            h = self.cur["h"].strip()
            if h:
                cls = self.cur["cls"]
                if cls:
                    self.blocks.append({"t": "raw", "h": f'<p class="{cls}">{h}</p>'})
                else:
                    self.blocks.append({"t": "p", "h": h})
        self.cur = None
        if self.deferred:
            d, self.deferred = self.deferred, []
            self.blocks.extend(d)

    def heading(self, level, text, cls=None):
        self.close()
        h = self._pg() + text
        if cls:
            self.blocks.append({"t": "raw", "h": f'<h{level} class="{cls}">{h}</h{level}>'})
        else:
            self.blocks.append({"t": f"h{level}", "h": h})

    def raw(self, h):
        # a framed box that runs over a page break continues the box on the previous page
        if h.startswith('<div class="frame">') and self.cur is None and self.blocks and \
                self.blocks[-1].get("h", "").startswith('<div class="frame">'):
            prev = self.blocks[-1]["h"]
            tail = re.sub(r"<[^>]+>", "", prev).rstrip()
            if tail and not tail.endswith(SENT_END):
                a = prev[:-len("</p></div>")]
                b = h[len('<div class="frame"><p>'):]
                self.blocks[-1]["h"] = self.join(a, self._pg() + b) if self.pending_pg is not None else self.join(a, b)
                return
        if self.continues():
            self.deferred.append({"t": "raw", "h": h})
            return
        self.close()
        if self.pending_pg is not None:
            h = re.sub(r"^(<\w+[^>]*>)", lambda m: m.group(1) + self._pg(), h, count=1)
        self.blocks.append({"t": "raw", "h": h})

    def img(self, b):
        if self.continues():
            self.deferred.append(b)
            return
        self.close()
        if self.pending_pg is not None:
            b["cap"] = self._pg() + (b.get("cap") or "")
        self.blocks.append(b)

    def join(self, left, right):
        """Join two lines of one paragraph, removing a line-break hyphen when it is one."""
        m = re.search(r"([" + LETTERS + r"]+)[-‑]$", left)
        rt = re.sub(r"<[^>]+>", "", re.sub(r'<span class="pg"[^>]*>\d+</span>', "", right))
        m2 = re.match(r"([" + LETTERS + r"]+)", rt)
        if m and m2 and (rt[:1].islower() or rt[:1].isdigit()):
            a, b = m.group(1).lower(), m2.group(1).lower()
            if self.words.get(a + "-" + b, 0) > self.words.get(a + b, 0):
                return left + right
            return left[:-1] + right
        if left.endswith("-") and not left.endswith(" -"):
            return left + right
        return left + " " + right

    def line(self, html, new_para, cls=None):
        if self.cur is None or new_para:
            self.close()
            self.cur = {"cls": cls, "h": self._pg() + html}
        else:
            self.cur["h"] = self.join(self.cur["h"], html)

    def continues(self):
        """True when the open paragraph looks unfinished (for joining across pages)."""
        if not self.cur:
            return False
        t = re.sub(r"<[^>]+>", "", self.cur["h"]).rstrip()
        return bool(t) and not t.endswith(SENT_END)


def words_count(doc):
    c = collections.Counter()
    for p in doc:
        for w in re.findall(r"[" + LETTERS + r"]+(?:-[" + LETTERS + r"]+)*", p.get_text()):
            c[w.lower()] += 1
            for part in w.split("-"):
                pass
    return c


# ---------------------------------------------------------------- main

def save_crop(page, clip, path, max_w, scale):
    pix = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(scale, scale), alpha=False)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    im.save(path, "WEBP", quality=64, method=6)
    return im.width, im.height


def run_text(lines):
    return " ".join(l.html() for l in lines)


def main():
    cfg = load_config(sys.argv[1])
    doc = pymupdf.open(cfg["pdf"])
    bk = Book(doc, cfg)
    words = words_count(doc)
    L = cfg["layout"]
    out = cfg["out"]
    imgdir = os.path.join(out, "img")
    os.makedirs(imgdir, exist_ok=True)
    for f in os.listdir(imgdir):
        os.remove(os.path.join(imgdir, f))

    marker_re = re.compile(cfg["marker_re"])
    chap_starts = {c["from"]: c for c in cfg["chapters"]}
    chapters = []
    flow = None
    images = []
    stats = collections.Counter()

    for pi in range(len(doc)):
        if pi in chap_starts:
            if flow:
                flow.close()
                chapters[-1]["blocks"] = flow.blocks
            c = chap_starts[pi]
            chapters.append({"title": c["title"], "section": c.get("section"), "pages": [pi + 1, c["to"] + 1], "sub": [], "blocks": []})
            flow = Flow(cfg, words)
            chapter_cfg = c
        if flow is None or pi > chapter_cfg["to"] or pi in cfg.get("skip_pages", []):
            continue
        page = doc[pi]
        lines = page_lines(page)
        # drop running header, page number and anything in the outer margins
        body = []
        for ln in lines:
            if ln.bbox.y1 < bk.top or ln.bbox.y0 > bk.bottom:
                continue
            body.append(ln)
        flow.pg_mark(pi + 1 + cfg.get("page_offset", 0))
        bk.set_page(pi + 1 + cfg.get("page_offset", 0))
        left, right = bk.left, bk.right
        hanging = chapter_cfg.get("hanging_indent")
        items, rest = bk.classify(page, pi, body)
        # group remaining lines into text items by y, keeping PDF block order inside a block
        # lines of one text block stay together, placed where the block starts
        # (a run is consecutive lines of one PDF text block without a vertical jump)
        runs, run = [], []
        for ln in rest:
            if run and (ln.block != run[-1].block or not (-2 < ln.bbox.y0 - run[-1].bbox.y1 < ln.size * 1.6)):
                runs.append(run); run = []
            run.append(ln)
        if run:
            runs.append(run)
        k = 0
        for run in runs:
            y, x = run[0].bbox.y0, min(l.bbox.x0 for l in run)
            for ln in run:
                items.append((y, x, "line", ln, k)); k += 1
        items = [it if len(it) == 5 else it + (-1,) for it in items]
        items.sort(key=lambda it: (round(it[0]), round(it[1]), it[4]))
        items = [it[:4] for it in items]
        first_line = True
        prev = None
        bullet_x = None
        prev_sh = None
        fig_n = 0
        for y, x, kind, obj in items:
            if kind == "fig":
                fig_n += 1
                name = f"p{pi + 1:03d}-{fig_n}.webp"
                clip = obj["clip"] + (-2, -2, 2, 2)
                w, h = save_crop(page, clip & page.rect, os.path.join(imgdir, name), L["img_max_w"], L["img_scale"])
                images.append("img/" + name)
                cap = run_text(obj["labels"])
                c2 = run_text(obj["cap"])
                capt = " ".join(x for x in (c2, cap) if x)
                b = {"t": "img", "src": "img/" + name, "w": w, "ht": h}
                if capt:
                    b["cap"] = capt
                flow.img(b)
                stats["figures"] += 1
                prev = None
                continue
            if kind == "box":
                flow.raw(render_box(obj, flow))
                stats["boxes"] += 1
                prev = None
                continue
            if kind == "table":
                flow.raw(render_table(obj, flow))
                stats["tables"] += 1
                prev = None
                continue
            ln = obj
            t = ln.text
            h = ln.html()
            if ln.w >= 700 and (ln.size >= L["chapter_size"] - 0.5 or abs(ln.size - L["title_size"]) < 0.5):
                # chapter (paragraph) title, e.g. "§ 1. | TITLE"; the title comes from the config
                if not any(b.get("chap") for b in flow.blocks):
                    flow.heading(2, esc(chapter_cfg.get("heading", chapter_cfg["title"])))
                    flow.blocks[-1]["chap"] = True
                prev = None
                continue
            if abs(ln.size - L["sub_size"]) < 0.5 and ln.w >= 900 and t.upper() == t and ln.color == L["text_color"]:
                # sub-heading in caps; two-line headings are merged
                if flow.blocks and flow.blocks[-1].get("sub") and prev is not None and prev.get("sub"):
                    flow.blocks[-1]["h"] += " " + h
                    chapters[-1]["sub"][-1]["title"] += " " + t
                else:
                    flow.heading(3, h)
                    flow.blocks[-1]["sub"] = True
                    chapters[-1]["sub"].append({"title": t, "b": len(flow.blocks) - 1})
                prev = {"sub": True}
                continue
            if marker_re.match(t) and ln.w >= 700 and ln.size >= L["sub_size"] - 0.5:
                flow.heading(4, h, "mk")
                prev = None
                continue
            if ln.w >= 700 and all(weight(x["font"]) >= 700 or not x["text"].strip() or x["font"] == "bullet" for x in ln.spans) \
                    and ln.bbox.x0 - left > 20 and right - ln.bbox.x1 > 20 and not t.endswith((".", ";", ",")) \
                    and abs(ln.size - L["body_size"]) < 0.6 and not (t[:1].islower() and prev_sh is None) and not (flow.continues() and prev_sh is None):
                # a centred bold line: a small heading inside the text (lines of one heading are joined)
                last = flow.blocks[-1] if flow.blocks else None
                if flow.cur is None and last and last.get("h", "").startswith('<h4 class="sh">') and prev_sh is not None \
                        and 0 <= ln.bbox.y0 - prev_sh.bbox.y1 < ln.size * 0.9:
                    last["h"] = flow.join(last["h"][:-len("</h4>")], h) + "</h4>"
                else:
                    flow.heading(4, h, "sh")
                prev = None
                prev_sh = ln
                continue
            prev_sh = None
            cls = None
            if ln.color != L["text_color"] and ln.color != 0xffffff:
                cls = "hl"
            if ln.size < L["body_size"] - 1.5:
                cls = "small"
            indent = ln.bbox.x0 - left
            new_para = False
            if prev is None or not isinstance(prev, Line):
                tail = re.sub(r"<[^>]+>", "", flow.cur["h"]).rstrip() if flow.cur else ""
                new_para = not (flow.continues() and (indent < 4 or indent > 30 or tail.endswith(("-", ","))))
            else:
                pr = prev.bbox
                gap = ln.bbox.y0 - pr.y1
                if bullet_x is not None and abs(ln.bbox.x0 - bullet_x) < 2.5 and not ln.text.startswith("•") \
                        and "Wingdings" not in ln.spans[0]["font"] and ln.spans[0]["font"] != "bullet" and gap < ln.size * 0.9:
                    new_para = False
                elif hanging:
                    new_para = indent < 4 and prev.bbox.x0 - left > 4 or indent < 4 and pr.x1 < right - 25
                elif indent > 8 and indent < 30:
                    new_para = not (pr.x1 > right - 25 and not prev.text.endswith(SENT_END))
                elif gap > ln.size * 0.9 or gap < -2:
                    new_para = True
                elif re.match(r"^(\d+\.|•|–|—)\s", re.sub(r"<[^>]+>", "", h)) or "Wingdings" in ln.spans[0]["font"]:
                    new_para = True
                elif pr.x1 < right - 25 and prev.text.endswith(SENT_END):
                    new_para = True
                elif ln.w >= 700 and prev.w < 700 and ln.spans[0]["font"] != prev.spans[-1]["font"] and pr.x1 < right - 25:
                    new_para = True
            flow.line(h, new_para, cls)
            if new_para:
                is_bul = h.startswith("•")
                bullet_x = ln.text_x0 if is_bul else None
            first_line = False
            prev = ln
    if flow:
        flow.close()
        chapters[-1]["blocks"] = flow.blocks
    for c in chapters:
        for b in c["blocks"]:
            b.pop("chap", None); b.pop("sub", None)
        for s in c["sub"]:
            s["title"] = s["title"].capitalize()
    book = {k: cfg[k] for k in ("id", "title", "subtitle", "author", "grade", "lang", "langName", "subject", "year",
                                "publisher", "school", "source", "notes") if k in cfg}
    book["format"] = 2
    book["images"] = images
    book["chapters"] = chapters
    with open(os.path.join(out, "book.json"), "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, separators=(",", ":"))
    size = sum(os.path.getsize(os.path.join(imgdir, x)) for x in os.listdir(imgdir))
    print(dict(stats), f"images {size / 1048576:.2f} MB", f"book.json {os.path.getsize(os.path.join(out, 'book.json')) / 1048576:.2f} MB")


def lines_to_paras(lines, flow):
    """Paragraphs of a small group of lines (inside a box or cell)."""
    paras, cur, prev = [], None, None
    for ln in lines:
        h = ln.html()
        if cur is None:
            cur = h
        elif re.match(r"^(\d+\.|•|–|—)\s", re.sub(r"<[^>]+>", "", h)) or (prev and prev.text.endswith(SENT_END) and
                                                                        ln.bbox.y0 - prev.bbox.y1 > 3):
            paras.append(cur); cur = h
        else:
            cur = flow.join(cur, h)
        prev = ln
    if cur:
        paras.append(cur)
    return paras


def render_box(obj, flow):
    kind = obj["kind"]
    lines = sorted(obj["lines"], key=lambda l: (round(l.bbox.y0), l.bbox.x0))
    if kind == "frame":
        return '<div class="frame">' + "".join(f"<p>{p}</p>" for p in lines_to_paras(lines, flow)) + "</div>"
    head, rest = lines[0], lines[1:]
    body = " ".join(lines_to_paras(rest, flow))
    return f'<div class="kbox {kind}"><b>{head.html()}</b> {body}</div>'


def render_table(tab, flow):
    h = '<div class="tbl">'
    if tab["title"]:
        h += "<p class=\"tt\">" + " ".join(l.html() for l in tab["title"]) + "</p>"
    h += "<table>"
    for ri, row in enumerate(tab["rows"]):
        cells = [c for c in row if c is not None]
        head = ri == 0 and all(c and all(l.color == 0xffffff or l.w >= 700 for l in c) for c in cells)
        tag = "th" if head else "td"
        h += "<tr>" + "".join(f"<{tag}>" + "<br>".join(lines_to_paras(sorted(c, key=lambda l: (round(l.bbox.y0), l.bbox.x0)), flow)) + f"</{tag}>"
                              for c in cells) + "</tr>"
    return h + "</table></div>"


if __name__ == "__main__":
    main()
