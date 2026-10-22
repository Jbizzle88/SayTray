"""Fixed pre-roll of recent microphone samples, and splitting long clips.

The ring keeps the last `seconds` of audio so a dictation can include the
moment of the key press. Long clips are cut into recognizer-sized pieces
without dropping or reordering samples.
"""
import numpy as np


class Ring:
    def __init__(self, capacity):
        self.capacity = max(1, int(capacity))
        self.buf = np.zeros(self.capacity, np.float32)
        self.pos = 0
        self.filled = 0

    def push(self, samples):
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        n = int(samples.size)
        if n <= 0:
            return
        if n >= self.capacity:
            self.buf[:] = samples[-self.capacity:]
            self.pos = 0
            self.filled = self.capacity
            return
        end = self.pos + n
        if end <= self.capacity:
            self.buf[self.pos:end] = samples
        else:
            head = self.capacity - self.pos
            self.buf[self.pos:] = samples[:head]
            self.buf[:n - head] = samples[head:]
        self.pos = end % self.capacity
        self.filled = min(self.capacity, self.filled + n)

    def snapshot(self):
        if self.filled <= 0:
            return np.zeros(0, np.float32)
        if self.filled < self.capacity:
            return self.buf[:self.filled].copy()
        return np.concatenate((self.buf[self.pos:], self.buf[:self.pos])).copy()

    def clear(self):
        self.pos = 0
        self.filled = 0


def _quiet_cut(audio, end, sample_rate, window_s=0.35):
    """Move a cut to a quiet moment in the last part of the slice, when there is one."""
    frame = max(1, int(sample_rate * 0.02))
    start = max(0, end - int(sample_rate * window_s))
    if end - start <= frame:
        return end
    edge = audio[max(0, end - frame):end]
    edge_rms = float(np.sqrt(np.mean(edge * edge))) + 1e-8
    best = end
    best_rms = edge_rms
    i = start
    while i + frame <= end:
        seg = audio[i:i + frame]
        rms = float(np.sqrt(np.mean(seg * seg)))
        if rms < best_rms:
            best_rms = rms
            best = i
        i += frame
    if best < end and best_rms < 0.02 and best_rms < edge_rms * 0.5:
        return best
    return end


def split_pcm(audio, sample_rate, limit_s):
    """Split a 1-D clip into pieces no longer than limit_s. Order is preserved.

    A cut near the limit moves earlier when that moment is quiet, so a word is
    less likely to be sliced in half. Loud audio keeps the hard limit.
    """
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    step = int(sample_rate * limit_s)
    if step <= 0 or audio.size <= step:
        return [audio]
    parts = []
    i = 0
    while i < audio.size:
        end = min(audio.size, i + step)
        if end < audio.size:
            end = _quiet_cut(audio, end, sample_rate)
            if end <= i:
                end = min(audio.size, i + step)
        parts.append(audio[i:end])
        i = end
    return parts


def overlapped_pieces(audio, sample_rate, limit_s, overlap_s):
    """Same cuts as split_pcm, plus a short copy of the audio on each side of a cut.

    Every sample is still in at least one piece, in order. The extra samples are how
    a word that sat on the cut can be heard in both slices. Pieces stay under a minute
    when the limit is 30 s and the overlap is about a second.
    """
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    pieces = split_pcm(audio, sample_rate, limit_s)
    overlap = int(sample_rate * overlap_s) if overlap_s and sample_rate else 0
    if overlap <= 0 or len(pieces) < 2:
        return pieces
    starts = []
    pos = 0
    for piece in pieces:
        starts.append(pos)
        pos += int(piece.size)
    out = []
    for i, piece in enumerate(pieces):
        a = starts[i]
        b = a + int(piece.size)
        if i > 0:
            a = max(0, a - overlap)
        if i + 1 < len(pieces):
            b = min(int(audio.size), b + overlap)
        out.append(audio[a:b])
    return out
