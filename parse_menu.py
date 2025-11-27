#!/usr/bin/env python3
"""Parse a mensa/menu HTML page (even if it's one long line) and extract meals.

Usage examples:
  python3 parse_menu.py --file sample_menu.html
  python3 parse_menu.py --url https://example.my-mensa.de/essen.php

This script extracts:
 - meal name
 - category (if found)
 - zusatzstoffe (numbers in parentheses)
 - tags (from `data-type` attributes on images)
 - price

The parser is heuristic to handle compressed single-line HTML.

"""
from __future__ import annotations

import argparse
import datetime
import json
import re
from typing import List, Dict, Optional

import requests
import os
import tempfile
from bs4 import BeautifulSoup, Tag
import html as _html


PRICE_RE = re.compile(r"(\d+[\.,]\d{2})\s*€")
# capture alphanumeric codes or numeric codes, comma/space separated, e.g. (1,19) or (WEI)
ZUSATZ_RE = re.compile(r"\(?\s*([A-Za-z0-9]{1,5}(?:[,\s]*[A-Za-z0-9]{1,5})*)\s*\)?")


# Characters to clean from parsed text (soft hyphen U+00AD and several zero-widths)
_INVISIBLE_REPLACEMENTS = {
    "\u00ad": "",  # soft hyphen
    "\u200b": "",  # zero width space
    "\ufeff": "",  # byte order mark
    "\u200e": "",  # left-to-right mark
    "\u200f": "",  # right-to-left mark
}


def clean_text(s: Optional[str]) -> Optional[str]:
    """Normalize and remove invisible/control characters from text."""
    if s is None:
        return None
    if not isinstance(s, str):
        s = str(s)
    # replace non-breaking space with regular space
    s = s.replace("\u00a0", " ")
    # remove common invisible characters
    for k, v in _INVISIBLE_REPLACEMENTS.items():
        s = s.replace(k, v)
    # collapse repeated whitespace
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_global_zusatzstoffe(html: str) -> Dict[str, str]:
    """Parse JavaScript block which defines `zusatzstoffe["KEY"] = JSON.parse('...')`.
    Returns mapping KEY -> human-readable name (if available) or empty string.
    """
    mapping: Dict[str, str] = {}
    # simplified: find the JSON payloads and load them; site format is stable
    pattern = (
        r"zusatzstoffe\[\"([^\"]+)\"\]\s*=\s*JSON\.parse\((?P<j>\"[^\"]*\"|'[^']*')\)"
    )
    for m in re.finditer(pattern, html):
        key = m.group(1)
        js_str = m.group("j")
        if js_str and js_str[0] in ('"', "'"):
            js_str = js_str[1:-1]
        try:
            obj = json.loads(js_str)
        except Exception:
            try:
                obj = json.loads(js_str.replace("\\/", "/"))
            except Exception:
                obj = {}
        mapping[key] = obj.get("id") or obj.get("name") or ""
    return mapping


def load_html_from_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_html_from_url(url: str) -> str:
    resp = requests.get(
        url,
        timeout=10,
        headers={
            "User-Agent": "MensaFetcher/0.1 (+https://github.com/LeanderJDev) py-requests/"
            + requests.__version__
        },
    )
    resp.raise_for_status()
    return resp.text


def find_dish_list(soup: BeautifulSoup) -> List[Tag]:
    """Find candidate <li> elements that represent dishes.

    each dish is a <li> with both `data-gid` and `ref`
    """
    return list(soup.select("li[data-gid][ref]"))


