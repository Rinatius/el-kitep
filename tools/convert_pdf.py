#!/usr/bin/env python3
"""Convert a scanned textbook PDF with an OCR text layer into reader-app book format.

Usage: python3 convert_pdf.py book_config.json

The text comes only from the PDF's own text layer (no new OCR). The converter:
  * drops page numbers,
  * rebuilds paragraphs across lines and pages and removes line-break hyphens,
  * keeps poems line by line (stanza gaps kept),
  * turns headings, glossary entries and question lists into structured HTML,
  * cuts out illustrations the OCR layer marks as separate pictures,
  * fixes a small, logged set of systematic OCR mistakes using the book's own vocabulary.
Every automatic text correction is written to corrections.tsv for review.
"""
import collections, html, io, json, os, re, sys, unicodedata
import pymupdf
from PIL import Image

LETTERS = "A-Za-zА-Яа-яЁёӨөҮүҢңІіЇїЄєҒғҚқҰұҺһӘә"
WORD_RE = re.compile(f"[{LETTERS}]+")
KG_SPECIFIC = set("өүңӨҮҢ")
LAT2CYR = str.maketrans("AaBCcEeHKMOoPpTXxYy", "АаВСсЕеНКМОоРрТХхУу")
HYPHENS = "-‐‑–—"


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    for k in ("pdf", "out"):
        cfg[k] = os.path.normpath(os.path.join(base, cfg[k]))
    return cfg


# ---------------------------------------------------------------- extraction

class Line:
    __slots__ = ("page", "block", "x0", "y0", "x1", "y1", "spans", "size", "arial", "bold", "italic")

    def __init__(self, page, block, bbox, spans):
        self.page, self.block = page, block
        self.x0, self.y0, self.x1, self.y1 = bbox
        # spans: list of [text, bold, italic]
        self.spans = spans
        chars = collections.Counter()
        for s, sp in zip(spans, spans):
            pass
        self.size = 0
        self.arial = self.bold = self.italic = False

    @property
    def text(self):
        return "".join(s[0] for s in self.spans)


def extract(doc, cfg):
    pages = {}
    figures = collections.defaultdict(list)
    skip = set(cfg.get("skip_pages", []))
    for pi in range(doc.page_count):
        if pi in skip:
            continue
        page = doc[pi]
        pw, ph = page.rect.width, page.rect.height
        lines = []
        d = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
        for b in d["blocks"]:
            for l in b.get("lines", []):
                spans, weight = [], collections.Counter()
                for s in l["spans"]:
                    t = s["text"]
                    if not t:
                        continue
                    font = s["font"].split("+")[-1]
                    bold = bool(s["flags"] & 16) or "Bold" in font
                    italic = bool(s["flags"] & 2) or "Italic" in font
                    spans.append([t, bold, italic])
                    n = len(t.strip())
                    weight["arial" if ("Arial" in font or "Gothic" in font) else "times"] += n
                    weight["bold"] += n if bold else 0
                    weight["italic"] += n if italic else 0
                    weight[("size", round(s["size"]))] += n
                    weight["all"] += n
                if not spans or not "".join(s[0] for s in spans).strip():
                    continue
                fixes = cfg.get("line_fixes", {}).get(str(pi + 1), {})
                whole = "".join(s[0] for s in spans).strip()
                if whole in fixes:
                    spans = [[fixes[whole], spans[0][1], spans[0][2]]]
                ln = Line(pi, b["number"], l["bbox"], spans)
                tot = max(weight["all"], 1)
                ln.arial = weight["arial"] > weight["times"]
                ln.bold = weight["bold"] > tot * 0.6
                ln.italic = weight["italic"] > tot * 0.6
                sizes = [(v, k[1]) for k, v in weight.items() if isinstance(k, tuple)]
                ln.size = max(sizes)[1] if sizes else 11
                lines.append(ln)
        pages[pi] = (lines, pw, ph)
        # Illustrations: image blocks that are not the full-page scan.
        for info in page.get_image_info(xrefs=True):
            x0, y0, x1, y1 = info["bbox"]
            w, h = x1 - x0, y1 - y0
            if w > pw * 0.9 and h > ph * 0.9:
                continue
            if w < 40 or h < 40:
                continue
            figures[pi].append({"bbox": (x0, y0, x1, y1), "xref": info["xref"]})
    return pages, figures


