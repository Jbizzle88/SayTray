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


def split_pcm(audio, sample_rate, limit_s):
    """Split a 1-D clip into pieces no longer than limit_s. Order is preserved."""
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    step = int(sample_rate * limit_s)
    if step <= 0 or audio.size <= step:
        return [audio]
    return [audio[i:i + step] for i in range(0, audio.size, step)]