def extract_from_node(node: Tag, global_zs: Dict[str, str]) -> Dict[str, Optional[str]]:
    text = clean_text(node.get_text(" ", strip=True))
    # price
    price_m = PRICE_RE.search(text)
    price = price_m.group(1).replace(",", ".") if price_m else None
    # tags from img[data-type]
    tags = [
        clean_text(img.get("data-type"))
        for img in node.find_all("img")
        if img.get("data-type")
    ]
    # zusatzstoffe: find patterns like (1,2) or (WEI)
    # zusatzstoffe: prefer parsing the `ref` attribute if present (it contains all codes),
    zusatz = []
    ref_attr = node.get("ref") or node.get("data-ref")
    if ref_attr:
        # unescape HTML entities and extract quoted tokens
        ref_unesc = clean_text(_html.unescape(ref_attr))
        parts = re.findall(r'"([^\"]+)"', ref_unesc)
        if not parts:
            # fallback: split by non-word characters
            parts = re.findall(r"[A-Za-z0-9]+", ref_unesc)
        zusatz = parts
    # normalize and keep only codes that exist in global mapping when available
    zusatz = [clean_text(z) for z in zusatz if z and z.strip()]
    if global_zs:
        zusatz = [z for z in zusatz if z in global_zs]
    # remove duplicates while preserving order
    zusatz = list(dict.fromkeys(zusatz))
    # name: prefer headings inside node
    name = None
    t = node.find("h3")
    if t and t.get_text(strip=True):
        name = clean_text(t.get_text(strip=True))
    # category: for <li> dish entries the third class token is the category name
    category = None
    cls = node.get("class") or []
    if isinstance(cls, list) and len(cls) >= 3:
        # third token (index 2)
        category = clean_text(cls[2])

    # description: collect non-heading, non-price text parts excluding zusatz tokens
    desc_parts = []
    for el in node.find_all(string=True):
        t = clean_text(el)
        if not t:
            continue
        if PRICE_RE.search(t):
            continue
        # skip pure zusatz tokens
        if any(t == z or t.startswith(f"({z}") for z in zusatz):
            continue
        if name and t == name:
            continue
        desc_parts.append(t)
    description = " ".join(dict.fromkeys(desc_parts)).strip() or None

    return {
        "name": name,
        "description": description,
        "category": category,
        "zusatzstoffe": zusatz,
        "tags": tags,
        "price_eur": float(price) if price else None,
    }


def parse_html(html: str, date: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    global_zs = parse_global_zusatzstoffe(html)

    # find all divs with ids like '..._tag_<number>'
    tag_divs = []
    for div in soup.find_all("div", id=True):
        m = re.search(r"_tag_(\d+)", div["id"])
        if m:
            try:
                tag_divs.append((int(m.group(1)), div))
            except Exception:
                continue
    nodes = []
    if tag_divs:
        if date:
            # try to find the div for the specified date
            date_found = False
            for tag_num, div in tag_divs:
                if str(tag_num) == date:
                    nodes = find_dish_list(div)
                    date_found = True
                    break
            if not date_found:
                print(
                    f"Warning: specified date {date} not found, using first available tag."
                )
        tag_divs.sort(key=lambda x: x[0])
        chosen = tag_divs[0][1]
        nodes = find_dish_list(chosen)
    else:
        nodes = find_dish_list(soup)

    results = []
    for n in nodes:
        results.append(extract_from_node(n, global_zs))
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Read HTML from file")
    parser.add_argument("--url", help="Fetch HTML from URL")
    parser.add_argument("--date", help="Fetch HTML from URL for specific date")
    parser.add_argument(
        "--output", "-o", default="menu_parsed.json", help="Output JSON file"
    )
    args = parser.parse_args()
    if not args.file and not args.url:
        parser.error("provide --file or --url")

    # Normalize date token for parsing and for filename when requested.
    date = args.date
    if date == "today":
        today = datetime.date.today()
        day_of_year = today.timetuple().tm_yday
        date = str(today.year * 1000 + day_of_year)

    # If the user didn't override the output filename and provided a date,
    # name the file using that date (sanitized).
    output_filename = args.output or "menu_parsed.json"
    if args.date and (output_filename == "menu_parsed.json"):
        safe_date = re.sub(r"[^A-Za-z0-9_.-]", "_", date)
        output_filename = f"menu_{safe_date}.json"

    if args.file:
        html = load_html_from_file(args.file)
    else:
        html = load_html_from_url(args.url)

    parsed = parse_html(html, date)

    # --- Atomarer Schreibvorgang ---
    # Um sicherzustellen, dass Cron‑Jobs oder unerwartete Abbrüche
    # keine halbgeschriebenen Ausgabedateien hinterlassen, schreiben
    # wir zuerst in eine temporäre Datei im selben Verzeichnis und
    # ersetzen anschließend die Zieldatei mit os.replace().
    # os.replace() ist atomar auf den meisten POSIX‑Dateisystemen.
    out_dir = os.path.dirname(output_filename) or "."
    # NamedTemporaryFile mit delete=False, damit wir die Datei nach dem
    # Schreiben sicher umbenennen können. Wir schließen die Datei explizit
    # bevor wir os.replace() aufrufen.
    fd, tmp_path = tempfile.mkstemp(prefix="tmp_menu_", dir=out_dir, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tf:
            json.dump(parsed, tf, ensure_ascii=False, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
        # atomar ersetzen
        os.replace(tmp_path, output_filename)
    except Exception:
        # Aufräumen bei Fehlern
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise

    print(f"Wrote {len(parsed)} items to {output_filename}")


if __name__ == "__main__":
    main()
