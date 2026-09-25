#!/usr/bin/env python3
"""Convert a typeset maths textbook PDF (new kitep.edu.kg editions) into the reader's book.json.

Usage: python3 convert_math.py /mnt/project-files/pilot-book/<book>.config.json

Maths pages mix running text with worked solutions, number lines, colour notes and
fractions. Reflowing all of that as text would break it, so this converter:
  * keeps running text, exercise lists and one-line formulas as real text
    (italic variables, simple fractions as HTML fractions, a/б/в badges);
  * crops worked solutions ("Решение" areas), diagrams, side notes and tables that are
    drawn as pictures, splitting wide ones into narrow pieces (e.g. part "a" and part "б")
    so their text stays readable on a phone;
  * turns the upside-down answers printed under "Попробуйте!" into tap-to-open answers;
  * removes the big diagonal kitep.edu.kg watermark before cropping.
Printed page numbers are kept as markers, like in the other books.
"""
import collections, json, os, re, sys

import pymupdf
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_layout import Flow, esc, weight, merge_rects, load_config, LETTERS, SENT_END  # noqa: E402

ONLY = {int(x) for x in os.environ.get("PAGES", "").split(",") if x}  # debugging: convert only these page indexes
TAB_RE = re.compile(r"[\t\x07\x08]+")
CYR_WORD = re.compile(r"[А-Яа-яЁёҢңӨөҮү]{2,}")


def clean(t):
    return TAB_RE.sub(" ", t)


# ---------------------------------------------------------------- document prep

def open_doc(path):
    with open(path, "rb") as f:
        doc = pymupdf.open(stream=f.read(), filetype="pdf")  # the shared folder is slow to seek in
    # the watermark is a form XObject with one huge line of text; empty it
    seen = set()
    for p in doc:
        for x in p.get_xobjects():
            xref, bb = x[0], x[3]
            if xref in seen:
                continue
            seen.add(xref)
            if abs(bb[1] + 120) < 2 and bb[3] - bb[1] < 140 and bb[2] - bb[0] > 300:
                doc.update_stream(xref, b"")
    return doc


# ---------------------------------------------------------------- lines

class MLine:
    def __init__(self, spans, bbox):
        self.spans = spans
        self.bbox = pymupdf.Rect(bbox)
        main = max(spans, key=lambda s: len(s["text"].strip()) or 0.01)
        self.size = round(main["size"], 1)
        self.font = main["font"]
        self.color = main["color"]
        self.w = weight(self.font) if re.search(r"-\d00", self.font) else (700 if "Bold" in self.font else 500)

    @property
    def text(self):
        return clean("".join(s["text"] for s in self.spans)).strip()

    def first(self):
        return next((s for s in self.spans if s["text"].strip()), self.spans[0])

    def html(self, skip_first=False):
        out = []
        spans = [s for s in self.spans if s["text"] != ""]
        if skip_first:
            f = self.first()
            spans = spans[spans.index(f) + 1:]
        for s in spans:
            if s.get("_done"):
                continue
            fr = s.get("_frac")
            if fr is not None:
                bar = fr[0]
                num = "".join(span_html(x) for x in bar["num"])
                den = "".join(span_html(x) for x in bar["den"])
                for x in bar["num"] + bar["den"]:
                    x["_done"] = True
                out.append(f'<span class="fr"><span>{num.strip()}</span><span>{den.strip()}</span></span>')
                continue
            if is_badge(s):
                out.append(f' <b class="bd">{esc(badge_letter(s["text"].strip()))}</b> ')
                continue
            if is_number_badge(s):
                out.append(f'<b class="nb">{esc(s["text"].strip())}</b> ')
                continue
            out.append(span_html(s))
        h = "".join(out)
        h = re.sub(r"</(i|b)>(\s*)<\1>", r"\2", h)
        h = re.sub(r"[  ]* [   ]*", " ", h)
        return re.sub(r" {2,}", " ", h).strip("  ")


def span_html(s):
    t = esc(clean(s["text"]))
    if not t.strip():
        return t
    f = s["font"]
    if "Italic" in f and "Bahnschrift" not in f:
        t = f"<i>{t}</i>"
    if (("Bold" in f or "Black" in f) and s["size"] >= 9) or (s["color"] == 0xffffff and f.startswith("Bahnschrift")):
        t = f"<b>{t}</b>"
    return t


