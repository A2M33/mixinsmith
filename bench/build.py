#!/usr/bin/env python3
"""Benchmark build wrapper: run one Gradle task, log the attempt, print the raw log tail.

Both benchmark arms build only through this script, so every attempt is counted the same way.
It prints raw Gradle output (no mixinsmith diagnosis) to keep the baseline arm honest.

    python build.py compile      # gradlew compileJava
    python build.py build        # gradlew build
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Gradle output on a cp1252 console
except Exception:
    pass
task = {"compile": "compileJava", "build": "build"}[sys.argv[1] if len(sys.argv) > 1 else "compile"]
root = Path(os.environ.get("BENCH_PROJECT", ".")).resolve()
env = dict(os.environ)
java_home = os.environ.get("BENCH_JAVA_HOME")
if not java_home and (root / "bench-env.json").is_file():
    java_home = json.loads((root / "bench-env.json").read_text(encoding="utf-8")).get("java_home")
if java_home:
    env["JAVA_HOME"] = java_home
    env["PATH"] = str(Path(env["JAVA_HOME"]) / "bin") + os.pathsep + env.get("PATH", "")
gradlew = [str(root / "gradlew.bat")] if os.name == "nt" else ["sh", str(root / "gradlew")]
t = time.time()
p = subprocess.run(gradlew + [task, "--console=plain", "-q"], cwd=root, env=env,
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
with open(root / "bench-attempts.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps({"task": task, "ok": p.returncode == 0, "seconds": round(time.time() - t)}) + "\n")
(root / "bench-last-build.log").write_text(p.stdout + "\n" + p.stderr, encoding="utf-8")
out = (p.stdout + p.stderr).strip().splitlines()
print("\n".join(out[-60:]))
print("BUILD SUCCESSFUL" if p.returncode == 0 else "BUILD FAILED")
sys.exit(p.returncode)
