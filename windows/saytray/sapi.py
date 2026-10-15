"""Windows SAPI fallback voice, rendered to WAV so it goes through the same player (and speed control)."""
import threading
_local = threading.local()


def _voice():
    if getattr(_local, "v", None) is None:
        import comtypes, comtypes.client
        comtypes.CoInitialize()
        _local.v = comtypes.client.CreateObject("SAPI.SpVoice")
    return _local.v


def voices():
    try:
        v = _voice()
        toks = v.GetVoices()
        return [toks.Item(i).GetDescription() for i in range(toks.Count)]
    except Exception:
        return []


def render(text, path, voice_desc=""):
    import comtypes.client
    v = _voice()
    if voice_desc:
        toks = v.GetVoices()
        for i in range(toks.Count):
            if toks.Item(i).GetDescription() == voice_desc:
                v.Voice = toks.Item(i)
                break
    stream = comtypes.client.CreateObject("SAPI.SpFileStream")
    fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
    fmt.Type = 22  # SAFT22kHz16BitMono
    stream.Format = fmt
    stream.Open(path, 3)  # SSFMCreateForWrite
    old = v.AudioOutputStream
    v.AudioOutputStream = stream
    try:
        v.Speak(text, 0)
    finally:
        stream.Close()
        v.AudioOutputStream = old
