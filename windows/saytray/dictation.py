"""Push-to-talk dictation: record while the hotkey is held, transcribe locally with faster-whisper
(base.en, CPU int8), type the result at the cursor.

The input stream keeps ~450 ms of audio and is closed about 3 seconds after a
dictation, so the OS mic indicator turns off. It stays open while the dictate
modifiers are held. The session itself is every sample from key-down to key-up,
with no duration cap. Long clips are transcribed in 30 s pieces (under one Whisper
window). A piece whose transcript does not cover it is halved and transcribed again,
then the pieces are concatenated in order.
"""
import os, threading, time
import numpy as np
from . import logs
from .preroll import Ring
from .segments import SEGMENT_S, stitch_audio
from .config import coerce_bool
from .selection import insert_dictation

SR = 16000
_PRE_ROLL_S = 0.45
_MIN_LIVE_S = 0.15
_MIN_TRANSCRIBE_S = 0.30     # shorter than this is a tap, not speech
_SHORT_CLIP_S = 1.5          # room noise under this length needs a stronger energy gate
_SHORT_VAD_S = 2.0           # temperature fallback and VAD apply under this length
_SHORT_ENERGY_RMS = 0.004
_GRACE_S = 0.25          # keep capturing briefly after key-up so the last word is not lost
_IDLE_MIC_S = 3.0           # every input is released soon after a hold so the mic indicator turns off
_MODEL_IDLE_S = 600.0       # unload Whisper after 10 minutes with no dictation
_CHIME_SETTLE_S = 0.40       # a just-opened stream waits this long before the start chime
_SILENCE_RMS = 0.001


def keep_whisper_segment(text, no_speech_prob, avg_logprob):
    """Drop silence hallucinations such as a lone "you" on a quiet slice."""
    if not (text or "").strip():
        return False
    try:
        nsp = float(0 if no_speech_prob is None else no_speech_prob)
    except (TypeError, ValueError):
        nsp = 0.0
    try:
        lp = float(0 if avg_logprob is None else avg_logprob)
    except (TypeError, ValueError):
        lp = 0.0
    if nsp >= 0.6 and lp < -0.5:
        return False
    if nsp >= 0.85:
        return False
    return True


_HANDSFREE_MARKS = ("bluetooth", "hands-free", "hands free", "airpod", " ag audio", "hfp", "hsp")
_VIRTUAL_MARKS = (
    "oculus", "steam streaming", "nvidia virtual", "nvidia broadcast",
    "vb-audio", "vb-cable", "voicemeeter", "virtual audio", "virtual cable",
    "cable output", "cable input",
)


def classify_input(name="", endpoint_id="", instance_id=""):
    """'hands-free', 'wired', 'virtual', or 'unknown'.

    Bluetooth shows up as BTHENUM or BTHHFENUM on the Windows endpoint, even when
    the PortAudio name is truncated. A name that starts with 'Headset (' is the
    Windows hands-free endpoint, unless it is a virtual device such as Oculus.
    An empty result is unknown.
    """
    blob = f"{endpoint_id}\n{instance_id}".upper()
    if "BTHHFENUM" in blob or "BTHENUM" in blob:
        return "hands-free"
    n = (name or "").strip()
    low = n.lower()
    if any(mark in low for mark in _VIRTUAL_MARKS):
        return "virtual"
    if low.startswith("headset ("):
        return "hands-free"
    if any(mark in low for mark in _HANDSFREE_MARKS):
        return "hands-free"
    if not n and not blob.strip():
        return "unknown"
    return "wired"


def combine_input_kinds(*kinds):
    if "hands-free" in kinds:
        return "hands-free"
    if "wired" in kinds:
        return "wired"
    if "virtual" in kinds:
        return "virtual"
    return "unknown"