def is_badge(s):
    # white letter on a black circle: a, б, в, г ... (item markers)
    return (s["font"].startswith("Bahnschrift") or s["font"] == "Lato-Medium") and abs(s["size"] - 9) < 0.3 and len(s["text"].strip()) == 1 \
        and s["text"].strip().lower() in "aабвгдеж"


def badge_letter(c):
    return {"a": "а"}.get(c, c)


def is_number_badge(s):
    return "Lato-Medium" in s["font"] and abs(s["size"] - 9) < 0.3 and s["color"] == 0xffffff and s["text"].strip().isdigit()


def page_content(page):
    """Normal lines (glued), upside-down answer lines and rotated labels."""
    raw, answers, labels = [], [], []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            spans = [dict(s) for s in l["spans"] if s["text"] != ""]
            if not spans or not "".join(s["text"] for s in spans).strip():
                continue
            d = l["dir"]
            if abs(d[0] - 1) < 0.02 and abs(d[1]) < 0.02:
                raw.append({"bbox": pymupdf.Rect(l["bbox"]), "spans": spans})
            elif d[0] < -0.9:
                answers.append({"bbox": pymupdf.Rect(l["bbox"]), "text": clean("".join(s["text"] for s in spans)).strip()})
            else:
                labels.append({"bbox": pymupdf.Rect(l["bbox"]), "text": clean("".join(s["text"] for s in spans)).strip()})
    # glue pieces of one visual line (baseline shifts for fractions split PDF lines)
    raw.sort(key=lambda r: (r["bbox"].x0))
    lines = []
    for r in sorted(raw, key=lambda r: (round(r["bbox"].y0), r["bbox"].x0)):
        best = None
        for ln in lines:
            a, b = ln["bbox"], r["bbox"]
            ov = min(a.y1, b.y1) - max(a.y0, b.y0)
            if ov >= 0.5 * min(a.height, b.height) and -12 <= b.x0 - a.x1 < 16:
                best = ln
                break
        if best:
            best["spans"] += r["spans"]
            best["bbox"] |= r["bbox"]
        else:
            lines.append({"bbox": pymupdf.Rect(r["bbox"]), "spans": list(r["spans"])})
    # short formulas with their explanation on the same row ("4 < 6      4 меньше 6.")
    lines.sort(key=lambda l: (round(l["bbox"].y0), l["bbox"].x0))
    k = 0
    while k < len(lines) - 1:
        a, b = lines[k], lines[k + 1]
        ta = "".join(s["text"] for s in a["spans"]).strip()
        if abs(a["bbox"].y0 - b["bbox"].y0) < 1.5 and abs(a["bbox"].y1 - b["bbox"].y1) < 1.5 and len(ta) <= 14 \
                and 0 < b["bbox"].x0 - a["bbox"].x1 < 90 and abs(a["spans"][0]["size"] - b["spans"][0]["size"]) < 0.5:
            sp = dict(a["spans"][-1], text=" \u2003 ", bbox=(a["bbox"].x1, a["bbox"].y0, b["bbox"].x0, a["bbox"].y1))
            a["spans"] += [sp] + b["spans"]
            a["bbox"] |= b["bbox"]
            del lines[k + 1]
            continue
        k += 1
    out = []
    for ln in lines:
        ln["spans"].sort(key=lambda s: s["bbox"][0])
        out.append(MLine(ln["spans"], ln["bbox"]))
    return out, answers, labels


def mark_fractions(page, lines, bars):
    for bar in bars:
        num, den = [], []
        for ln in lines:
            for s in ln.spans:
                if not s["text"].strip():
                    continue
                b = pymupdf.Rect(s["bbox"])
                cx = (b.x0 + b.x1) / 2
                if not (bar.x0 - 1.5 <= cx <= bar.x1 + 1.5) or b.width > bar.width + 6:
                    continue
                cy = (b.y0 + b.y1) / 2
                if cy < bar.y0 and b.y0 >= bar.y0 - 15:
                    num.append(s)
                elif cy > bar.y0 and b.y1 <= bar.y0 + 15:
                    den.append(s)
        if num and den:
            info = {"num": sorted(num, key=lambda s: s["bbox"][0]), "den": sorted(den, key=lambda s: s["bbox"][0])}
            first = min(num + den, key=lambda s: s["bbox"][0])
            for s in num + den:
                s["_frac"] = None
            first["_frac"] = (info,)
            for s in num + den:
                if s is not first:
                    s["_done"] = True


