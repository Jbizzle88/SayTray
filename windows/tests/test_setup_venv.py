"""setup_piper.sh recreates a venv whose python or pip script cannot run.

Jon hit this after the venv moved out of ~/Library/Application Support/SpeakBar:
pip's shebang still pointed at that path, the script printed an error, and `|| true`
let setup exit 0 without repairing it.

The recreate checks source that bash script. A stock Windows install has no bash,
so those checks skip with a warning instead of raising WinError 2. Python itself
is this interpreter (sys.executable), then the py launcher, then python on PATH.
"""
import os, shutil, stat, subprocess, sys, tempfile, textwrap

passes = failures = 0

def check(cond, msg):
    global passes, failures
    if cond:
        passes += 1
    else:
        failures += 1
        print("FAIL:", msg)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(ROOT, "macos", "support", "setup_piper.sh")
INSTALL = os.path.join(ROOT, "windows", "install.ps1")

setup = open(SCRIPT, encoding="utf-8").read()
install = open(INSTALL, encoding="utf-8").read()
check(all("|| true" not in line for line in setup.splitlines() if "pip" in line and not line.strip().startswith("#")),
      "setup_piper.sh no longer swallows pip failures")
check("Piper venv is broken" in setup, "setup_piper.sh explains a broken venv")
check(" -m pip " in setup or "-m pip " in setup, "setup_piper.sh installs with python -m pip")
check("Piper venv is broken" in install, "install.ps1 explains a broken venv")
check("Test-VenvHealthy" in install, "install.ps1 probes the venv")
check("-m pip" in install, "install.ps1 installs with python -m pip")
check("incomplete download" in setup, "setup_piper.sh rejects a short download")
check("sizeBytes" in setup, "setup_piper.sh passes the catalog size")
check("incomplete download" in install, "install.ps1 rejects a short download")
check("$expect" in install and "sizeBytes" in install, "install.ps1 compares file length to sizeBytes")
check("sha256" in setup and "checksum mismatch" in setup, "setup_piper.sh checks sha256")
check("import piper, onnxruntime" in setup, "setup_piper.sh recreates a venv that cannot import Piper")
check("import piper, onnxruntime" in install, "install.ps1 recreates a venv that cannot import Piper")
check("Get-FileHash" in install and "checksum mismatch" in install, "install.ps1 checks sha256")
check('"$out.sha256"' in setup, "setup_piper.sh writes the hash marker")
check("Write-VoiceMarker" in install and ".sha256" in install, "install.ps1 writes the hash marker")
check("WhisperModel" in install, "install.ps1 prefetches the dictation model")
check("3.10" in setup and "3.10" in install, "installers require Python 3.10+")

def resolve_tool(name):
    """Find bash, or a Python interpreter, on this machine.

    python, python3, and py prefer this process (sys.executable). py is also
    accepted from the Windows launcher. Anything else is looked up on PATH.
    A missing tool returns None so the caller can skip instead of crashing.
    """
    if name in ("python", "python3", "py"):
        if name == "py":
            found = shutil.which("py")
            if found:
                return found
        if sys.executable and os.path.isfile(sys.executable):
            return sys.executable
        for candidate in ("py", "python", "python3"):
            found = shutil.which(candidate)
            if found:
                return found
        return None
    return shutil.which(name)

check(resolve_tool("no-such-saytray-tool") is None, "a missing tool is a skip signal")
resolved_py = resolve_tool("python3")
check(bool(resolved_py) and os.path.isfile(resolved_py), f"python3 resolves via this interpreter or the py launcher: {resolved_py}")

