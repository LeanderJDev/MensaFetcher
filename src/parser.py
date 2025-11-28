#!/usr/bin/env python3
"""Parse a mensa/menu HTML page (even if it's one long line) and extract meals.

This parser extracts:
 - meal name
 - category (if found)
 - zusatzstoffe (numbers in parentheses)
 - tags (from `data-type` attributes on images)
 - price

The parser is heuristic to handle compressed single-line HTML.

"""


import datetime
import json
import re
from typing import Any, Optional, List, Dict

import requests
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
    """Normalize and remove invisible/control characters from text.

    Args:
        s (str): Input string

    Returns:
        Optional[str]: Cleaned string or None
    """
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
    """Parse JavaScript blocks that define extra-ingredient mappings.

    The target pages embed mappings like ``zusatzstoffe["KEY"] = JSON.parse('...')``
    in inline JavaScript. This function extracts those payloads and returns a
    dictionary mapping the KEY to a human-readable name (if available) or an
    empty string.

    Args:
        html: The full HTML document as a string.

    Returns:
        A mapping from the zusatzstoff key (str) to its human readable name
        (str) or an empty string when no name could be parsed.
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
    """Load HTML content from a local file.

    Args:
        path: Path to the HTML file.

    Returns:
        The file contents decoded as UTF-8.
    """
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_html_from_url(url: str) -> str:
    """Fetch HTML from a remote URL using ``requests``.

    A conservative timeout is used and a descriptive User-Agent header is set
    to identify this tool. HTTP errors raise an exception.

    Args:
        url: The URL to fetch.

    Returns:
        The response body as decoded text.

    Raises:
        requests.HTTPError: If the response contains an HTTP error status.
    """
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
    """Locate candidate ``<li>`` elements that represent dishes.

    The site represents each dish as an ``<li>`` element that contains both a
    ``data-gid`` and a ``ref`` attribute. This helper returns the matching
    Tag objects for further extraction.

    Args:
        soup: A BeautifulSoup-parsed document.

    Returns:
        A list of Tag objects for candidate dish list items.
    """
    return list(soup.select("li[data-gid][ref]"))


def extract_from_node(node: Tag, global_zs: Dict[str, str]) -> Dict[str, Optional[str]]:
    """Extract structured dish information from a single ``<li>`` node.

    The returned dictionary contains the following keys:
    ``name`` (str|None), ``description`` (str|None), ``category`` (str|None),
    ``zusatzstoffe`` (list[str]), ``tags`` (list[str]) and ``price_eur``
    (float|None).

    Args:
        node: The BeautifulSoup Tag corresponding to a single dish ``<li>``.
        global_zs: Mapping of valid zusatzstoff codes (from
            :func:`parse_global_zusatzstoffe`). If provided, only codes present
            in this mapping are returned.

    Returns:
        A dict with parsed fields for the dish.
    """
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


def parse_html(html: str, date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Parse a mensa HTML page and extract the list of dishes for a date.

    The function locates the HTML block(s) that correspond to menu days
    (identified by IDs containing ``_tag_<number>``). If a ``date`` token is
    provided it will try to select the matching block; otherwise the first
    (lowest) tag is used.

    Args:
        html: Full HTML document as text.
        date: Optional date token (string like ``YYYYDDD``). If omitted, the
            first available tag block is parsed.

    Returns:
        A list of dictionaries representing parsed dishes. Each dict uses the
        same structure as returned by :func:`extract_from_node`.
    """
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


def parse_url_to_items(
    url: str, date: Optional[datetime.date] = None
) -> List[Dict[str, Any]]:
    """Fetch a URL and parse dishes for the given date.

    Args:
        url: URL to fetch.
        date: Optional `datetime.date`. If provided it will be converted to the
            internal date token format (``YYYYDDD``) before parsing.

    Returns:
        A list of parsed dish dictionaries (same format as
        :func:`parse_html`).
    """
    if date is None:
        date_str = None
    else:
        day_of_year = date.timetuple().tm_yday
        date_str = str(date.year * 1000 + day_of_year)
    html = load_html_from_url(url)
    return parse_html(html, date_str)