def choose_input_index(devices, default_index=None):
    """Index of a real microphone when the default input is virtual.

    Returns None to keep the default. `devices` is a list of dicts with
    index, name, and max_input_channels.
    """
    default = None
    for dev in devices or []:
        if default_index is not None and dev.get("index") == default_index:
            default = dev
            break
    if default is not None and classify_input(default.get("name") or "") != "virtual":
        return None
    if default is None and default_index is None:
        return None
    for dev in devices or []:
        if int(dev.get("max_input_channels") or 0) < 1:
            continue
        if default is not None and dev.get("index") == default.get("index"):
            continue
        if classify_input(dev.get("name") or "") in ("wired", "hands-free"):
            return dev.get("index")
    return None


def clip_rms(samples):
    if samples is None or len(samples) == 0:
        return 0.0
    arr = np.asarray(samples, dtype=np.float32)
    return float(np.sqrt(np.mean(np.square(arr))))


def clip_should_skip(samples, sample_rate):
    """Why a clip should not be sent to Whisper, or '' when it should.

    A very short tap is ignored. Room noise under 1.5 s is ignored unless it
    is loud enough to be speech. Longer clips use the digital-silence gate only.
    """
    n = 0 if samples is None else len(samples)
    if n <= 0 or not sample_rate:
        return "too short"
    dur = n / float(sample_rate)
    if dur < _MIN_TRANSCRIBE_S:
        return "too short"
    if dur < _SHORT_CLIP_S and clip_rms(samples) < _SHORT_ENERGY_RMS:
        return "low energy"
    return ""


def segment_past_audio(end, audio_s, slack=0.5):
    """True when a Whisper timestamp runs past the audio that was sent."""
    try:
        end_s = float(end)
    except (TypeError, ValueError):
        return False
    return end_s > float(audio_s) + slack


def input_releases_quickly(name="", endpoint_id="", instance_id=""):
    """True when this input should not stay open. Unknown is not 'quickly' by name."""
    return classify_input(name, endpoint_id, instance_id) == "hands-free"


def idle_seconds_for_input(name="", endpoint_id="", instance_id=""):
    """Every input is released after a few seconds. The OS mic light stays on while the stream is open."""
    return _IDLE_MIC_S


def should_prewarm(kind, already_open):
    """Modifier pre-warm is only for a wired mic that is currently closed."""
    return kind == "wired" and not already_open


def _windows_capture_ids():
    """Default capture endpoint id and device instance id. Empty off Windows."""
    if os.name != "nt":
        return "", ""
    try:
        return _mmdevice_capture_ids()
    except Exception:
        return "", ""


# x64 PROPVARIANT is 24 bytes: an 8-byte header plus a 16-byte union.
# A 16-byte buffer lets IPropertyStore::GetValue write past the object.
# The bus path looks like "{1}.BTHENUM\...". The enumerator name is "BTHENUM" or "USB".
_PKEY_DEVICE_BUS = ("b3f8fa53-0004-438e-9003-51a46e139bfc", 2)
_PKEY_DEVICE_ENUMERATOR = ("a45c254e-df1c-4efd-8020-67d146a850e0", 24)
_VT_LPWSTR = 31


def _propvariant_type():
    import ctypes
    from ctypes import wintypes

    class PROPVARIANT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [
                ("pwszVal", ctypes.c_wchar_p),
                ("_pad", ctypes.c_byte * 16),
            ]

        _fields_ = [
            ("vt", wintypes.USHORT),
            ("wReserved1", wintypes.USHORT),
            ("wReserved2", wintypes.USHORT),
            ("wReserved3", wintypes.USHORT),
            ("u", _U),
        ]

    return PROPVARIANT


def propvariant_size():
    import ctypes
    return ctypes.sizeof(_propvariant_type())