# ---------------------------------------------------------------- vocabulary / OCR fixes

class Fixer:
    def __init__(self, pages, cfg):
        self.log = []
        self.cfg = cfg
        self.vocab = collections.Counter()
        for lines, _, _ in pages.values():
            for ln in lines:
                for w in WORD_RE.findall(ln.text):
                    self.vocab[w.lower()] += 1
        self.manual = cfg.get("manual_fixes", {})
        self.keep = set(w.lower() for w in cfg.get("keep_words", []))

    def freq(self, w):
        return self.vocab.get(w.lower(), 0)

    def _case_like(self, src, dst):
        if src.isupper() and len(src) > 1:
            return dst.upper()
        if src[:1].isupper():
            return dst[:1].upper() + dst[1:]
        return dst

    def fix_word(self, w, page):
        orig = w
        lw = w.lower()
        # Latin look-alike letters inside Cyrillic words.
        if re.search("[А-Яа-яӨөҮүҢң]", w) and re.search("[A-Za-z]", w):
            w = w.translate(LAT2CYR)
            lw = w.lower()
        # ABBYY sometimes reads the Kyrgyz letter ү (and rarely ң) as ц.
        if "ц" in lw and len(lw) > 1 and lw not in self.keep:
            best, bf = None, 0
            for rep in ("ү", "ң"):
                c = lw.replace("ц", rep)
                f = self.freq(c)
                if f > bf:
                    best, bf = c, f
            if best and (bf >= 1 or KG_SPECIFIC & set(lw)) and self.freq(lw) <= bf:
                w = self._case_like(w, best)
                lw = best
            elif (KG_SPECIFIC & set(lw) or "цц" in lw or lw.endswith("ц")) and not re.search("ңц|цң|ц[иа]", lw) and len(lw) > 1:
                w = self._case_like(w, lw.replace("ц", "ү"))
                lw = w.lower()
        # In capitals ABBYY often reads Е as Б (КАСЫМББКОВ, МЕНБН).
        if w.isupper() and "б" in lw and self.freq(lw) <= 1:
            idx = [i for i, ch in enumerate(lw) if ch == "б"][:4]
            best, bf = None, 0
            for mask in range(1, 1 << len(idx)):
                c = list(lw)
                for k, i in enumerate(idx):
                    if mask >> k & 1:
                        c[i] = "е"
                c = "".join(c)
                if self.freq(c) > bf:
                    best, bf = c, self.freq(c)
            if best:
                w, lw = best.upper(), best
        # Single-letter confusions, only for rare words whose fix is common in this book.
        if len(lw) >= 4 and self.freq(lw) <= 1 and lw not in self.keep:
            pairs = (("в", "б"), ("п", "л"), ("г", "т"), ("е", "ө"), ("е", "с"), ("о", "ө"),
                     ("у", "ү"), ("н", "ң"), ("и", "й"), ("ш", "щ"), ("ь", "ы"))
            best, bf = None, 3
            for a, b in pairs:
                for i, ch in enumerate(lw):
                    if ch != a:
                        continue
                    before = lw[i - 1] if i else ""
                    if a == "г" and before and before in "аеёиоуыэюяөү":
                        continue  # between vowels г is usually a real г (ага, бага, жагат)
                    if a in "пн" and i == len(lw) - 1:
                        continue  # final п/н are common real endings (сымап, күнүн)
                    if True:
                        c = lw[:i] + b + lw[i + 1:]
                        f = self.freq(c)
                        if f > bf:
                            best, bf = c, f
            if best:
                w = self._case_like(w, best)
        if w != orig:
            self.log.append((page + 1, orig, w, "word"))
        return w

    def manual_fix(self, text, page):
        for a, b in self.manual.items():
            if a in text:
                text = text.replace(a, b)
                self.log.append((page + 1, a, b, "manual"))
        return text

    def fix_text(self, text, page):
        return WORD_RE.sub(lambda m: self.fix_word(m.group(0), page), text)

    def join_split_letters(self, text, page):
        """'Ж А Н А' -> 'ЖАНА', 'киш и' -> 'киши', when the joined word is known."""
        toks = text.split(" ")
        out, i = [], 0
        while i < len(toks):
            best_j = None
            for j in range(min(len(toks), i + 12), i + 1, -1):
                piece = toks[i:j]
                if not all(WORD_RE.fullmatch(p) for p in piece[:-1]):
                    continue
                last = WORD_RE.match(piece[-1]) if piece[-1] else None
                if not last:
                    continue
                core = "".join(piece[:-1]) + last.group(0)
                if any(len(p) == 1 for p in piece) or any(self.freq(p) == 0 for p in piece[:-1]):
                    pass
                else:
                    continue
                pieces = piece[:-1] + [last.group(0)]
                spaced = len(pieces) >= 3 and all(len(p) == 1 for p in pieces)
                if (spaced and self.freq(core) >= 1) or (
                        self.freq(core) >= 3 and self.freq(core) > min(self.freq(p) for p in pieces)):
                    best_j = j
                    break
            if best_j:
                joined = "".join(toks[i:best_j])
                self.log.append((page + 1, " ".join(toks[i:best_j]), joined, "join"))
                out.append(joined)
                i = best_j
            else:
                out.append(toks[i])
                i += 1
        return " ".join(out)

    def dehyphen(self, left, right):
        """Decide whether 'left-' + 'right' at a line break is a soft hyphen or a real one."""
        lw = WORD_RE.findall(left)
        rw = WORD_RE.findall(right)
        if not lw or not rw:
            return left + right
        a, b = lw[-1], rw[0]
        joined, hyph = (a + b).lower(), (a + "-" + b).lower()
        fj, fh = self.freq(joined), self.hyph_freq.get(hyph, 0)
        if fh > fj:
            return left + "-" + right
        return left + right