# ---------------------------------------------------------------- regions

def light(c):
    return c is not None and min(c) > 0.85


def classify_drawings(page, lines, cfg, heading_lines):
    """Return (fraction bars, solution areas, figure pieces)."""
    bars, sol, pieces = [], [], []
    body = pymupdf.Rect(0, cfg["layout"]["top"], page.rect.width, cfg["layout"]["bottom"])
    white_spans = [sp for ln in lines for sp in ln.spans if sp["color"] == 0xffffff and sp["text"].strip()]
    for dr in page.get_drawings():
        r = pymupdf.Rect(dr["rect"])
        fill, stroke = dr.get("fill"), dr.get("color")
        if (dr.get("fill_opacity") or 1) < 0.05:
            fill = None
        if not dr.get("width"):
            stroke = None if dr["type"] == "s" else stroke
        if r.height < 1.0 and 3 < r.width < 70 and stroke is not None and max(stroke) < 0.4:
            bars.append(r)
            continue
        r &= page.rect
        if r.is_empty or not r.intersects(body) or r.get_area() > 0.4 * page.rect.get_area():
            continue
        area = r.get_area()
        if fill is not None and max(fill) < 0.6 and any(
                (pymupdf.Rect(sp["bbox"]) & r).get_area() > 0.6 * pymupdf.Rect(sp["bbox"]).get_area()
                for sp in white_spans):
            continue  # dark tab or badge behind white text ("Решение:", "а", "б")
        if fill is not None and min(fill) > 0.97 and area > 4000:
            if area < 0.5 * body.get_area():
                sol.append(r)  # white card (worked solution)
            continue
        if r.width < 18 and r.height < 18 and any(
                len(sp["text"].strip()) == 1 and r.contains(pymupdf.Point((sp["bbox"][0] + sp["bbox"][2]) / 2, (sp["bbox"][1] + sp["bbox"][3]) / 2 + 2))
                for ln in lines for sp in ln.spans):
            continue  # round badge with a letter
        if fill is not None and light(fill) and stroke is None and area > 40000:
            continue  # panel background
        if fill is not None and min(fill) > 0.97 and stroke is None:
            continue
        if fill is not None and any(r.intersects(h.bbox) for h in heading_lines):
            continue  # tab behind "Пример 3", banner behind a heading
        if r.width < 16 and r.height < 16 and any(is_badge(s) or is_number_badge(s) for ln in lines for s in ln.spans
                                                  if pymupdf.Rect(s["bbox"]).intersects(r)):
            continue
        if any(0 <= h.bbox.x0 - r.x1 < 40 and r.width < 90 and r.height < 70 and r.y0 < h.bbox.y1 + 10 and r.y1 > h.bbox.y0 - 25
               for h in heading_lines):
            continue  # pictogram before a heading
        if fill is not None and area < 6000 and any(0 <= r.x0 - h.bbox.x1 < 80 and r.y0 < h.bbox.y1 + 12 and r.y1 > h.bbox.y0 - 12
                                                    and h.size >= 14 for h in heading_lines):
            continue  # shape at the end of a heading banner
        if area < 1500 and any((r + (-30, -30, 30, 30)).intersects(h.bbox) for h in heading_lines):
            continue  # corner squares around the "Пример" tab
        if dr["type"] != "s" and any(r.contains(ln.bbox) and is_prose(ln) for ln in lines):
            continue  # a frame or highlight around sentences
        pieces.append(r)
    for im in page.get_image_info():
        r = pymupdf.Rect(im["bbox"]) & page.rect
        if r.is_empty or not r.intersects(body) or r.get_area() > 0.4 * page.rect.get_area():
            continue
        if any(0 <= h.bbox.x0 - r.x1 < 40 and r.width < 90 and r.height < 70 for h in heading_lines):
            continue
        pieces.append(r)
    return bars, sol, pieces


