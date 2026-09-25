#!/usr/bin/env python3
"""Strategy 3: assemble a book from hand-made (model-made) page transcriptions.

Usage: python3 assemble_s3.py <config.json> <pages_dir>

For each page the transcriber reads the page picture and the exact text lines (from
convert_math_s1.py with DUMP_DIR set) and writes pNNN.html: clean, well-formed XHTML using the
reader's vocabulary. Pictures are requested with <figure data-crop="R3"/> (a region id from pNNN.json)
or <figure data-crop="x0,y0,x1,y1"/> (PDF points); this script redraws them as SVG (or WebP for photos).
"""
import json, os, re, sys
import xml.etree.ElementTree as ET

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_layout import load_config, esc  # noqa: E402
from convert_math import open_doc  # noqa: E402
from convert_math_s1 import Saver, trim_spans, photo_areas  # noqa: E402


def html_of(el):
    s = ET.tostring(el, encoding="unicode", method="html")
    return re.sub(r"\s+\n\s*", " ", s).strip()


def inner_html(el):
    s = html_of(el)
    return re.sub(r"^<[^>]+>|</[a-z0-9]+>$", "", s)


BD = re.compile(r'(<b class="bd">)')


def keep_items(h):
    """Wrap each а/б/в exercise item so a line break falls between items, not inside one."""
    if h.count('class="bd"') < 2 or not h.startswith("<p"):
        return h
    m = re.match(r"^(<p[^>]*>(?:<span class=\"pg\"[^>]*>[^<]*</span>)?)(.*)(</p>)$", h, re.S)
    if not m:
        return h
    head, body, tail = m.groups()
    parts = BD.split(body)
    out = parts[0]
    for i in range(1, len(parts), 2):
        item = (parts[i] + parts[i + 1]).replace("\u2003", " ").strip()
        out += '<span class="it">' + item + "</span> "
    return head + out.rstrip() + tail


def main():
    cfg = load_config(sys.argv[1])
    pages_dir = sys.argv[2]
    meta_dir = sys.argv[3] if len(sys.argv) > 3 else pages_dir
    doc = open_doc(cfg["pdf"])
    saver = Saver(cfg, doc)
    off = cfg["page_offset"]
    chapters = []
    problems = []
    for ch in cfg["chapters"]:
        c = {"title": ch["title"], "section": ch.get("section"), "pages": [ch["from"] + 1 + off, ch["to"] + 1 + off],
             "sub": [], "blocks": [{"t": "h2", "h": esc(ch["title"])}]}
        for pi in range(ch["from"], ch["to"] + 1):
            printed = pi + 1 + off
            path = os.path.join(pages_dir, f"p{printed:03d}.html")
            if not os.path.exists(path):
                continue
            meta_p = os.path.join(meta_dir, f"p{printed:03d}.json")
            regs = {}
            if os.path.exists(meta_p):
                regs = {g["id"]: g for g in json.load(open(meta_p, encoding="utf-8"))["regions"]}
            page = doc[pi]
            drawings = page.get_drawings()
            rasters = [pymupdf.Rect(im["bbox"]) & page.rect for im in page.get_image_info()
                       if 3000 < (pymupdf.Rect(im["bbox"]) & page.rect).get_area() < 0.4 * page.rect.get_area()]
            rasters += photo_areas(page, drawings)
            saver.set_page(pi, page, drawings, trim_spans(page), rasters)
            saver.prepare_render([])
            src = open(path, encoding="utf-8").read()
            src = re.sub(r"&nbsp;", " ", src)
            src = re.sub(r"&(?!(amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);)", "&amp;", src)
            try:
                root = ET.fromstring("<root>" + src + "</root>")
            except ET.ParseError as e:
                problems.append(f"p{printed}: {e}")
                continue

            def crop_rect(spec):
                spec = spec.strip()
                if spec in regs:
                    return pymupdf.Rect(regs[spec]["bbox"]), regs[spec].get("photo", False)
                v = [float(x) for x in re.split(r"[,\s]+", spec) if x]
                return pymupdf.Rect(v), False

            def picture(fig):
                r, photo = crop_rect(fig.get("data-crop"))
                r &= page.rect
                if fig.get("data-kind") == "photo":
                    saver.rasters = saver.rasters + [pymupdf.Rect(r)]
                b = saver.picture(r)
                saver.rasters = rasters
                return b

            first = True
            norm = lambda s: re.sub(r"\W+", " ", s).strip().lower()
            for el in list(root):
                if el.tag in ("h3", "h4") and norm("".join(el.itertext())) in (norm(ch["title"]), norm(ch["title"].split(" ", 1)[-1])):
                    continue
                pg = f'<span class="pg" data-n="{printed}">{printed}</span>' if first else ""
                if el.tag == "figure" and el.get("data-crop"):
                    b = picture(el)
                    cap = el.find("figcaption")
                    b["cap"] = pg + (inner_html(cap) if cap is not None else "")
                    if not b["cap"]:
                        del b["cap"]
                    c["blocks"].append(b)
                    first = False
                    continue
                for fig in el.iter("figure"):
                    if fig.get("data-crop"):
                        b = picture(fig)
                        spec = fig.get("data-crop")
                        fig.attrib.clear()
                        for k in list(fig):
                            fig.remove(k)
                        img = ET.SubElement(fig, "img", {"data-w": str(b["w"]), "data-h": str(b["ht"]),
                                                         "style": f"width:{b['dw']}em", "src": b["src"], "alt": ""})
                h = keep_items(html_of(el))
                if pg:
                    h = re.sub(r"^(<\w+[^>]*>)", lambda m: m.group(1) + pg, h, count=1)
                if el.tag == "h3":
                    c["blocks"].append({"t": "h3", "h": inner_html(el) if not pg else pg + inner_html(el)})
                    c["sub"].append({"title": re.sub(r"<[^>]+>", "", inner_html(el)).strip(), "b": len(c["blocks"]) - 1})
                elif el.tag == "p" and not el.attrib:
                    c["blocks"].append({"t": "p", "h": re.sub(r"^<p>|</p>$", "", h)})
                else:
                    c["blocks"].append({"t": "raw", "h": h})
                first = False
        chapters.append(c)
    book = {k: cfg[k] for k in ("id", "title", "subtitle", "author", "grade", "lang", "langName", "subject", "year",
                                "publisher", "school", "source", "notes") if k in cfg}
    book.update(format=2, images=saver.images, chapters=[c for c in chapters if len(c["blocks"]) > 1])
    with open(os.path.join(saver.out, "book.json"), "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, separators=(",", ":"))
    size = sum(os.path.getsize(os.path.join(saver.imgdir, x)) for x in os.listdir(saver.imgdir))
    print(dict(saver.stats), f"images {size / 1048576:.2f} MB", "problems:", problems)


if __name__ == "__main__":
    main()
