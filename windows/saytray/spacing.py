"""Join dictated text to the cursor, and concatenate recognizer slices.

Same rules as macOS DictationSpacing. One leading space between phrases, never a
double space, never a space after a newline or at the start of an empty field.
Independent slices are concatenated. A shared prefix does not drop either side.
Opening quotes, parentheses, and $ get a space. Commas and periods stay attached.
"""

# Attached punctuation does not get a leading space. Opening quotes, brackets, $, ¿, and ¡ do.
_ATTACHED = set("!#%&)*+,-./:;<=>?@\\]^_`|}~") | set("”’…—–")
_OPENING = set("¿¡")


def _attached(ch):
    return ch in _ATTACHED


def _opening_quote(text):
    """A straight quote followed by a word is opening. A quote followed by space is closing."""
    if not text or text[0] not in "\"'":
        return False
    if len(text) < 2:
        return False
    return not text[1].isspace()


def prepare(text, previous):
    """Strip the recognizer text, then apply the one-space rule."""
    return apply((text or "").strip(), previous)


def apply(text, previous):
    """previous is one character or None (empty field / unknown boundary)."""
    if not text:
        return text
    first = text[0]
    if first in _OPENING:
        pass
    elif first.isspace() or _attached(first):
        return text
    if first in "\"'" and not _opening_quote(text):
        return text
    if previous is None or (isinstance(previous, str) and (not previous or previous[-1].isspace())):
        return text
    prev = previous[-1] if len(previous) != 1 else previous
    if prev.isspace():
        return text
    return " " + text


def _words(text):
    return [w for w in (text or "").split() if w]


def _same_word(a, b):
    def norm(w):
        return "".join(ch for ch in w.casefold() if ch.isalnum())
    na, nb = norm(a), norm(b)
    return bool(na) and na == nb


def dedupe_boundary(left, right, max_words=8):
    """Drop a short repeated prefix of `right` that copies the end of `left`.

    Used only where two slices share audio. A long shared sentence is left alone.
    "I" and "It" do not match.
    """
    lw, rw = _words(left), _words(right)
    if not lw or not rw:
        return right or ""
    cap = max(1, int(max_words or 1))
    best = 0
    limit = min(cap, len(lw), len(rw))
    for n in range(1, limit + 1):
        if all(_same_word(lw[-n + i], rw[i]) for i in range(n)):
            best = n
    if best <= 0:
        return right or ""
    kept = rw[best:]
    if not kept:
        return ""
    # Preserve the original spacing of the surviving tail.
    tail = right
    for word in rw[:best]:
        idx = tail.find(word)
        if idx < 0:
            break
        tail = tail[idx + len(word):]
    return tail.lstrip()


def join_overlapped(parts, max_words=8):
    """Join slices that shared a second of audio, dropping the repeated boundary words."""
    out = ""
    for part in parts:
        piece = part or ""
        if out:
            piece = dedupe_boundary(out, piece, max_words)
        out = merge(out, piece)
    return out


def merge(previous, incoming):
    """Join two independent slices. Nothing is dropped because one starts with the other."""
    a = (previous or "").strip()
    b = (incoming or "").strip()
    if not a:
        return b
    if not b:
        return a
    return a + apply(b, a[-1])


def join_segments(parts):
    out = ""
    for part in parts:
        out = merge(out, part)
    return out


def simulate_inserts(parts):
    """Type parts in order, using the last typed character as the cursor context."""
    typed = ""
    for part in parts:
        piece = prepare(part, typed[-1] if typed else None)
        typed += piece
    return typed
