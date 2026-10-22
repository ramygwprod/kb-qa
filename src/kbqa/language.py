"""Language copies — when English exists, the other languages are not collected.

The operator's ruling (2026-10-22): when a page exists in English, its copies in
other languages add nothing but repeated rows, so they are left out of the
denominator, each listed with the English page that covers it. A page with no
English counterpart stays in, and is collected only on the operator's word.

A copy is recognised by code, never guessed:
1. **hreflang** — the sitemap's own `<xhtml:link rel="alternate" hreflang=…>`
   says which URL is the English version of which page. The vendor's word.
2. **a language path** — `/<lang>/rest` (or `/<lang>-<region>/rest`) where
   `<lang>` is an ISO 639-1 code other than `en`, and the same host also lists
   `/rest`, `/en/rest` or `/en-<region>/rest`. Taken only when one language
   segment covers at least LANGUAGE_MIN such pairs, so a lone path that merely
   looks like a language code (`/it/…`, `/id/…`) is never dropped.
Nothing else: no guessing from page text, query strings or headers.
"""

import re
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

LANGUAGE_MIN = 3

# ISO 639-1, the two-letter language codes (a standard list, not a vocabulary of ours).
ISO_639_1 = frozenset("""
aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de
dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie
ig ii ik io is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg
mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro
ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw
ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu
""".split())

LOCALE_RE = re.compile(r"^(?P<lang>[a-z]{2})(?:[-_](?P<rest>[a-z0-9]{2,4}))?$", re.IGNORECASE)


def _lang(segment: str) -> Optional[str]:
    m = LOCALE_RE.match(segment)
    if m and m.group("lang").lower() in ISO_639_1:
        return m.group("lang").lower()
    return None


def _split(url: str) -> Tuple[str, Optional[str], str]:
    """(host, the language of the first path segment or None, the rest of the path)."""
    p = urlsplit(url)
    segs = p.path.split("/")
    first = segs[1] if len(segs) > 1 else ""
    lang = _lang(first)
    rest = "/" + "/".join(segs[2:]) if lang else p.path
    return (p.hostname or "").lower(), lang, rest


def copies(urls: Iterable[str], hreflang: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """{copy URL: the English URL that covers it} for the given index URLs."""
    urls = list(dict.fromkeys(urls))
    present = set(urls)
    out: Dict[str, str] = {}
    for copy, english in (hreflang or {}).items():
        if copy in present and english in present and copy != english:
            out[copy] = english
    english_at: Dict[Tuple[str, str], str] = {}
    for u in urls:
        host, lang, rest = _split(u)
        if lang in (None, "en"):
            english_at.setdefault((host, rest.rstrip("/") or "/"), u)
    by_segment: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
    for u in urls:
        if u in out:
            continue
        host, lang, rest = _split(u)
        if lang is None or lang == "en":
            continue
        english = english_at.get((host, rest.rstrip("/") or "/"))
        if english and english != u:
            seg = urlsplit(u).path.split("/")[1].lower()
            by_segment.setdefault((host, seg), []).append((u, english))
    for pairs in by_segment.values():
        if len(pairs) >= LANGUAGE_MIN:
            out.update(dict(pairs))
    return out


def english_alternates(url_elements) -> Dict[str, str]:
    """{page URL: its English alternate} from sitemap `<url>` elements carrying
    `xhtml:link rel="alternate" hreflang=…` — the vendor's own statement."""
    out: Dict[str, str] = {}
    for el in url_elements:
        loc = next((c.text.strip() for c in el if c.tag.split("}")[-1] == "loc" and c.text), None)
        if not loc:
            continue
        english, own = None, None
        for c in el:
            if c.tag.split("}")[-1] == "link" and c.get("rel") == "alternate":
                lang = (c.get("hreflang") or "").lower()
                href = (c.get("href") or "").strip()
                if href == loc:
                    own = lang
                elif english is None and (lang == "en" or lang.startswith("en-")):
                    english = href
        # The page's own language: its self link, else its language path. A page
        # that is English, or whose language cannot be told, is never a copy.
        own = own or (_split(loc)[1] or "")
        if english and own and own != "x-default" and not (own == "en" or own.startswith("en-")):
            out[loc] = english
    return out
