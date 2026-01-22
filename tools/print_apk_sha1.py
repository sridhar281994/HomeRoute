#!/usr/bin/env python3
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


SHA1_RE = re.compile(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){19})")


def _pick_apksigner() -> str | None:
    # 1) Explicit env var
    env = os.environ.get("APKSIGNER") or ""
    if env and Path(env).exists():
        return env

    # 2) PATH
    p = shutil.which("apksigner")
    if p:
        return p

    # 3) Android SDK build-tools
    sdk = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME") or ""
    if not sdk:
        return None
    cand = sorted(glob.glob(os.path.join(sdk, "build-tools", "*", "apksigner")))
    return cand[-1] if cand else None


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)


def _sha1_from_apksigner(apk_path: str) -> str | None:
    apksigner = _pick_apksigner()
    if not apksigner:
        return None
    out = _run([apksigner, "verify", "--print-certs", apk_path])
    # apksigner outputs e.g. "Signer #1 certificate SHA-1 digest: XX:YY:..."
    for line in out.splitlines():
        if "SHA-1 digest" not in line:
            continue
        m = SHA1_RE.search(line)
        if m:
            return m.group(1).upper()
    return None


def _sha1_from_keytool(apk_path: str) -> str | None:
    keytool = shutil.which("keytool")
    if not keytool:
        return None
    out = _run([keytool, "-printcert", "-jarfile", apk_path])
    # keytool outputs e.g. "SHA1: XX:YY:..."
    for line in out.splitlines():
        if "SHA1" not in line.upper():
            continue
        m = SHA1_RE.search(line)
        if m:
            return m.group(1).upper()
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in {"-h", "--help"}:
        print("Usage: print_apk_sha1.py <path/to/app.apk>", file=sys.stderr)
        return 2

    apk = argv[1]
    if not os.path.isfile(apk):
        print(f"APK not found: {apk}", file=sys.stderr)
        return 2

    sha1 = _sha1_from_apksigner(apk) or _sha1_from_keytool(apk)
    if not sha1:
        print("Could not extract SHA-1 from APK (need apksigner or keytool).", file=sys.stderr)
        return 1

    print(sha1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

