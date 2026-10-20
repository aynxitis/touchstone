"""Runs the token-free test files; exits non-zero if any fails.

Run: .venv/bin/python run_tests.py
TOUCHSTONE_OFFLINE=1 skips the parts that need the internet (CI sets it): test_security.py's
DNS-rebinding, TLS, redirect-to-private and live IANA checks, and test_pdf.py's download of the
real ICO report. No test needs an API key or makes a model call.
"""
import os
import subprocess
import sys
import time

TESTS = ["test_parsing.py", "test_pdf.py", "test_sources.py", "test_checks.py", "test_security.py",
         "test_engine_golden.py"]

here = os.path.dirname(os.path.abspath(__file__))
failed = []
for name in TESTS:
    t0 = time.monotonic()
    code = subprocess.run([sys.executable, name], cwd=here).returncode
    print(f"{'ok  ' if code == 0 else 'FAIL'} {name} ({time.monotonic() - t0:.1f}s)", flush=True)
    if code:
        failed.append(name)
print(f"{len(TESTS) - len(failed)} of {len(TESTS)} test files passed" + (f"; failed: {', '.join(failed)}" if failed else ""))
sys.exit(1 if failed else 0)
