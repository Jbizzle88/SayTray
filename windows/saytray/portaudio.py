"""Shared PortAudio lifetime.

sounddevice's _terminate() frees the host while it still has streams. On Windows
that is an access violation in pythonw, and it also breaks the player's
keepalive stream. Re-initialize only when every known stream is closed, and
only while holding this lock so a stream cannot open underneath the call.
"""
import threading

_lock = threading.RLock()


def lock():
    return _lock


def stream_alive(stream):
    """True when `stream` might still be registered with PortAudio.

    A stopped stream is still open until it is closed. A stream whose state
    cannot be read is treated as alive so a host restart cannot free it.
    """
    if stream is None:
        return False
    try:
        if bool(getattr(stream, "closed", False)):
            return False
    except Exception:
        return True
    try:
        if bool(stream.active):
            return True
    except Exception:
        return True
    # sounddevice streams stay registered after stop() until close().
    return hasattr(stream, "closed")


def refresh_devices(streams):
    """Re-query devices by restarting PortAudio when nothing is open.

    Returns True when the host was re-initialized. Returns False when any
    stream is still alive; the caller must use the device list it already has.
    """
    import sounddevice as sd
    with _lock:
        if any(stream_alive(stream) for stream in streams):
            return False
        try:
            if getattr(sd, "_initialized", False):
                sd._terminate()
        except Exception:
            pass
        try:
            sd._initialize()
        except Exception:
            return False
        return True
