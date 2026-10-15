"""TextPrep + BabbleGuard: faithful port of SayTrayCore (macOS).

Turns arbitrary selected text into short, clean, speakable chunks for Piper.
Pure and deterministic; covered by tests/test_textprep.py.
"""
import unicodedata
import regex as re
from urllib.parse import urlparse

MAX_CHUNK = 200
MIN_WORDS = 3


def word_count(s: str) -> int:
    return sum(1 for w in s.split() if any(c.isalnum() for c in w))


def _dots(s):
    return s.replace(".", " dot ")


_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"


def _url(m):
    u = m.group(0)
    tail = ""
    while u and u[-1] in ".,;:!?":
        tail = u[-1] + tail
        u = u[:-1]
    try:
        host = urlparse("https://" + u if u.lower().startswith("www.") else u).hostname or "a website"
    except Exception:
        host = "a website"
    if host.startswith("www."):
        host = host[4:]
    return " " + _dots(host) + tail + " "


def _strip_scalar(ch: str) -> str:
    cp = ord(ch)
    if cp == 0x0A:
        return ch
    if cp in (0x200B, 0x2060):
        return " "
    cat = unicodedata.category(ch)
    if cat in ("Cc", "Cf"):
        return ""
    if 0xFE00 <= cp <= 0xFE0F or 0x1F3FB <= cp <= 0x1F3FF:
        return ""
    # emoji / pictographs / other + math symbols
    if cp >= 0x1F000 or (0x2190 <= cp <= 0x2BFF) or cat in ("So", "Sm"):
        return " "
    return ch


def normalize_to_lines(text: str):
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    # Markdown structure
    t = re.sub(r"```[\s\S]*?(```|$)", "\nCode block omitted.\n", t)
    t = re.sub(r"`([^`\n]+)`", r"\1", t)
    t = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1", t)
    t = re.sub(r"(\*\*|__|~~)(.+?)\1", r"\2", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\1", t)
    t = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+", "", t)
    t = re.sub(r"(?m)^[ \t]*>+[ \t]?", "", t)
    t = re.sub(r"(?m)^[ \t]*([-*_][ \t]*){3,}$", "", t)
    t = re.sub(r"(?m)^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$", "", t)
    t = re.sub(r"(?m)^[ \t]*\|(.*)\|[ \t]*$", r"\1", t)
    # Abbreviations
    for a, b in [("e.g.", "for example"), ("i.e.", "that is"), ("etc.", "etcetera."), ("vs.", "versus"), ("approx.", "approximately")]:
        t = re.sub(re.escape(a), b, t, flags=re.IGNORECASE)
    # URLs, emails, bare domains, dotted identifiers
    t = re.sub(r"\b(?:https?://|www\.)[^\s<>()\[\]\"']+", _url, t, flags=re.IGNORECASE)
    t = re.sub(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b",
               lambda m: " " + _dots(m.group(1)) + " at " + _dots(m.group(2)) + " ", t)
    t = re.sub(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|dev|ai|app|co|edu|gov|us|uk|me|tv)\b",
               lambda m: _dots(m.group(0)), t, flags=re.IGNORECASE)
    t = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z]{2,}\b)(?![A-Z][a-z])", " dot ", t)
    # Symbols and typography
    t = re.sub(r"\$" + _NUM, r"\1 dollars", t)
    t = re.sub("\u20AC" + _NUM, r"\1 euros", t)
    t = re.sub("\u00A3" + _NUM, r"\1 pounds", t)
    t = re.sub(r"#(?=\d)", " number ", t)
    t = re.sub(r"~(?=\d)", " about ", t)
    t = re.sub(r"(?<=\w)/(?=\w)", " slash ", t)
    reps = [
        ("\u2018", "'"), ("\u2019", "'"), ("\u201A", "'"), ("\u201B", "'"), ("`", "'"),
        ("\u201C", ""), ("\u201D", ""), ("\u201E", ""), ("\u201F", ""), ("\u00AB", ""), ("\u00BB", ""), ('"', ""),
        ("\u2013", ", "), ("\u2014", ", "), ("\u2015", ", "), ("\u2026", ", "),
        ("\u2192", " to "), ("\u21D2", " to "), ("\u2190", " from "), ("\u00B0", " degrees "),
        ("\u2022", "\n- "), ("\u2028", "\n"), ("\u2029", "\n"), ("\u0085", "\n"), ("\t", " "),
        ("&", " and "), ("%", " percent "), ("@", " at "), ("+", " plus "), ("=", " equals "),
        ("\\", " "), ("|", ", "), ("<", " "), (">", " "), ("{", " "), ("}", " "), ("[", " "), ("]", " "),
        ("^", " "), ("*", " "), ("_", " "),
    ]
    for a, b in reps:
        t = t.replace(a, b)
    t = "".join(_strip_scalar(c) for c in t)
    # Repeated punctuation, glued sentences ("know.If"), stray spacing
    t = re.sub(r"[!?]*\?[!?]*", "?", t)
    t = re.sub(r"!+", "!", t)
    t = re.sub(r"\.{2,}", ", ", t)
    t = re.sub(r"([,;:])[,;:\s]*(?=[,;:])", "", t)
    t = re.sub(r"([\p{Ll}\p{N})'][.!?])(?=\p{Lu})", "\\1\n", t)
    lines = []
    for raw in t.split("\n"):
        l = raw
        l = re.sub(r"^\s*(?:[-*+\u25E6\u25AA\u25AB\u25CF\u25CB\u00B7\u2023\u2043]|\(?\d{1,3}[.)]|[a-zA-Z][.)])\s+", "", l)
        l = re.sub(r"^\s*-\s+", "", l)
        l = re.sub(r"[^\p{L}\p{N}\s.,!?;:'()-]", " ", l)
        l = re.sub(r"\s+-+\s+", ", ", l)
        l = re.sub(r"\(\s*\)", " ", l)
        l = re.sub(r"\s+", " ", l)
        l = re.sub(r"\s+([,.;:!?)])", r"\1", l)
        l = re.sub(r"([,;:])(?=[.!?])", "", l)
        l = re.sub(r"^[\s,.;:!?)'-]+", "", l)
        l = l.strip()
        if not any(c.isalnum() for c in l):
            continue
        if l[-1] in ",;:-(":
            l = l[:-1].strip() + "."
        elif l[-1] not in ".!?":
            l += "."
        lines.append(l)
    return lines