def split_columns(page, clip, lines, min_gap=14, max_w=330):
    """Split a wide crop at empty vertical gutters (e.g. between part a and part б)."""
    if clip.width <= max_w:
        return [clip]
    occ = []
    for ln in lines:
        for s in ln.spans:
            if s["text"].strip():
                b = pymupdf.Rect(s["bbox"]) & clip
                if not b.is_empty:
                    occ.append((b.x0, b.x1))
    for dr in page.get_drawings():
        r = pymupdf.Rect(dr["rect"]) & clip
        if r.is_empty or (r.width > 0.8 * clip.width):
            continue
        fill = dr.get("fill")
        if fill is not None and min(fill) > 0.97 and dr.get("color") is None:
            continue
        occ.append((r.x0, r.x1))
    for im in page.get_image_info():
        r = pymupdf.Rect(im["bbox"]) & clip
        if not r.is_empty and r.width < 0.8 * clip.width:
            occ.append((r.x0, r.x1))
    if not occ:
        return [clip]
    occ.sort()
    merged = [list(occ[0])]
    for a, b in occ[1:]:
        if a <= merged[-1][1] + 0.5:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    cuts = []
    for (a0, a1), (b0, b1) in zip(merged, merged[1:]):
        if b0 - a1 >= min_gap and a1 - clip.x0 > 60 and clip.x1 - b0 > 60:
            cuts.append((a1 + b0) / 2)
    if not cuts:
        return [clip]
    parts, x = [], clip.x0
    for c in cuts + [clip.x1]:
        part = pymupdf.Rect(x, clip.y0, c, clip.y1)
        # trim the part to its content
        xs = [(a, b) for a, b in occ if a >= part.x0 - 0.5 and b <= part.x1 + 0.5]
        if xs:
            part = pymupdf.Rect(min(a for a, _ in xs) - 4, clip.y0, max(b for _, b in xs) + 4, clip.y1)
            parts.append(part)
        x = c
    return parts or [clip]


def trim_vertical(page, clip, lines):
    """Tighten a crop to the content inside it (drops empty panel space above and below)."""
    ys = []
    for ln in lines:
        if (ln.bbox & clip).get_area() > 0.5 * ln.bbox.get_area():
            ys.append((ln.bbox.y0, ln.bbox.y1))
    for dr in page.get_drawings():
        r = pymupdf.Rect(dr["rect"])
        fill = dr.get("fill")
        if (r & clip).is_empty or (fill is not None and min(fill) > 0.97 and dr.get("color") is None):
            continue
        if r.width > 0.9 * clip.width and r.height > 0.9 * clip.height:
            continue
        r &= clip
        ys.append((r.y0, r.y1))
    if not ys:
        return clip
    return pymupdf.Rect(clip.x0, max(clip.y0, min(a for a, _ in ys) - 4), clip.x1, min(clip.y1, max(b for _, b in ys) + 4))


# ---------------------------------------------------------------- main

def save_crop(page, clip, path, scale, max_w):
    pix = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(scale, scale), alpha=False)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    im.save(path, "WEBP", quality=62, method=6)
    return im.width, im.height


def style_of(ln, cfg):
    s = ln.first()
    for rule in cfg["styles"]:
        if rule["font"] in s["font"] and abs(s["size"] - rule["size"]) < 0.3 and \
                ("color" not in rule or s["color"] == rule["color"]):
            if "text_re" in rule and not re.match(rule["text_re"], ln.text):
                continue
            return rule["kind"]
    return None


def xy_cut(elems, gy=1.0, gx=10):
    """Recursive XY-cut: returns elements in reading order; a leaf holding a picture becomes one picture."""
    if len(elems) <= 1:
        return elems
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
            return [x for g in groups for x in xy_cut(g, gy, gx)]
    if any(e[0] == "fig" for e in elems):
        heads = sorted([e for e in elems if e[0] in ("head", "tbl")], key=lambda e: e[1].y0)
        rest = [e for e in elems if e[0] not in ("head", "tbl")]
        r = pymupdf.Rect(rest[0][1])
        for e in rest[1:]:
            r |= e[1]
        return heads + [("fig", r, r)]
    return sorted(elems, key=lambda e: (e[1].y0, e[1].x0))


def is_prose(ln):
    """Ordinary sentence text (stays as text even when a picture is next to it)."""
    t = ln.text
    return ln.size >= 9.5 and not ln.font.startswith("Bahnschrift") and len(CYR_WORD.findall(t)) >= 3


def is_math_line(t):
    t2 = re.sub(r"^Решение:?", "", t).strip()
    words = CYR_WORD.findall(t2)
    ops = len(re.findall(r"[=+×÷–−<>≤≥√]", t2))
    if not t2:
        return False
    if "=" in t2 and len(words) <= 1:
        return True
    return len(words) == 0 and ops >= 1 and len(re.findall(r"\d", t2)) >= 1


