"""setup_piper.sh recreates a venv whose python or pip script cannot run.

Jon hit this after the venv moved out of ~/Library/Application Support/SpeakBar:
pip's shebang still pointed at that path, the script printed an error, and `|| true`
let setup exit 0 without repairing it.
"""
import os, stat, subprocess, sys, tempfile, textwrap

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

def write(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(path, stat.S_IRWXU)

def ensure(piper, python3):
    env = os.environ.copy()
    env["SAYTRAY_SETUP_LIBRARY"] = "1"
    return subprocess.run(
        ["bash", "-c", 'source "$1" && ensure_piper_venv "$2" "$3"', "bash", SCRIPT, piper, python3],
        env=env, capture_output=True, text=True)

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
    r = subprocess.run(
        ["bash", "-c", 'source "$1" && ensure_piper_venv "$2" "$3"', "bash", SCRIPT, piper, os.path.join(tmp, "python3")],
        env=env, capture_output=True, text=True)
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
        check(r.returncode == 0, f"{kind} broken venv exits 0 ({r.returncode}) stderr={r.stderr!r}")
        check("Recreating" in r.stdout, f"{kind} broken venv recreates: {r.stdout!r} {r.stderr!r}")
        check(os.path.exists(marker), f"{kind} broken venv called python -m venv")
        new_pip = os.path.join(venv, "bin", "pip")
        first = open(new_pip, encoding="utf-8").readline() if os.path.exists(new_pip) else ""
        check("SpeakBar" not in first, f"{kind} new pip shebang is not the old path: {first!r}")

broken_case("pip")
broken_case("python")

print(f"Venv setup tests: {passes} passed, {failures} failed")
sys.exit(0 if failures == 0 else 1)