# ---------------------------------------------------------------- layout analysis

def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def page_geometry(lines, pw):
    body = [l for l in lines if not l.arial and 10 <= l.size <= 12]
    xs = collections.Counter(round(l.x0) for l in body) or collections.Counter(round(l.x0) for l in lines)
    left = min((x for x, c in xs.most_common(3)), default=40)
    rights = sorted(l.x1 for l in body) or [pw - 40]
    right = rights[int(len(rights) * 0.9)] if len(rights) > 3 else max(rights)
    return left, right


BOOK_CENTER = None


def book_center(pages):
    xs, rs = collections.Counter(), []
    for lines, pw, ph in pages.values():
        for l in lines:
            if not l.arial and 10 <= l.size <= 12:
                xs[round(l.x0)] += 1
                rs.append(l.x1)
    right = collections.Counter(round(r / 2) * 2 for r in rs).most_common(1)[0][0]
    return (xs.most_common(1)[0][0] + right) / 2


def is_caps(t):
    letters = [c for c in t if c.isalpha()]
    return len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.8


def is_page_number(ln, ph):
    return ln.y0 > ph * 0.88 and re.fullmatch(r"\s*\d{1,3}\s*", ln.text)


def classify_blocks(lines, pw, ph):
    """Group lines by OCR block and label each block."""
    left, right = page_geometry(lines, pw)
    center = BOOK_CENTER or (left + right) / 2
    blocks = collections.OrderedDict()
    for ln in lines:
        if is_page_number(ln, ph):
            continue
        blocks.setdefault(ln.block, []).append(ln)
    out = []
    for bl in blocks.values():
        text = " ".join(l.text.strip() for l in bl)
        mids = [(l.x0 + l.x1) / 2 for l in bl]
        centered = all(abs(m - center) < 22 for m in mids) and all(l.x0 > left + 12 for l in bl)
        kind = "text"
        if re.fullmatch(r"[\s*•·]+", text) and "*" in text:
            kind = "sep"
        elif centered and len(bl) <= 3 and len(text) < 160 and not re.match(r"^\s*(\d+[.)]|[a-zа-яөүң])", text) and (
                is_caps(text) or (all(l.bold for l in bl) and len(text) < 70 and len(bl) == 1
                                  and not re.search(r"[-.,:;?!»…]\s*$", text))):
            kind = "heading"
        elif all(l.x0 > center + 10 for l in bl) and len(bl) <= 2 and len(text) < 60:
            kind = "attr"
        elif all(l.arial for l in bl):
            kind = "heading" if (is_caps(text) and len(text) < 120 and centered) else "arial"
        out.append((kind, bl))
    return out, left, right


