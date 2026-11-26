"""
scrapers/common.py — small helpers shared by the ATS scrapers.

html_to_text()        HTML -> plain text. Also handles Greenhouse, which sends
                      descriptions HTML-entity-encoded (&lt;p&gt; instead of <p>):
                      without html.unescape() the tags end up in the DB as text.
is_israel_location()  keyword check for free-text locations (Greenhouse, Lever).
"""

import html
import re

from bs4 import BeautifulSoup

ISRAEL_KEYWORDS = (
    "israel",
    "tel aviv", "tel-aviv", "tlv",
    "herzliya", "herzelia", "herzlia", "herzeliya",
    "haifa",
    "petah tikva", "petach tikva", "petah-tikva", "petach-tikva",
    "ra'anana", "raanana",
    "netanya",
    "jerusalem",
    "ramat gan",
    "kfar saba",
    "rishon",
    "rehovot",
    "beer sheva", "be'er sheva",
    "hod hasharon",
    "givatayim",
    "holon",
    "bnei brak",
    # added: tech hubs the old list missed
    "yokneam", "yokne'am",
    "caesarea",
    "airport city",
    "modiin", "modi'in",
    "ness ziona", "nes ziona",
    "rosh haayin", "rosh ha'ayin",
    "or yehuda",
    "ramat hasharon",
    "yavne",
    "ashdod",
    "kiryat gat",
    "beit shemesh",
    "nazareth",
    "migdal haemek",
)

_BLANK_LINES = re.compile(r"\n\s*\n+")


def is_israel_location(text: str) -> bool:
    text = (text or "").lower()
    return any(keyword in text for keyword in ISRAEL_KEYWORDS)


def html_to_text(fragment: str) -> str:
    """
    HTML (or entity-encoded HTML) -> plain text, one block per line.

    Newlines between <p>/<li> blocks are kept on purpose: the matcher reads
    requirement bullets line by line.
    """
    if not fragment:
        return ""
    unescaped = html.unescape(fragment)
    text = BeautifulSoup(unescaped, "lxml").get_text(separator="\n", strip=True)
    return _BLANK_LINES.sub("\n", text).strip()