_ABBREV = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "ext", "no", "vol", "fig", "inc", "ltd", "co", "approx", "dept"}


def sentences(line: str):
    """Sentence split (stand-in for NLTokenizer): break after . ! ? + space + capital/digit/quote,
    except after common abbreviations and single initials."""
    out, start = [], 0
    for m in re.finditer(r"[.!?]+(?=\s+[\p{Lu}\p{N}'(])", line):
        before = line[start:m.start()].split()
        last = before[-1].lower().strip("(") if before else ""
        if m.group(0) == "." and (last in _ABBREV or (len(last) == 1 and last.isalpha())):
            continue
        out.append(line[start:m.end()].strip())
        start = m.end()
    rest = line[start:].strip()
    if rest:
        out.append(rest)
    return out or [line]


def cap_split(s: str):
    """Split a sentence longer than MAX_CHUNK at clause boundaries, else at word boundaries (balanced)."""
    if len(s) <= MAX_CHUNK:
        return [s]
    words = s.split(" ")
    parts = -(-len(s) // MAX_CHUNK)
    target = len(s) / parts
    out, cur = [], ""
    for w in words:
        is_last = len(out) >= parts - 1
        if cur and len(cur) + 1 + len(w) > min(target * 1.15, MAX_CHUNK):
            out.append(cur if cur[-1] in ",;:" else cur + ",")
            cur = ""
        cur += (" " if cur else "") + w
        if not is_last and len(cur) >= target * 0.75 and w and w[-1] in ",;:":
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def merge_tiny(chunks):
    out = []
    for c in chunks:
        if out and (word_count(c) < MIN_WORDS or word_count(out[-1]) < MIN_WORDS) and len(out[-1]) + len(c) + 1 <= MAX_CHUNK + 40:
            out[-1] = out[-1] + " " + c
        else:
            out.append(c)
    return out


def chunks(text: str):
    out = []
    for line in normalize_to_lines(text):
        for s in sentences(line):
            out += cap_split(s)
    return merge_tiny(out)


def split_in_half(s: str):
    words = s.split(" ")
    if len(words) < 6:
        return None
    mid = len(words) // 2
    best = mid
    for d in range(len(words) // 3):
        i, j = mid - 1 - d, mid - 1 + d
        if i >= 2 and words[i] and words[i][-1] in ",;:":
            best = i + 1
            break
        if j <= len(words) - 3 and words[j] and words[j][-1] in ",;:":
            best = j + 1
            break
    return [" ".join(words[:best]), " ".join(words[best:])]


class BabbleGuard:
    """Detects Piper babble/skip from audio duration vs. phoneme count (same thresholds as macOS).
    Calibrated: normal speech 0.054-0.103 s/phoneme; confirmed babble case 0.040."""
    MIN_SPP, MAX_SPP, MIN_SPW, MAX_SPW = 0.043, 0.16, 0.12, 1.0

    @classmethod
    def check(cls, text: str, seconds: float, phonemes: int):
        w = max(1, word_count(text))
        spw = seconds / w
        spp = seconds / phonemes if phonemes > 0 else 0.0
        reason = ""
        if seconds < 0.15:
            reason = "empty audio"
        elif phonemes >= 12 and spp < cls.MIN_SPP:
            reason = "too fast for its phonemes (skipped speech)"
        elif phonemes >= 12 and spp > cls.MAX_SPP:
            reason = "too slow for its phonemes (babble)"
        elif w >= 4 and spw < cls.MIN_SPW:
            reason = "too short per word"
        elif w >= 4 and spw > cls.MAX_SPW:
            reason = "too long per word"
        return (reason == "", spp, spw, reason)
