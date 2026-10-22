"""Resolve the Windows pins for each Python the installer accepts.

Python 3.10 and 3.11 do not have the newest numpy and pillow wheels. The
requirements file uses markers so `pip install` still works. This downloads
win_amd64 wheels and does not install them.
"""
import os, subprocess, sys, tempfile

try:
    from packaging.requirements import Requirement
except ImportError:
    Requirement = None

passes = failures = 0

def check(cond, msg):
    global passes, failures
    if cond:
        passes += 1
    else:
        failures += 1
        print("FAIL:", msg)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REQ = os.path.join(ROOT, "windows", "requirements.txt")
text = open(REQ, encoding="utf-8").read()
for line in (
    'numpy==2.2.6; python_version < "3.11"',
    'numpy==2.4.6; python_version == "3.11"',
    'numpy==2.5.4; python_version >= "3.12"',
    'pillow==12.3.0; python_version < "3.11"',
    'pillow==13.0.0; python_version >= "3.11"',
):
    check(line in text, f"requirements include {line}")

def _for_python(version):
    """Keep the lines whose markers match this Python. pip's --python-version flag
    selects wheels, but it still evaluates markers with the interpreter that is running.
    """
    kept = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if Requirement is None or ";" not in line:
            kept.append(line)
            continue
        req = Requirement(line)
        if req.marker is None or req.marker.evaluate({"python_version": version}):
            kept.append(line)
    return kept

for version in ("3.10", "3.11", "3.12"):
    selected = _for_python(version)
    if version == "3.10":
        check(any(line.startswith("numpy==2.2.6") for line in selected), "Python 3.10 selects numpy 2.2.6")
        check(any(line.startswith("pillow==12.3.0") for line in selected), "Python 3.10 selects pillow 12.3.0")
        check(not any("numpy==2.5.4" in line for line in selected), "Python 3.10 does not select numpy 2.5.4")
    elif version == "3.11":
        check(any(line.startswith("numpy==2.4.6") for line in selected), "Python 3.11 selects numpy 2.4.6")
        check(any(line.startswith("pillow==13.0.0") for line in selected), "Python 3.11 selects pillow 13")
    else:
        check(any(line.startswith("numpy==2.5.4") for line in selected), "Python 3.12 selects numpy 2.5.4")
        check(any(line.startswith("pillow==13.0.0") for line in selected), "Python 3.12 selects pillow 13")
    with tempfile.TemporaryDirectory() as dest:
        req_path = os.path.join(dest, "requirements.txt")
        with open(req_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(selected) + "\n")
        wheels = os.path.join(dest, "wheels")
        os.makedirs(wheels)
        cmd = [
            sys.executable, "-m", "pip", "download",
            "-r", req_path,
            "--only-binary=:all:",
            "--platform", "win_amd64",
            "--python-version", version,
            "--dest", wheels,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        names = sorted(os.listdir(wheels))
        check(proc.returncode == 0 and names, f"Python {version} resolves win_amd64 wheels ({proc.returncode}, {len(names)} files)")
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-8:]
            print("\n".join(tail))

print(f"requirement wheel tests: {passes} passed, {failures} failed")
sys.exit(0 if failures == 0 else 1)
