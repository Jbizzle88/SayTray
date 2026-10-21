"""Split a long dictation into recognizer-sized slices and concatenate them.

Speech requests (Apple's SFSpeechRecognizer, and a single Whisper window) do not
reliably return the beginning of a multi-minute clip. The full audio is kept.
It is recognized in pieces of at most SEGMENT_S seconds. If a piece's transcript
does not cover that piece, it is halved and recognized again, then joined in order.
"""
from .preroll import split_pcm
from .spacing import join_segments

SEGMENT_S = 30.0
MIN_SLICE_S = 8.0


def needs_resplit(audio_s, first_word_at, last_word_end, failed, characters):
    """Same rule as macOS DictationPlan.needsResplit."""
    if audio_s <= MIN_SLICE_S:
        return False
    if first_word_at is not None and first_word_at > 2:
        return True
    if last_word_end is not None and audio_s - last_word_end > 8:
        return True
    if failed and characters == 0:
        return True
    if audio_s > 12 and characters < int(audio_s * 3):
        return True
    return False


def stitch_audio(audio, sample_rate, limit_s, transcribe, depth_limit=4, on_resplit=None):
    """transcribe(samples) -> (text, first_word_at, last_word_end, failed).

    Offsets are seconds from the start of `samples`. Returns the joined transcript.
    Every sample is sent to some leaf transcription; none are dropped.
    """
    parts = []
    for piece in split_pcm(audio, sample_rate, limit_s):
        parts.append(_piece(piece, sample_rate, transcribe, 0, depth_limit, on_resplit))
    return join_segments(parts)


def _piece(samples, sample_rate, transcribe, depth, depth_limit, on_resplit):
    text, first, last, failed = transcribe(samples)
    text = text or ""
    audio_s = (len(samples) / sample_rate) if sample_rate else 0
    if depth < depth_limit and needs_resplit(audio_s, first, last, failed, len(text)):
        mid = len(samples) // 2
        if mid <= 0 or mid >= len(samples):
            return text
        if on_resplit:
            on_resplit(audio_s, first, last)
        left = _piece(samples[:mid], sample_rate, transcribe, depth + 1, depth_limit, on_resplit)
        right = _piece(samples[mid:], sample_rate, transcribe, depth + 1, depth_limit, on_resplit)
        return join_segments([left, right])
    return text
