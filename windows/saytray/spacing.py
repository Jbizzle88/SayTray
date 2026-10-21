"""Join dictated text to the cursor, and concatenate recognizer segments.

Same rules as macOS DictationSpacing: one leading space between back-to-back
phrases, never a double space, never a space after a newline or at the start
of an empty field, and a later segment must not erase the beginning.
"""

_PUNCT = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~") | set("“”‘’…—–")


def _punct(ch):
    return ch in _PUNCT


def prepare(text, previous):
    """Strip the recognizer text, then apply the one-space rule."""
    return apply((text or "").strip(), previous)


def apply(text, previous):
    """previous is one character or None (empty field / unknown boundary)."""
    if not text:
        return text
    first = text[0]
    if first.isspace() or _punct(first):
        return text
    if previous is None or (isinstance(previous, str) and (not previous or previous[-1].isspace())):
        return text
    prev = previous[-1] if len(previous) != 1 else previous
    if prev.isspace():
        return text
    return " " + text


def merge(previous, incoming):
    a = (previous or "").strip()
    b = (incoming or "").strip()
    if not a:
        return b
    if not b:
        return a
    if b.startswith(a):
        return b
    if a.startswith(b):
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