# ---------------------------------------------------------------- building elements

ICON_RE = re.compile(r"^(\[\d\]|\|[^|\s]{1,3}\||[ШшЩщНН]|Ы|[ПП]|Ш)\s+(?=\S)")


def span_html(spans, fixer, page, strip_fmt=False):
    parts = []
    for t, bold, italic in spans:
        t = html.escape(t, quote=False)
        if not strip_fmt and t.strip():
            if italic:
                t = f"<i>{t}</i>"
            if bold:
                t = f"<b>{t}</b>"
        parts.append(t)
    s = "".join(parts)
    s = re.sub(r"</i>(\s*)<i>", r"\1", s)
    s = re.sub(r"</b>(\s*)<b>", r"\1", s)
    s = re.sub(r"<b><i>(\s*)</i></b>", r"\1", s)
    return s


def clean_line_text(raw_html, fixer, page):
    """Fix OCR mistakes in text outside of tags."""
    parts = re.split(r"(<[^>]+>)", raw_html)
    for i in range(0, len(parts), 2):
        t = parts[i]
        t = t.replace("­", "")
        t = re.sub(r"[ \t]+", " ", t)
        t = fixer.manual_fix(t, page)
        t = fixer.join_split_letters(t, page)
        t = fixer.fix_text(t, page)
        parts[i] = t
    return "".join(parts)