def _mmdevice_capture_ids():
    import ctypes
    from ctypes import wintypes
    ole32 = ctypes.windll.ole32
    CLSCTX_ALL = 23
    eCapture = 1
    eMultimedia = 1
    COINIT_APARTMENTTHREADED = 2

    def guid(text):
        import uuid
        u = uuid.UUID(text)
        raw = (ctypes.c_byte * 16).from_buffer_copy(u.bytes_le)
        return raw

    class GUID(ctypes.Structure):
        _fields_ = [("data", ctypes.c_byte * 16)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    PROPVARIANT = _propvariant_type()
    ole32.PropVariantClear.argtypes = [ctypes.POINTER(PROPVARIANT)]
    ole32.PropVariantClear.restype = ctypes.HRESULT
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
    ]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    clsid = GUID(guid("BCDE0395-E52F-467C-8E3D-C4579291692E"))
    iid_enum = GUID(guid("A95664D2-9614-4F35-A746-DE8DB63617E6"))
    iid_store = GUID(guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"))
    enumerator = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, CLSCTX_ALL, ctypes.byref(iid_enum), ctypes.byref(enumerator))
    if hr < 0 or not enumerator:
        return "", ""

    def vtbl(ptr, slot, restype, *argtypes):
        table = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return proto(table[slot])

    endpoint = ctypes.c_void_p()
    get_default = vtbl(enumerator, 4, ctypes.HRESULT, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
    hr = get_default(enumerator, eCapture, eMultimedia, ctypes.byref(endpoint))
    if hr < 0 or not endpoint:
        return "", ""
    id_ptr = ctypes.c_wchar_p()
    get_id = vtbl(endpoint, 5, ctypes.HRESULT, ctypes.POINTER(ctypes.c_wchar_p))
    endpoint_id = ""
    if get_id(endpoint, ctypes.byref(id_ptr)) >= 0 and id_ptr.value:
        endpoint_id = id_ptr.value
        ole32.CoTaskMemFree(id_ptr)
    instance_parts = []
    store = ctypes.c_void_p()
    open_store = vtbl(endpoint, 4, ctypes.HRESULT, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))
    if open_store(endpoint, 0, ctypes.byref(store)) >= 0 and store:
        get_value = vtbl(store, 5, ctypes.HRESULT, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))

        def read_prop(fmtid, pid):
            key = PROPERTYKEY()
            key.fmtid = GUID(guid(fmtid))
            key.pid = pid
            var = PROPVARIANT()
            text = ""
            try:
                if get_value(store, ctypes.byref(key), ctypes.byref(var)) >= 0 and var.vt == _VT_LPWSTR and var.u.pwszVal:
                    text = var.u.pwszVal
            finally:
                ole32.PropVariantClear(ctypes.byref(var))
            return text or ""

        for fmtid, pid in (_PKEY_DEVICE_BUS, _PKEY_DEVICE_ENUMERATOR):
            got = read_prop(fmtid, pid)
            if got:
                instance_parts.append(got)
        release = vtbl(store, 2, ctypes.c_ulong)
        release(store)
    release_dev = vtbl(endpoint, 2, ctypes.c_ulong)
    release_dev(endpoint)
    release_enum = vtbl(enumerator, 2, ctypes.c_ulong)
    release_enum(enumerator)
    return endpoint_id or "", "\n".join(instance_parts)


def _host_input_names():
    """Default input name, plus the WASAPI name when PortAudio has that host API.

    MME truncates names to 31 characters. WASAPI keeps the full 'Headset (…)' name.
    """
    try:
        import sounddevice as sd
    except Exception:
        return "", ""
    short = ""
    try:
        dev = sd.query_devices(kind="input")
        short = ((dev or {}).get("name") or "") if isinstance(dev, dict) else ""
    except Exception:
        short = ""
    wasapi = ""
    try:
        for api in sd.query_hostapis():
            if "WASAPI" not in str(api.get("name") or "").upper():
                continue
            idx = api.get("default_input_device", -1)
            if idx is None or int(idx) < 0:
                continue
            info = sd.query_devices(int(idx))
            wasapi = (info or {}).get("name") or ""
            break
    except Exception:
        wasapi = ""
    return short, wasapi