def write(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(path, stat.S_IRWXU)

BASH = resolve_tool("bash")

def ensure(piper, python3):
    if not BASH:
        return None
    env = os.environ.copy()
    env["SAYTRAY_SETUP_LIBRARY"] = "1"
    try:
        return subprocess.run(
            [BASH, "-c", 'source "$1" && ensure_piper_venv "$2" "$3"', "bash", SCRIPT, piper, python3],
            env=env, capture_output=True, text=True)
    except FileNotFoundError:
        print("WARNING: bash could not be started. Skipping this venv check.")
        return None

def healthy_case():
    # Healthy venv: pip *script* answers --version, and installs go through python -m pip.
    # python3 must not be asked to recreate it.
    with tempfile.TemporaryDirectory() as tmp:
        piper = os.path.join(tmp, "Application Support", "SayTray", "piper")
        venv = os.path.join(piper, "venv")
        log = os.path.join(tmp, "python.log")
        pip_log = os.path.join(tmp, "pip.log")
        calls = os.path.join(tmp, "python3.calls")
        write(os.path.join(venv, "bin", "python"), "#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$SAYTRAY_PY_LOG\"\nexit 0\n")
        write(os.path.join(venv, "bin", "pip"), "#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$SAYTRAY_PIP_LOG\"\nexit 0\n")
        write(os.path.join(tmp, "python3"), "#!/bin/bash\nprintf '%s\\n' \"$*\" >> \"$SAYTRAY_PY3_CALLS\"\nexit 99\n")
        env = os.environ.copy()
        env.update(SAYTRAY_SETUP_LIBRARY="1", SAYTRAY_PY_LOG=log, SAYTRAY_PIP_LOG=pip_log, SAYTRAY_PY3_CALLS=calls)
        try:
            r = subprocess.run(
                [BASH, "-c", 'source "$1" && ensure_piper_venv "$2" "$3"', "bash", SCRIPT, piper, os.path.join(tmp, "python3")],
                env=env, capture_output=True, text=True)
        except FileNotFoundError:
            print("WARNING: bash could not be started. Skipping the healthy-venv check.")
            return
        py_log = open(log, encoding="utf-8").read() if os.path.exists(log) else ""
        pip_log_text = open(pip_log, encoding="utf-8").read() if os.path.exists(pip_log) else ""
        check(r.returncode == 0, f"healthy venv exits 0 ({r.returncode}) {r.stderr}")
        check("already present" in r.stdout, f"healthy venv kept: {r.stdout}")
        check(not os.path.exists(calls), "healthy venv was not recreated")
        check("-m pip install" in py_log, f"install used python -m pip: {py_log!r}")
        check("install" not in pip_log_text, f"pip script was not used to install: {pip_log_text!r}")

def broken_case(kind):
    with tempfile.TemporaryDirectory() as tmp:
        piper = os.path.join(tmp, "Application Support", "SayTray", "piper")
        venv = os.path.join(piper, "venv")
        marker = os.path.join(tmp, "recreated")
        # Jon's failure: pip shebang still points at the old SpeakBar venv. python may or may not run.
        if kind == "pip":
            write(os.path.join(venv, "bin", "python"), "#!/bin/bash\nexit 0\n")
        else:
            write(os.path.join(venv, "bin", "python"), "#!/no/such/SpeakBar/venv/bin/python\necho dead >&2\nexit 1\n")
        write(os.path.join(venv, "bin", "pip"), "#!/no/such/SpeakBar/venv/bin/python\necho bad pip shebang >&2\nexit 1\n")
        py3 = os.path.join(tmp, "python3")
        write(py3, textwrap.dedent(f"""\
            #!/bin/bash
            dest=""
            for a in "$@"; do dest="$a"; done
            if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
              mkdir -p "$dest/bin"
              cat > "$dest/bin/python" << 'PY'
            #!/bin/bash
            exit 0
            PY
              cp "$dest/bin/python" "$dest/bin/pip"
              chmod +x "$dest/bin/python" "$dest/bin/pip"
              echo ok > "{marker}"
              exit 0
            fi
            echo "unexpected python3 $*" >&2
            exit 1
        """))
        r = ensure(piper, py3)
        if r is None:
            print(f"WARNING: skipped the {kind} venv check because bash could not be started.")
            return
        check(r.returncode == 0, f"{kind} broken venv exits 0 ({r.returncode}) stderr={r.stderr!r}")
        check("Recreating" in r.stdout, f"{kind} broken venv recreates: {r.stdout!r} {r.stderr!r}")
        check(os.path.exists(marker), f"{kind} broken venv called python -m venv")
        new_pip = os.path.join(venv, "bin", "pip")
        first = open(new_pip, encoding="utf-8").readline() if os.path.exists(new_pip) else ""
        check("SpeakBar" not in first, f"{kind} new pip shebang is not the old path: {first!r}")

def broken_import():
    with tempfile.TemporaryDirectory() as tmp:
        piper = os.path.join(tmp, "Application Support", "SayTray", "piper")
        venv = os.path.join(piper, "venv")
        marker = os.path.join(tmp, "recreated")
        write(os.path.join(venv, "bin", "python"), textwrap.dedent("""\
            #!/bin/bash
            case "$*" in
              *piper*) exit 1 ;;
            esac
            exit 0
        """))
        write(os.path.join(venv, "bin", "pip"), "#!/bin/bash\nexit 0\n")
        py3 = os.path.join(tmp, "python3")
        write(py3, textwrap.dedent(f"""\
            #!/bin/bash
            dest=""
            for a in "$@"; do dest="$a"; done
            if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
              mkdir -p "$dest/bin"
              cat > "$dest/bin/python" << 'PY'
            #!/bin/bash
            exit 0
            PY
              cp "$dest/bin/python" "$dest/bin/pip"
              chmod +x "$dest/bin/python" "$dest/bin/pip"
              echo ok > "{marker}"
              exit 0
            fi
            echo "unexpected python3 $*" >&2
            exit 1
        """))
        r = ensure(piper, py3)
        if r is None:
            print("WARNING: skipped the import-broken venv check because bash could not be started.")
            return
        check(r.returncode == 0, f"import-broken venv exits 0 ({r.returncode}) stderr={r.stderr!r}")
        check("Recreating" in r.stdout, f"import-broken venv recreates: {r.stdout!r} {r.stderr!r}")
        check(os.path.exists(marker), "import-broken venv called python -m venv")

def run_bash_cases():
    """Source setup_piper.sh. Skipped, with one warning, when bash is not installed."""
    if not BASH:
        print("WARNING: bash was not found, so the venv recreate checks were skipped. "
              "Those checks source setup_piper.sh. The file checks above still ran. "
              f"Python for this suite is {resolved_py or sys.executable}.")
        return
    healthy_case()
    broken_case("pip")
    broken_case("python")
    broken_import()

run_bash_cases()

print(f"Venv setup tests: {passes} passed, {failures} failed")
sys.exit(0 if failures == 0 else 1)