def typo(s):
    """Typographic normalisation: spaced hyphens used as dashes become en dashes."""
    s = re.sub(r"(^|\s)[-–—](?=\s)", lambda m: m.group(1) + "–", s)
    s = re.sub(r"(^|>)[-–—]\s", lambda m: m.group(1) + "– ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s


class Builder:
    def __init__(self, fixer, cfg):
        self.fixer = fixer
        self.cfg = cfg
        self.els = []          # list of dicts
        self.mode = "prose"    # carried across pages
        self.cur = None        # open element
        self.prev = None       # previous line (for paragraph logic)
        self.prev_right = None
        self.pending_pg = None

    # -- helpers
    def close(self):
        self.cur = None

    def start(self, typ, **kw):
        el = {"type": typ, "parts": [], **kw}
        self.els.append(el)
        self.cur = el
        return el

    def add_text(self, el, txt):
        """Append one line of text to an element, joining across line-break hyphens."""
        if self.pending_pg is not None:
            txt = f'<span class="pg" data-n="{self.pending_pg}">{self.pending_pg}</span>' + txt.lstrip()
            self.pending_pg = None
        parts = el["parts"]
        if not parts:
            parts.append(txt.strip())
            return
        last = parts[-1].rstrip()
        plain_last = re.sub(r"<[^>]+>", "", last)
        plain_next = re.sub(r"<[^>]+>", "", txt).strip()
        m = re.search(r"[-‐‑–—](\s*(?:</[ib]>)*)$", last)
        if m and plain_next[:1].isalpha() and plain_next[:1].islower() and re.search(f"[{LETTERS}][-‐‑–—]$", plain_last):
            stripped = last[:m.start()] + m.group(1)
            left_plain = re.sub(r"<[^>]+>", "", stripped)
            merged = self.fixer.dehyphen(left_plain, plain_next)
            keep = "-" if merged.startswith(left_plain + "-") else ""
            parts[-1] = stripped + keep
            parts.append(txt.strip())
        else:
            parts[-1] = last
            parts.append(" " + txt.strip())

    # -- main entry per page
    def page(self, pi, lines, figures, pw, ph):
        self.pending_pg = self.cfg["page_offset"] + pi + 1
        blocks, left, right = classify_blocks(lines, pw, ph)
        figs = sorted(figures, key=lambda f: f["bbox"][1])
        placed = set()

        def place_figs(y):
            for k, f in enumerate(figs):
                if k in placed or f["bbox"][1] > y:
                    continue
                placed.add(k)
                fig_el = {"type": "fig", "fig": f, "page": pi}
                # never split a paragraph: put the picture before the open paragraph
                if self.cur is not None and self.cur in self.els and self.cur["type"] in ("p",):
                    idx = self.els.index(self.cur)
                    self.els.insert(idx, fig_el)
                else:
                    self.els.append(fig_el)
                    self.close()

        for kind, bl in blocks:
            place_figs(bl[0].y0)
            if kind == "heading":
                txt = " ".join(clean_line_text(span_html(l.spans, self.fixer, pi, True), self.fixer, pi).strip() for l in bl)
                level = 3 if bl[0].arial else 2
                if (self.cur and self.cur["type"] == "h" and self.prev and self.cur["page"] == pi
                        and bl[0].y0 - self.prev.y1 < 10 and (txt.startswith("(") or is_caps(txt) == is_caps(self.cur["lines"][-1]))):
                    self.cur["lines"].append(txt)
                else:
                    self.els.append({"type": "h", "lines": [txt], "level": level, "page": pi, "pg": self.pending_pg})
                    self.pending_pg = None
                    self.cur = self.els[-1]
                self.prev = bl[-1]
                self.mode = "prose"
                continue
            if kind == "sep":
                self.els.append({"type": "sep"})
                self.close(); self.prev = bl[-1]
                continue
            if kind == "attr":
                txt = " ".join(clean_line_text(span_html(l.spans, self.fixer, pi), self.fixer, pi).strip() for l in bl)
                self.els.append({"type": "attr", "text": txt})
                self.close(); self.prev = bl[-1]
                continue
            if kind == "arial":
                self.arial_block(pi, bl)
                continue
            self.text_block(pi, bl, left, right)
        place_figs(10 ** 6)

    def arial_block(self, pi, bl):
        """Questions and tasks (numbered), or epigraphs/notes in the small sans font."""
        numbered = any(re.match(r"^\s*(\[\d\]\s*)?\d+[.)]", l.text) for l in bl)
        if numbered:
            if not (self.cur and self.cur["type"] == "tasks"):
                self.start("tasks", items=[])
            box = self.cur
            base = min(l.x0 for l in bl if re.match(r"^\s*\d+[.)]", l.text)) if any(re.match(r"^\s*\d+[.)]", l.text) for l in bl) else bl[0].x0
            for l in bl:
                raw = clean_line_text(span_html(l.spans, self.fixer, pi, True), self.fixer, pi)
                raw = ICON_RE.sub("", raw.strip())
                plain = re.sub(r"<[^>]+>", "", raw).strip()
                if not plain or (len(plain) <= 3 and not re.match(r"\d", plain)):
                    continue
                if re.match(r"^\d+[.)]", plain) or not box["items"]:
                    box["items"].append({"type": "p", "parts": []})
                self.add_text(box["items"][-1], raw)
            self.prev = bl[-1]
            return
        el = self.start("note")
        for l in bl:
            raw = clean_line_text(span_html(l.spans, self.fixer, pi, True), self.fixer, pi)
            raw = ICON_RE.sub("", raw.strip())
            if re.sub(r"<[^>]+>", "", raw).strip():
                self.add_text(el, raw)
        self.prev = bl[-1]
        self.close()

    def text_block(self, pi, bl, left, right):
        bl_left = min(l.x0 for l in bl)
        bl_right = max(l.x1 for l in bl)
        # verse or prose?
        body = bl[:-1] if len(bl) > 2 else bl
        if len(bl) >= 3:
            flush = sum(1 for l in body if l.x1 > bl_right - 5) / len(body)
            hy = sum(1 for l in bl if l.text.rstrip().endswith(tuple(HYPHENS)))
            mode = "prose" if (flush > 0.6 or hy >= 2) else "verse"
            if mode == "verse" and bl_right > right - 8 and flush > 0.4:
                mode = "prose"
        else:
            full = any(l.x1 > right - 12 for l in bl) or any(l.text.rstrip().endswith(tuple(HYPHENS)) for l in bl)
            mode = "prose" if full else self.mode
            if not full and self.mode == "prose":
                mode = "prose"
        # glossary entries
        gloss_re = re.compile(r"^\s*(?:[ШшЩщ]\s+)?[^\s–—-][^–—]{0,45}?\s[-–—]\s")
        local_right = [max(x.x1 for x in bl[max(0, i - 2):i + 3]) for i in range(len(bl))]
        for i, l in enumerate(bl):
            raw = clean_line_text(span_html(l.spans, self.fixer, pi), self.fixer, pi)
            plain = re.sub(r"<[^>]+>", "", raw)
            if not plain.strip():
                continue
            if re.fullmatch(r"[\s*]+", plain) and "*" in plain:
                self.els.append({"type": "sep"})
                self.close(); self.prev = l
                continue
            prev = self.prev if (self.prev is not None and self.prev.page == pi) else None
            gap = (l.y0 - prev.y1) if prev else 0
            # glossary: term – definition at a small indent, continuations indented further
            if mode == "prose" and gloss_re.match(plain) and left + 12 < l.x0 < left + 32 and (l.bold or (self.cur and self.cur["type"] == "gloss") or self._next_is_gloss(bl, i, left)):
                if not (self.cur and self.cur["type"] == "gloss"):
                    self.start("gloss", items=[])
                raw = re.sub(r"^\s*[ШшЩщ]\s+", "", raw)
                self.cur["items"].append({"type": "p", "parts": []})
                self.add_text(self.cur["items"][-1], raw)
                self.cur["left"] = l.x0
                self.prev = l
                continue
            if self.cur and self.cur["type"] == "gloss" and l.x0 > self.cur["left"] + 25:
                self.add_text(self.cur["items"][-1], raw)
                self.prev = l
                continue
            raw = ICON_RE.sub("", raw) if l.x0 < left + 8 and ICON_RE.match(plain) and len(plain) > 3 else raw
            if mode == "verse":
                if self.cur is None or self.cur["type"] != "verse":
                    self.start("verse", lines=[])
                v = self.cur
                if v["lines"] and l.x0 > bl_left + 45 and plain.strip()[:1].islower() and prev is not None:
                    # a long verse line that wrapped
                    v["lines"][-1]["parts"].append(" " + raw.strip())
                else:
                    if prev is not None and v["lines"] and gap > 7:
                        v["lines"].append({"gap": True})
                    ln = {"parts": []}
                    v["lines"].append(ln)
                    self.add_text(ln, raw.strip())
                self.prev = l
                self.mode = "verse"
                continue
            # prose
            indent = l.x0 > left + 10 and l.x0 > bl_left + 8 or (l.x0 > left + 10 and i == 0)
            prev_short = self.prev is not None and self.prev_right is not None and self.prev.x1 < self.prev_right - 25
            prev_end = ""
            if self.cur and self.cur.get("parts"):
                prev_end = re.sub(r"<[^>]+>", "", self.cur["parts"][-1]).rstrip()[-1:]
            new_para = (self.cur is None or self.cur["type"] != "p" or indent or
                        (prev_short and prev_end in ".!?…:»\"")) and not (
                self.cur is not None and self.cur["type"] == "p" and prev_end in tuple(HYPHENS) and not indent)
            if self.cur is not None and self.cur["type"] == "p" and prev_end in tuple(HYPHENS) and plain.strip()[:1].islower():
                new_para = False
            if new_para:
                self.start("p")
            self.add_text(self.cur, raw)
            self.prev = l
            self.prev_right = local_right[i]
            self.mode = "prose"

    def _next_is_gloss(self, bl, i, left):
        for l in bl[i + 1:i + 3]:
            t = l.text
            if re.match(r"^\s*\S[^–—]{0,45}?\s[-–—]\s", t) and left + 12 < l.x0 < left + 32:
                return True
        return False


# ---------------------------------------------------------------- rendering

def join_parts(parts):
    s = "".join(parts).strip()
    for t in ("i", "b"):
        s = re.sub(f"</{t}>(\\s*)<{t}>", r"\1", s)
    return typo(s)


def render(els, imgdir, doc, img_ext="webp"):
    """Turn builder elements into reader blocks (the format app.js reads)."""
    blocks = []
    fig_n = collections.Counter()
    for el in els:
        t = el["type"]
        if t == "p":
            s = join_parts(el["parts"])
            if s:
                blocks.append({"t": "p", "h": s})
        elif t == "h":
            txt = typo(re.sub(r"\s+", " ", " ".join(el["lines"])))
            pg = f'<span class="pg" data-n="{el["pg"]}">{el["pg"]}</span>' if el.get("pg") else ""
            blocks.append({"t": "h%d" % el["level"], "h": pg + txt})
        elif t == "verse":
            lines = []
            for ln in el["lines"]:
                if ln.get("gap"):
                    if lines and lines[-1] != "":
                        lines.append("")
                else:
                    lines.append(join_parts(ln["parts"]))
            while lines and lines[-1] == "":
                lines.pop()
            if lines:
                blocks.append({"t": "v", "l": lines})
        elif t in ("tasks", "gloss"):
            items = "".join(f'<p class="ni">{join_parts(i["parts"])}</p>' for i in el["items"] if i["parts"])
            if items:
                blocks.append({"t": "raw", "h": f'<div class="{t}">{items}</div>'})
        elif t == "note":
            s = join_parts(el["parts"])
            if s:
                blocks.append({"t": "raw", "h": f'<p class="note">{s}</p>'})
        elif t == "attr":
            blocks.append({"t": "raw", "h": f'<p class="attr">{typo(el["text"])}</p>'})
        elif t == "sep":
            blocks.append({"t": "raw", "h": '<p class="sep">* * *</p>'})
        elif t == "fig":
            pi = el["page"]
            fig_n[pi] += 1
            name = f"p{pi + 1:03d}-{fig_n[pi]}.{img_ext}"
            w, h = save_figure(doc, pi, el["fig"], os.path.join(imgdir, name))
            blocks.append({"t": "img", "src": "img/" + name, "w": w, "ht": h})
    # page markers that ended up in a heading followed by nothing, or pages whose marker was lost, are fine
    return blocks


def save_figure(doc, pi, f, path, max_w=560):
    page = doc[pi]
    clip = pymupdf.Rect(f["bbox"])
    pix = page.get_pixmap(clip=clip, dpi=200)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    if path.endswith(".webp"):
        im.save(path, "WEBP", quality=62, method=6)
    else:
        im.save(path, "JPEG", quality=72, optimize=True, progressive=True)
    return im.width, im.height


# ---------------------------------------------------------------- chapters

def norm_title(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = s.lower().replace("ё", "е")
    return re.sub(f"[^{LETTERS}]", "", s)


def main():
    cfg = load_config(sys.argv[1])
    doc = pymupdf.open(cfg["pdf"])
    pages, figures = extract(doc, cfg)
    fixer = Fixer(pages, cfg)
    global BOOK_CENTER
    BOOK_CENTER = cfg.get("text_center") or book_center(pages)
    print("text centre", round(BOOK_CENTER, 1))
    # hyphenated spellings seen inside lines, for line-break hyphen decisions
    hyph = collections.Counter()
    for lines, _, _ in pages.values():
        for ln in lines:
            for m in re.finditer(f"([{LETTERS}]+)-([{LETTERS}]+)", ln.text):
                hyph[(m.group(1) + "-" + m.group(2)).lower()] += 1
    fixer.hyph_freq = hyph

    out = cfg["out"]
    imgdir = os.path.join(out, "img")
    os.makedirs(imgdir, exist_ok=True)
    for d in (imgdir,):
        for fn in os.listdir(d):
            os.remove(os.path.join(d, fn))

    chapters = cfg["chapters"]
    chapter_list = []
    total_chars = 0
    for ci, ch in enumerate(chapters):
        b = Builder(fixer, cfg)
        for pi in range(ch["from"], ch["to"] + 1):
            if pi in pages:
                lines, pw, ph = pages[pi]
                figs = figures.get(pi, [])
                if ch.get("start_heading") and pi == ch["from"]:
                    lines = trim_before(lines, ch["start_heading"], True)
                    if lines:
                        figs = [f for f in figs if f["bbox"][1] >= lines[0].y0 - 5]
                if ch.get("end_heading") and pi == ch["to"]:
                    kept = trim_before(lines, ch["end_heading"], False)
                    if len(kept) < len(lines):
                        cut = lines[len(kept)].y0
                        figs = [f for f in figs if f["bbox"][3] <= cut + 5]
                    lines = kept
                b.page(pi, lines, figs, pw, ph)
                b.close()
                b.prev = None
        blocks = render(b.els, imgdir, doc)
        subs = []
        for sub in ch.get("sub", []):
            key = norm_title(sub)
            found = None
            for bi, bl in enumerate(blocks):
                if bl["t"] in ("h2", "h3") and key and key[:18] in norm_title(bl["h"]):
                    found = bi
                    break
            if found is None:  # title not set as a heading in the scan: first block starting with it
                for bi, bl in enumerate(blocks):
                    txt = bl.get("h") or " ".join(bl.get("l", [])[:2])
                    if key and norm_title(txt).startswith(key[:12]):
                        found = bi
                        break
            subs.append({"title": sub, "b": found})
        total_chars += sum(len(re.sub(r"<[^>]+>", "", bl.get("h", "") + " ".join(bl.get("l", [])))) for bl in blocks)
        chapter_list.append({"title": ch["title"], "section": ch.get("section"),
                             "pages": [ch["from"] + 1 + cfg["page_offset"], ch["to"] + 1 + cfg["page_offset"]],
                             "sub": subs, "blocks": blocks})

    images = sorted(os.listdir(imgdir))
    book = {k: cfg[k] for k in ("id", "title", "subtitle", "author", "grade", "lang", "langName", "subject", "year",
                                "publisher", "school", "source", "notes") if k in cfg}
    book.update({"format": 2, "images": ["img/" + i for i in images], "chapters": chapter_list})
    with open(os.path.join(out, "book.json"), "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out, "corrections.tsv"), "w", encoding="utf-8") as f:
        f.write("page\tocr_text\tcorrected\tkind\n")
        seen = set()
        for row in fixer.log:
            if row not in seen:
                seen.add(row)
                f.write("\t".join(map(str, row)) + "\n")
    print(f"chapters={len(chapters)} images={len(images)} chars={total_chars} corrections={len(set(fixer.log))}")


def trim_before(lines, heading, keep_after):
    """Keep lines from (keep_after=True) or before (False) the first line containing `heading`."""
    key = norm_title(heading)
    for i, l in enumerate(lines):
        if key and key[:14] in norm_title(l.text):
            return lines[i:] if keep_after else lines[:i]
    return lines if keep_after else lines


if __name__ == "__main__":
    main()