def slice_is_silent(samples, sample_rate):
    """Near-digital silence. A quiet mic still sits above this; Whisper's own filter does the rest."""
    if samples is None or len(samples) == 0:
        return True
    rms = float(np.sqrt(np.mean(np.square(np.asarray(samples, dtype=np.float32)))))
    return rms < _SILENCE_RMS


class Dictation:
    def __init__(self, player=None, settings=None):
        self._model = None
        self._stream = None
        self._frames = []
        self._capturing = False
        self.recording = False
        self.on_state = None
        self.player = player
        self.settings = settings
        self._lock = threading.Lock()
        self._open_lock = threading.Lock()
        self._transcribe_lock = threading.Lock()
        self._gen = 0
        self._phase = "idle"  # idle, recording, finalizing
        self._ring = Ring(int(SR * _PRE_ROLL_S))
        self._pre_samples = 0
        self._pressed_at = None
        self._first_live_at = None
        self._closed = False
        self._grace_gen = None
        self._idle_token = None
        self.on_notice = None
        self._model_error = None
        self._input_name = ""
        self._input_kind = "unknown"
        self._endpoint_id = ""
        self._instance_id = ""
        self._idle_timer = None
        self._modifier_held = False
        self._model_loading = False
        self._model_lock = threading.Lock()
        self._model_timer = None
        self._model_token = None
        threading.Thread(target=self._open_warm, daemon=True, name="dictation-warm").start()

    def _ensure_model(self):
        """Load Whisper on the first dictate. A bare test object has no model lock."""
        if getattr(self, "_model_lock", None) is None or self._closed:
            return
        self._cancel_model_unload()
        start = False
        with self._model_lock:
            token = time.monotonic()
            self._model_token = token
            if self._model is None and not self._model_loading:
                self._model_loading = True
                start = True
        if start:
            threading.Thread(target=self._load_model, args=(token,), daemon=True, name="whisper-load").start()

    def _cancel_model_unload(self):
        timer = getattr(self, "_model_timer", None)
        self._model_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_model_unload(self):
        if getattr(self, "_model_lock", None) is None:
            return
        self._cancel_model_unload()
        token = time.monotonic()
        with self._model_lock:
            self._model_token = token
        timer = threading.Timer(_MODEL_IDLE_S, self._unload_model, args=(token,))
        timer.daemon = True
        self._model_timer = timer
        timer.start()

    def _unload_model(self, token):
        with self._lock:
            if self._closed or self._phase != "idle":
                return
        with self._model_lock:
            if token != self._model_token or self._model is None:
                return
            model = self._model
            self._model = None
            self._model_loading = False
        del model
        import gc
        gc.collect()
        logs.event("dictation: whisper unloaded after 10 minutes idle")

    def _load_model(self, token=None):
        delay = 2.0
        while not self._closed:
            try:
                from faster_whisper import WhisperModel
                t0 = time.time()
                model = WhisperModel("base.en", device="cpu", compute_type="int8")
                with self._model_lock:
                    if token is not None and token != self._model_token:
                        self._model_loading = False
                        logs.event("dictation: whisper load discarded")
                        return
                    self._model = model
                    self._model_loading = False
                self._model_error = None
                logs.event(f"dictation: whisper base.en loaded in {time.time() - t0:.1f}s")
                return
            except Exception as e:
                self._model_error = str(e)
                logs.event(f"dictation: model load failed: {e!r}; retrying in {delay:.0f}s")
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
        with self._model_lock:
            self._model_loading = False

    def _cb(self, indata, frames, t, status):
        samples = indata[:, 0].copy()
        with self._lock:
            self._ring.push(samples)
            if self._capturing:
                if self._first_live_at is None:
                    self._first_live_at = time.monotonic()
                self._frames.append(samples)

    def _stream_ok(self):
        try:
            return self._stream is not None and bool(self._stream.active)
        except Exception:
            return False

    def _close_stream(self):
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def _default_changed(self):
        endpoint, _instance = _windows_capture_ids()
        return bool(endpoint and self._endpoint_id and endpoint != self._endpoint_id)

    def _open_warm(self):
        with self._open_lock:
            with self._lock:
                if self._closed or self._stream_ok():
                    return False
            import sounddevice as sd
            try:
                if getattr(sd, "_initialized", False):
                    sd._terminate()
            except Exception:
                pass
            try:
                sd._initialize()
            except Exception:
                pass
            short, wasapi = _host_input_names()
            endpoint, instance = _windows_capture_ids()
            name = wasapi or short
            if short and wasapi and len(wasapi) >= len(short):
                name = wasapi
            kind = combine_input_kinds(
                classify_input(short, endpoint, instance),
                classify_input(wasapi, endpoint, instance),
            )
            device = None
            try:
                listed = sd.query_devices()
                default_index = sd.default.device[0]
                rows = []
                for i, dev in enumerate(listed):
                    rows.append({
                        "index": i,
                        "name": dev["name"],
                        "max_input_channels": dev["max_input_channels"],
                    })
                picked = choose_input_index(rows, default_index)
            except Exception:
                picked = None
                rows = []
            if picked is not None:
                device = picked
                picked_name = next((row["name"] for row in rows if row["index"] == picked), "")
                logs.event(
                    f"dictation: default input {name or 'unknown'!r} is virtual; using {picked_name!r}"
                )
                name = picked_name or name
                kind = classify_input(name)
            elif kind == "virtual":
                logs.event(
                    f"dictation: warning: default input {name or 'unknown'!r} is virtual "
                    "and no other microphone was found"
                )
            self._input_name = name or short
            self._input_kind = kind
            self._endpoint_id = endpoint
            self._instance_id = instance
            try:
                stream_kwargs = dict(samplerate=SR, channels=1, dtype="float32", callback=self._cb)
                if device is not None:
                    stream_kwargs["device"] = device
                stream = sd.InputStream(**stream_kwargs)
                stream.start()
            except Exception as e:
                logs.event(f"dictation: microphone open failed: {e!r}")
                return False
            with self._lock:
                if self._closed:
                    try:
                        stream.stop(); stream.close()
                    except Exception:
                        pass
                    return False
                old, self._stream = self._stream, stream
            if old is not None:
                try:
                    old.stop(); old.close()
                except Exception:
                    pass
            logs.event(
                f"dictation: pre-roll microphone running input={self._input_name or 'unknown'!r} "
                f"kind={kind} idle={idle_seconds_for_input(self._input_name, endpoint, instance):.0f}s"
            )
            self._after_open()
            return True

    def _after_open(self):
        """Arm one idle timer when the launch open (or a later open) finds us idle."""
        with self._lock:
            idle = (not self._closed) and self._phase == "idle"
        if idle:
            self._arm_mic_idle()

    def warm(self):
        """Open a closed wired mic when the dictate modifiers go down.

        Already-open mics are left alone, so a modifier does not stack idle timers.
        Bluetooth and unknown inputs wait for the main key, so a headset is not
        pulled into a call just because Option or Alt was tapped.
        """
        if self._closed:
            return False
        self._ensure_model()
        with self._lock:
            running = self._stream_ok()
            kind = self._input_kind
        if running and self._default_changed():
            logs.event("dictation: default input changed; closing the microphone so it can reopen")
            self._close_stream()
            running = False
        if not should_prewarm(kind, running):
            return False
        opened = bool(self._open_warm())
        if opened:
            logs.event("dictation: pre-roll re-warmed on modifier")
        return opened

    def start(self):
        pressed = time.monotonic()
        self._ensure_model()
        if self._stream_ok() and self._default_changed():
            logs.event("dictation: default input changed; reopening the microphone")
            self._close_stream()
        with self._lock:
            if self._closed:
                logs.event("dictation: start ignored, shutting down")
                return
            if self._phase == "recording":
                logs.event("dictation: start ignored, already recording")
                return
            pending = self._grace_gen if self._phase == "grace" else None
        if pending is not None:
            self._end_grace(pending)
        with self._lock:
            if self._closed or self._phase == "recording":
                return
            if self._phase == "finalizing":
                logs.event("dictation: previous session still finalizing; starting a new one")
            self._idle_token = None
            self._gen += 1
            gen = self._gen
            self._phase = "recording"
            self.recording = True
            need_open = not self._stream_ok()
        self._state()
        just_opened = False
        if need_open:
            just_opened = self._open_warm()
        with self._lock:
            if gen != self._gen or self._phase != "recording":
                logs.event(f"dictation: start cancelled gen {gen}")
                return
            if not self._stream_ok():
                self._phase = "idle"
                self.recording = False
                self._capturing = False
                failed = True
            else:
                pre = self._ring.snapshot()
                self._frames = [pre] if pre.size else []
                self._pre_samples = int(pre.size)
                self._pressed_at = pressed
                self._first_live_at = None
                self._capturing = True
                failed = False
                pre_s = pre.size / SR
        if failed:
            logs.event("dictation: microphone not running")
            self._state()
            return
        # Capture is already running. A stream that just opened can reroute output,
        # so the start chime waits until that settles. A warm mic plays it now.
        if just_opened:
            logs.event("dictation: microphone was just opened; start chime waits for the stream to settle")
            delay = max(0.0, _CHIME_SETTLE_S)
            timer = threading.Timer(delay, self._chime_if_recording, args=("start", gen))
            timer.daemon = True
            timer.start()
            label = "deferred"
        else:
            chime_ok = self._chime("start")
            label = {True: "played", False: "FAILED"}.get(chime_ok, "off")
        logs.event(
            f"dictation: capture gen {gen} chime={label} pre-roll {pre_s * 1000:.0f}ms "
            f"input={self._input_name or 'unknown'!r} kind={self._input_kind}"
        )
        self._state()

    def stop(self):
        with self._lock:
            if self._phase != "recording":
                return
            gen = self._gen
            self._phase = "grace"
            self._grace_gen = gen
            self.recording = False
        self._state()
        self._chime("stop")
        timer = threading.Timer(_GRACE_S, self._end_grace, args=(gen,))
        timer.daemon = True
        timer.start()

    def _end_grace(self, gen):
        """Finish the hold, including a short tail, and drop that tail from the next pre-roll."""
        with self._lock:
            if self._phase != "grace" or self._grace_gen != gen:
                return
            self._capturing = False
            self._phase = "finalizing"
            frames = self._frames
            self._frames = []
            pre = self._pre_samples
            pressed = self._pressed_at
            first = self._first_live_at
            self._ring.clear()
        self._state()
        audio = np.concatenate(frames) if frames else np.zeros(0, np.float32)
        live = max(0, len(audio) - pre)
        lat = ((first - pressed) * 1000.0) if first is not None and pressed is not None else -1.0
        logs.event(
            f"dictation: stopped gen {gen} audio {len(audio) / SR:.2f}s "
            f"frames {len(frames)} (no duration cap) "
            f"pre-roll {pre / SR * 1000:.0f}ms live {live / SR:.2f}s first-buffer {lat:.0f}ms"
        )
        if live < int(SR * _MIN_LIVE_S) or clip_should_skip(audio, SR) == "too short":
            logs.event("dictation: too short, ignored")
            with self._lock:
                if self._gen == gen and self._phase == "finalizing":
                    self._phase = "idle"
            self._state()
            self._arm_mic_idle()
            self._schedule_model_unload()
            return
        threading.Thread(target=self._finish, args=(audio, gen), daemon=True, name="dictation-stop").start()

    def set_modifier_session(self, held):
        """Keep the mic open for the whole modifier hold, including gaps between rapid dictations."""
        with self._lock:
            self._modifier_held = bool(held)
            phase = self._phase
            closed = self._closed
        if held:
            self._cancel_idle_timer()
            logs.event("dictation: mic stays open while the dictate modifier is held")
        elif not closed and phase == "idle":
            self._arm_mic_idle()

    def _cancel_idle_timer(self):
        old = self._idle_timer
        self._idle_timer = None
        if old is not None:
            old.cancel()

    def _arm_mic_idle(self):
        self._cancel_idle_timer()
        with self._lock:
            if self._closed or self._modifier_held or self._phase != "idle":
                self._idle_token = None
                arm = False
                held = self._modifier_held
            else:
                arm = True
                held = False
                token = time.monotonic()
                self._idle_token = token
                name = self._input_name
                kind = self._input_kind or classify_input(name, self._endpoint_id, self._instance_id)
                self._input_kind = kind
                seconds = idle_seconds_for_input(name, self._endpoint_id, self._instance_id)
        if not arm:
            if held:
                logs.event("dictation: mic stays open while the dictate modifier is held")
            return
        logs.event(f"dictation: mic stays open for {seconds:.0f}s then releases ({kind}, {name or 'unknown input'})")
        timer = threading.Timer(seconds, self._close_if_idle, args=(token,))
        timer.daemon = True
        with self._lock:
            if self._modifier_held or self._phase != "idle" or self._idle_token != token or self._closed:
                return
            self._idle_timer = timer
        timer.start()

    def _close_if_idle(self, token):
        with self._lock:
            if self._closed or token != self._idle_token or self._phase != "idle" or self._modifier_held:
                if self._modifier_held:
                    logs.event("dictation: release skipped; dictate modifier is held")
                return
            stream = self._stream
            self._stream = None
            self._ring.clear()
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
            logs.event(f"dictation: microphone released after idle; input stream stopped and closed ({self._input_kind})")

    def _notify(self, message):
        logs.event("dictation: " + message)
        if self.on_notice:
            try:
                self.on_notice(message)
            except Exception:
                pass

    def shutdown(self):
        """Close the microphone and drop the capture. Do not transcribe or type."""
        self._cancel_idle_timer()
        self._cancel_model_unload()
        with self._lock:
            self._closed = True
            self._gen += 1
            self._capturing = False
            self._phase = "idle"
            self.recording = False
            self._frames = []
            stream = self._stream
            self._stream = None
            self._ring.clear()
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        logs.event("dictation: shutdown")
        self._state()

    def _finish(self, audio, gen):
        try:
            self._transcribe(audio, gen)
        except Exception as e:
            logs.event(f"dictation: transcribe failed: {e!r}")
        finally:
            with self._lock:
                if self._gen == gen and self._phase == "finalizing":
                    self._phase = "idle"
                    idle = True
                else:
                    idle = False
            self._arm_mic_idle()
            if idle:
                self._schedule_model_unload()

    def _chime_if_recording(self, kind, gen):
        with self._lock:
            if self._gen != gen or self._phase != "recording":
                logs.event(f"dictation: {kind} chime cancelled before playback")
                return
        self._chime(kind)

    def _chime(self, kind):
        chime_on = True if self.settings is None else coerce_bool(self.settings["chime"], True)
        if not chime_on or self.player is None:
            logs.event(f"dictation: {kind} chime requested but skipped")
            return None
        logs.event(f"dictation: {kind} chime requested")
        try:
            ok = self.player.play_chime(kind)
        except Exception as e:
            logs.event(f"dictation: {kind} chime started=False FAILED {e!r}")
            return False
        started = bool(ok)
        logs.event(f"dictation: {kind} chime started={started}")
        return started

    def _newer_tap(self, gen):
        with self._lock:
            return self._gen > gen

    def _transcribe(self, audio, gen):
        dur = len(audio) / SR
        skip = clip_should_skip(audio, SR)
        if skip and self._newer_tap(gen):
            logs.event(f"dictation: drop gen {gen} ({skip}; a newer tap superseded it)")
            return
        if skip:
            logs.event(f"dictation: {skip}, ignored")
            if skip != "too short":
                self._notify("SayTray didn't hear anything. If you were speaking, check the microphone and try again.")
            return
        if dur < _MIN_LIVE_S:
            logs.event("dictation: too short, ignored")
            return
        for _ in range(100):
            if self._model is not None:
                break
            time.sleep(0.1)
        if self._model is None:
            logs.event("dictation: no model")
            self._notify("Dictation isn't available yet. The speech model is still downloading, or the download failed. SayTray will keep trying.")
            return
        n_slices = max(1, int((dur + SEGMENT_S - 1e-9) // SEGMENT_S))
        logs.event(f"dictation: kept {dur:.2f}s with no duration cap; {n_slices} slices of <={SEGMENT_S:.0f}s")
        t0 = time.time()

        silent_slices = 0
        heard_slices = 0

        def transcribe_audio(samples):
            nonlocal silent_slices, heard_slices
            reason = clip_should_skip(samples, SR)
            if slice_is_silent(samples, SR) or reason:
                silent_slices += 1
                logs.event(f"dictation: slice {len(samples) / SR:.1f}s skipped ({reason or 'silence'})")
                return "", None, None, False
            heard_slices += 1
            audio_s = len(samples) / SR
            short = audio_s < _SHORT_VAD_S
            try:
                # A short noisy hold makes Whisper walk its temperature ladder and
                # invent text whose timestamps run past the audio. Those clips use
                # temperature 0 and the VAD filter. A long slice keeps VAD off so
                # the start of a multi-minute dictation is not cut, and it is not
                # conditioned on the previous window.
                kwargs = dict(
                    language="en", beam_size=1, vad_filter=short,
                    condition_on_previous_text=False, no_speech_threshold=0.6,
                )
                if short:
                    kwargs["temperature"] = 0.0
                segs, _ = self._model.transcribe(samples, **kwargs)
                kept = []
                for s in segs:
                    if segment_past_audio(getattr(s, "end", 0), audio_s):
                        logs.event(
                            f"dictation: drop segment ending at {float(getattr(s, 'end', 0) or 0):.1f}s "
                            f"past {audio_s:.1f}s of audio"
                        )
                        continue
                    if keep_whisper_segment(
                        getattr(s, "text", ""), getattr(s, "no_speech_prob", 0), getattr(s, "avg_logprob", 0)
                    ):
                        kept.append(s)
                segs = kept
            except Exception as e:
                logs.event(f"dictation: slice {len(samples) / SR:.1f}s failed: {e!r}")
                return "", None, None, True
            text = " ".join(s.text.strip() for s in segs).strip()
            first = float(segs[0].start) if segs else None
            last = float(segs[-1].end) if segs else None
            logs.event(
                f"dictation: request {len(samples) / SR:.1f}s -> {len(text)} chars "
                f"first {first if first is not None else '-'}s last {last if last is not None else '-'}s"
            )
            return text, first, last, False

        def on_resplit(audio_s, first, last):
            logs.event(
                f"dictation: slice {audio_s:.1f}s result did not cover it "
                f"(first {first} last {last}); splitting so the rest is kept"
            )

        # One model call at a time, and the paste happens before the next session's
        # transcript, so rapid holds stay in order.
        with self._transcribe_lock:
            with self._lock:
                if self._closed:
                    logs.event(f"dictation: drop transcript gen {gen} (shut down)")
                    return
            if clip_should_skip(audio, SR) and self._newer_tap(gen):
                logs.event(f"dictation: drop gen {gen} (short noise; a newer tap superseded it)")
                return
            text = stitch_audio(audio, SR, SEGMENT_S, transcribe_audio, on_resplit=on_resplit)
            logs.event(f"dictation: gen {gen} audio {dur:.2f}s transcript {len(text)} chars in {time.time() - t0:.1f}s")
            with self._lock:
                if self._closed:
                    logs.event(f"dictation: drop transcript gen {gen} (shut down)")
                    return
            if text:
                insert_dictation(text)
            elif silent_slices and not heard_slices:
                self._notify("SayTray didn't hear anything. If you were speaking, check the microphone and try again.")

    def _state(self):
        if self.on_state:
            try:
                self.on_state()
            except Exception:
                pass