def main():
    cfg = load_config(sys.argv[1])
    L = cfg["layout"]
    doc = open_doc(cfg["pdf"])
    out = cfg["out"]
    imgdir = os.path.join(out, "img")
    os.makedirs(imgdir, exist_ok=True)
    for f in os.listdir(imgdir):
        os.remove(os.path.join(imgdir, f))
    words = collections.Counter(w.lower() for p in doc for w in re.findall(r"[" + LETTERS + r"]+(?:-[" + LETTERS + r"]+)*", p.get_text()))
    chap_starts = {c["from"]: c for c in cfg["chapters"]}
    image_pages = set(cfg.get("image_pages", []))
    chapters, images = [], []
    flow = chap = None
    stats = collections.Counter()

    def add_img(page, pi, clip, n, cap=None, ans=None):
        name = f"p{pi + cfg['page_offset'] + 1:03d}-{n}.webp"
        w, h = save_crop(page, clip, os.path.join(imgdir, name), L["img_scale"], L["img_max_w"])
        images.append("img/" + name)
        b = {"t": "img", "src": "img/" + name, "w": w, "ht": h, "dw": round(clip.width / L["body_pt"], 1)}
        if cap:
            b["cap"] = cap
        flow.img(b)
        stats["pictures"] += 1

    for pi in range(len(doc)):
        if pi in chap_starts:
            if flow:
                flow.close()
                chapters[-1]["blocks"] = flow.blocks
            chap = chap_starts[pi]
            chapters.append({"title": chap["title"], "section": chap.get("section"), "pages": [pi + 1 + cfg["page_offset"], chap["to"] + 1 + cfg["page_offset"]],
                             "sub": [], "blocks": []})
            flow = Flow(cfg, words)
            flow.heading(2, esc(chap["title"]))
        if flow is None or pi > chap["to"] or pi in cfg.get("skip_pages", []):
            continue
        if ONLY and pi not in ONLY:
            continue
        page = doc[pi]
        printed = pi + 1 + cfg["page_offset"]
        flow.pg_mark(printed)
        n_img = 0
        if pi in image_pages:
            n_img += 1
            add_img(page, pi, pymupdf.Rect(0, L["top"], page.rect.width, L["bottom"]), n_img)
            continue
        _drs = page.get_drawings()
        page.get_drawings = lambda: _drs
        lines, answers, labels = page_content(page)
        lines = [ln for ln in lines if L["top"] < ln.bbox.y1 and ln.bbox.y0 < L["bottom"]]
        answers = [a for a in answers if L["top"] < a["bbox"].y1 and a["bbox"].y0 < L["bottom"] + 10]
        kinds = {id(ln): style_of(ln, cfg) for ln in lines}
        lines = [ln for ln in lines if kinds[id(ln)] != "skip"]
        heads = [ln for ln in lines if kinds[id(ln)] in ("ex", "try", "h3", "h4", "title")]
        bars, sols, pieces = classify_drawings(page, lines, cfg, heads)
        goal = []
        if pi == chap["from"] and L.get("header_bottom"):
            hb = L["header_bottom"]
            pieces = [pymupdf.Rect(r.x0, max(r.y0, hb), r.x1, r.y1) for r in pieces if r.y1 > hb + 3]
            goal = [ln for ln in lines if ln.bbox.y1 <= hb and ln not in heads]
            lines = [ln for ln in lines if ln not in goal]
            if goal:
                flow.raw('<p class="goal"><b>%s</b> %s</p>' % (esc(cfg.get("goal_label", "Цель обучения:")), " ".join(g.html() for g in goal)))
        mark_fractions(page, lines, bars)

        # graphic atoms: drawings/images plus the labels drawn on or right next to them
        # real tables (grid with text in most cells) become HTML tables
        tables = []
        for t in page.find_tables().tables:
            rows = t.extract()
            cells = [c for r in rows for c in r]
            full = [c for c in cells if c and c.strip()]
            tb = pymupdf.Rect(t.bbox)
            if t.col_count >= 2 and t.row_count >= 3 and len(full) >= 0.7 * len(cells) and tb.y0 >= L["top"] \
                    and sum(1 for c in rows[0] if c and c.strip()) >= 2 and not any(ln.bbox.intersects(tb) for ln in heads):
                tables.append((tb, rows))
        if tables:
            inside_t = lambda r: any((r & tb).get_area() > 0.6 * max(r.get_area(), 0.01) for tb, _ in tables)
            pieces = [r for r in pieces if not inside_t(r)]
            lines = [ln for ln in lines if not inside_t(ln.bbox)]
        # a label joins the graphic it sits on or right next to (checked against the drawn
        # parts only, so a picture never snowballs over the text around it)
        base = merge_rects(pieces, 3)
        grabbed = set()
        extra = []
        for ln in lines:
            if ln in heads:
                continue
            prose = is_prose(ln)
            tiny = len(ln.text) <= 4 or bool(re.fullmatch(r"[\d\s\u2009\u2003–−+\-.,()xyабвг]+", ln.text))
            for g in base:
                if (ln.bbox & g).get_area() > 0.5 * ln.bbox.get_area() or \
                        (not prose and ln.bbox.intersects(g + (-5, -5, 5, 5))) or \
                        (not prose and ln.size <= 9 and ln.bbox.intersects(g + (-10, -10, 10, 10))) or \
                        (tiny and ln.bbox.intersects(g + (-12, -12, 12, 12))):
                    grabbed.add(id(ln))
                    extra.append(ln.bbox)
                    if os.environ.get("DEBUG"):
                        print("  grab", repr(ln.text[:40]), [round(v) for v in ln.bbox], "into", [round(v) for v in g])
                    break
        for ln in lines:
            if id(ln) in grabbed or ln in heads:
                continue
            col = ln.first()["color"]
            if (ln.size <= 9 and col not in (0, 0xffffff) and not is_prose(ln)) or (ln.size >= 14 and len(ln.text) <= 6):
                grabbed.add(id(ln))
                extra.append(ln.bbox)
        atoms = merge_rects(base + extra, 1)
        # lines now mostly inside a merged picture belong to it too
        for ln in lines:
            if id(ln) not in grabbed and ln not in heads and any((ln.bbox & g).get_area() > 0.6 * ln.bbox.get_area() for g in atoms):
                grabbed.add(id(ln))
        atoms = [r for r in atoms if r.get_area() > 150]
        if os.environ.get("DEBUG"):
            print(pi, "atoms", [[round(v) for v in r] for r in atoms])
        elems = [("fig", r, r) for r in atoms]
        # busy worked solutions (bar models, fractions) are kept whole, one picture per row band
        banded = []
        for card in merge_rects(sols, 0):
            ins = lambda r: card.contains(pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
            nfig = sum(1 for r in atoms if ins(r))
            if nfig > 3 or (nfig and any(ins(bar) for bar in bars)):
                banded.append(card)
        if banded:
            rest, bands = [], []
            cand = elems + [("head" if ln in heads else "line", ln.bbox, ln) for ln in lines if id(ln) not in grabbed]
            taken = set()
            for card in banded:
                inner = [e for e in cand if card.contains(pymupdf.Point((e[1].x0 + e[1].x1) / 2, (e[1].y0 + e[1].y1) / 2))]
                if not inner:
                    continue
                for e in inner:
                    taken.add(id(e[2]))
                r = pymupdf.Rect(inner[0][1])
                for e in inner[1:]:
                    r |= e[1]
                bands.append(("fig", r, r))
            for ln in lines:
                if id(ln) in taken:
                    grabbed.add(id(ln))
            elems = [e for e in elems if id(e[2]) not in taken] + [b for b in bands if b[0] == "fig"]
            loose_lines = [b for b in bands if b[0] != "fig"]
            for b in loose_lines:
                grabbed.discard(id(b[2]))
            extra_elems = []
        else:
            extra_elems = []
        elems += [("head" if ln in heads else "line", ln.bbox, ln) for ln in lines if id(ln) not in grabbed]
        elems += [e for e in extra_elems if e not in elems]
        elems += [("ans", a["bbox"], a) for a in answers]
        elems += [("tbl", tb, rows) for tb, rows in tables]
        items = [(0, 0, "line" if k == "head" else k, o) for k, _, o in xy_cut(elems)]
        # answers: upside-down lines of one answer are read bottom-up; group those close together
        prev = None
        pend_ans = []

        def flush_ans():
            if pend_ans:
                txt = " ".join(a["text"] for a in sorted(pend_ans, key=lambda a: (-a["bbox"].y0, -a["bbox"].x0)))
                txt = re.sub(r"(?<![A-Za-z])a\)", "а)", txt)
                flow.raw(f'<details class="ans"><summary>{esc(cfg.get("answer_label", "Ответ"))}</summary>{esc(txt)}</details>')
                stats["answers"] += 1
                pend_ans.clear()

        for y, x, kind, obj in items:
            if kind != "ans":
                if pend_ans and not (kind == "line" and False):
                    flush_ans()
            if kind == "ans":
                if pend_ans and abs(obj["bbox"].y0 - pend_ans[-1]["bbox"].y0) > 30:
                    flush_ans()
                pend_ans.append(obj)
                continue
            if kind == "tbl":
                def cell(c):
                    return esc(re.sub(r"\s+", " ", clean(c or "")).strip())
                h = "<tr>" + "".join(f"<th>{cell(c)}</th>" for c in obj[0]) + "</tr>"
                h += "".join("<tr>" + "".join(f"<td>{cell(c)}</td>" for c in r) + "</tr>" for r in obj[1:])
                flow.raw(f'<div class="tbl"><table>{h}</table></div>')
                stats["tables"] += 1
                prev = None
                continue
            if kind in ("sol", "fig"):
                parts = [obj & page.rect]
                for part in parts:
                    n_img += 1
                    add_img(page, pi, part, n_img)
                if kind == "sol":
                    stats["solutions"] += 1
                prev = None
                continue
            ln = obj
            k = kinds[id(ln)]
            t = ln.text
            if k == "title" and pi != chap["from"]:
                k = "h3"
            if k == "title":
                prev = None
                continue
            if k in ("ex", "try"):
                first = esc(clean(ln.first()["text"]).strip())
                flow.heading(4, first, k)
                rest = ln.html(skip_first=True)
                if rest:
                    flow.line(rest, True)
                    prev = ln
                else:
                    prev = None
                continue
            if k == "h3":
                if flow.blocks and flow.blocks[-1].get("_h3") and prev is not None and getattr(prev, "_h3", False) \
                        and ln.bbox.y0 - prev.bbox.y1 < 8:
                    flow.blocks[-1]["h"] += " " + ln.html()
                    chapters[-1]["sub"][-1]["title"] += " " + t
                else:
                    flow.heading(3, ln.html())
                    flow.blocks[-1]["_h3"] = True
                    chapters[-1]["sub"].append({"title": t, "b": len(flow.blocks) - 1})
                ln._h3 = True
                prev = ln
                continue
            if k == "h4":
                flow.heading(4, ln.html(), "mk")
                prev = None
                continue
            h = ln.html()
            if not h:
                continue
            math = is_math_line(t)
            cls = "ml" if math else ("side" if ln.size < 9.5 and ln.size >= 7.5 else None)
            if prev is None or not isinstance(prev, MLine) or getattr(prev, "_h3", False):
                new = not (flow.continues() and not math and not re.match(r"^(\S{1,2}\s)", t) and prev is None and flow.cur is not None)
            else:
                gap = ln.bbox.y0 - prev.bbox.y1
                starts_item = bool(re.match(r"^<b class=\"(bd|nb)\">", h)) or bool(re.match(r"^(\d+[.)]|•)\s", t))
                new = (math or getattr(prev, "_math", False) or starts_item or gap > ln.size * 0.6 or gap < -4
                       or abs(ln.bbox.x0 - prev.bbox.x0) > 14 and not (prev.text.endswith(("-", ",")) or not prev.text.endswith(SENT_END))
                       or (prev.text.endswith(SENT_END) and prev.bbox.x1 < L["right"] - 45)
                       or cls != (flow.cur or {}).get("cls"))
            ln._math = math
            flow.line(h, new, cls)
            prev = ln
        flush_ans()
    if flow:
        flow.close()
        chapters[-1]["blocks"] = flow.blocks
    for c in chapters:
        for b in c["blocks"]:
            b.pop("_h3", None)
    book = {k: cfg[k] for k in ("id", "title", "subtitle", "author", "grade", "lang", "langName", "subject", "year",
                                "publisher", "school", "source", "notes") if k in cfg}
    book["format"] = 2
    book["images"] = images
    book["chapters"] = chapters
    with open(os.path.join(out, "book.json"), "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, separators=(",", ":"))
    size = sum(os.path.getsize(os.path.join(imgdir, x)) for x in os.listdir(imgdir))
    print(dict(stats), f"images {size / 1048576:.2f} MB", f"book.json {os.path.getsize(os.path.join(out, 'book.json')) / 1048576:.2f} MB")


if __name__ == "__main__":
    main()
