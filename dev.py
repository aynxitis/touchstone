#!/usr/bin/env python3
"""One command to run Touchstone locally: the landing page at / and the app at /app.

    python dev.py                 # http://127.0.0.1:8031/  -> landing
                                  # http://127.0.0.1:8031/app -> the app
    python dev.py --port 9000
    python dev.py --no-reload

It runs the same entry point as production (uvicorn app:app), with --reload so editing
app.py, static/ or landing/ shows up on the next page load. The first run creates .venv
and installs requirements.txt; afterwards it re-executes itself inside that venv, so you
never have to activate or know about it.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
DEFAULT_PORT = 8031


def venv_python() -> Path:
    """The .venv interpreter, created and populated on first run."""
    if VENV_PY.exists():
        return VENV_PY
    print("no .venv yet: creating it and installing requirements.txt (once)...")
    subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    subprocess.run([str(VENV_PY), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
                   check=True)
    subprocess.run([str(VENV_PY), "-m", "pip", "install", "--quiet", "-r",
                    str(ROOT / "requirements.txt")], check=True)
    return VENV_PY


def main() -> int:
    argv = sys.argv[1:]
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    port, host, reload = DEFAULT_PORT, "127.0.0.1", True
    args = iter(argv)
    for arg in args:
        if arg in ("--port", "-p"):
            port = int(next(args))
        elif arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg in ("--host",):
            host = next(args)
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]
        elif arg == "--no-reload":
            reload = False
        else:
            print(f"unknown option: {arg}\n", file=sys.stderr)
            print(__doc__, file=sys.stderr)
            return 2

    python = venv_python()
    if Path(sys.executable).resolve() != python.resolve():
        # Wrong interpreter (a bare `python dev.py`, or `npm run dev` via a stray python):
        # hand over to the venv one, which is where the dependencies live.
        return subprocess.run([str(python), str(Path(__file__).resolve()), *argv]).returncode

    env_file = ROOT / ".env"
    if not env_file.exists():
        print("no .env: starting with the default provider (groq). The example replay works "
              "without a key; real checks need GROQ_API_KEY or GEMINI_API_KEY - copy "
              ".env.example to .env and fill it in.\n")

    cmd = [str(python), "-m", "uvicorn", "app:app", "--host", host, "--port", str(port),
           "--workers", "1", "--no-proxy-headers"]
    if reload:
        cmd.append("--reload")

    print(f"Touchstone\n  landing  http://{host}:{port}/\n  app      http://{host}:{port}/app\n")
    sys.stdout.flush()
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
