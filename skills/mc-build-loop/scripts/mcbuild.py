#!/usr/bin/env python3
"""mcbuild: build or smoke-test a mod and print a short diagnosis instead of a wall of Gradle log.

    mcbuild.py build                    # gradlew build, report compile errors
    mcbuild.py compile                  # gradlew compileJava only (fastest)
    mcbuild.py server [--timeout 300]   # boot a dedicated server, stop it once loaded
    mcbuild.py crash [path]             # summarize the newest crash report (or the given file)
    mcbuild.py log <file>               # diagnose any saved Gradle / game log

Exit code 0 = success, 1 = failure with diagnosis printed, 2 = could not run.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

MAX_ITEMS = 15

# ---------------------------------------------------------------- project


def find_root(start: Path) -> Path:
    for d in [start, *start.parents]:
        if (d / "gradlew").is_file() or (d / "gradlew.bat").is_file():
            return d
    sys.exit("mcbuild: no gradlew found here or above. Run inside a mod project.")


def gradlew(root: Path) -> list[str]:
    if os.name == "nt":
        return [str(root / "gradlew.bat")]
    return ["sh", str(root / "gradlew")]


def loader(root: Path) -> str:
    text = ""
    for n in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"):
        p = root / n
        if p.is_file():
            text += p.read_text(encoding="utf-8", errors="replace")
    if "fabric-loom" in text:
        return "fabric"
    if "net.neoforged.gradle" in text:
        return "neogradle"
    if "net.neoforged" in text:
        return "neoforge"
    return "unknown"


def server_dir(root: Path) -> Path:
    # Loom and ModDevGradle start every run in run/; the older NeoGradle uses runs/<run name>
    return root / ("runs/server" if loader(root) == "neogradle" else "run")


# ---------------------------------------------------------------- diagnosis

JAVAC = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[^:]+\.java):(?P<line>\d+): (?:error|Fehler): (?P<msg>.+)$")
MIXIN_PATTERNS = [
    (re.compile(r"InvalidInjectionException: (.+)"), "mixin injection invalid"),
    (re.compile(r"InjectionError: (.+)"), "mixin injection error"),
    (re.compile(r"Critical injection failure: (.+)"), "mixin target not found"),
    (re.compile(r"Mixin apply for mod \S+ failed (.+)"), "mixin apply failed"),
    (re.compile(r"Mixin transformation of (\S+) failed"), "mixin transformation failed"),
    (re.compile(r"InvalidMixinException: (.+)"), "invalid mixin class"),
    (re.compile(r"@Shadow (?:method|field) (.+) was not located"), "shadow member missing"),
]
LOADER_PATTERNS = [
    (re.compile(r"Incompatible mods? found!?(.*)"), "incompatible mods"),
    (re.compile(r"requires (?:version|any version) .+ of (\S+), which is missing"), "missing dependency"),
    (re.compile(r"Mod (\S+) requires .+"), "dependency problem"),
    (re.compile(r"ModLoadingException: (.+)"), "mod loading failed"),
    (re.compile(r"Missing or unsupported mandatory dependencies:(.*)"), "missing dependency"),
    (re.compile(r"Failed to load registry (.+)|Registry .+ is missing (.+)"), "registry problem"),
    (re.compile(r"Couldn't parse data file (\S+)|Failed to parse (\S+\.json)"), "bad data/asset json"),
]
JAVA_PATTERNS = [
    re.compile(r"JAVA_HOME is not set and no 'java' command could be found.*"),
    re.compile(r"JAVA_HOME is set to an invalid directory.*"),
    re.compile(r"Unsupported class file major version \d+"),
    re.compile(r"Dependency requires at least JVM runtime version \d+.*"),
]
GRADLE_FAIL = re.compile(r"^\* What went wrong:\s*$")
LOG_PREFIX = re.compile(r"^\[[\d:.]+\] \[[^\]]+\](?: \([^)]+\))?:? ")


def diagnose(text: str, root: Path | None = None) -> list[str]:
    lines = text.splitlines()
    out: list[str] = []

    # 1. compiler errors, grouped by message so 40 identical "cannot find symbol" collapse
    errs = []
    seen_err = set()
    for i, line in enumerate(lines):
        m = JAVAC.match(line.strip())
        if not m or (m.group("file"), m.group("line"), m.group("msg")) in seen_err:
            continue  # Gradle repeats compiler output in its failure summary
        seen_err.add((m.group("file"), m.group("line"), m.group("msg")))
        detail = []
        for nxt in lines[i + 1:i + 6]:
            s = nxt.strip()
            if s.startswith(("symbol:", "location:", "required:", "found:", "reason:")):
                detail.append(s)
        f = m.group("file")
        if root:
            try:
                f = str(Path(f).resolve().relative_to(root))
            except ValueError:
                pass
        errs.append((f, int(m.group("line")), m.group("msg"), detail))
    if errs:
        out.append(f"COMPILE ERRORS: {len(errs)}")
        for f, ln, msg, detail in errs[:MAX_ITEMS]:
            out.append(f"  {f}:{ln}: {msg}" + (f"  [{'; '.join(detail)}]" if detail else ""))
        if len(errs) > MAX_ITEMS:
            out.append(f"  ... {len(errs) - MAX_ITEMS} more")
        syms = sorted({d.split(":", 1)[1].strip() for *_, ds in errs for d in ds if d.startswith("symbol:")})
        if syms:
            out.append("  Unknown symbols (look each up with mc-source-lookup): " + ", ".join(syms[:20]))

    # 2. mixin and loader failures
    seen = set()
    for line in lines:
        for pats, label in ((MIXIN_PATTERNS, "MIXIN"), (LOADER_PATTERNS, "LOADER")):
            hit = next(((rx, kind) for rx, kind in pats if rx.search(line)), None)
            if not hit:
                continue
            msg = LOG_PREFIX.sub("", line.strip())
            # the same failure is logged several times with different wrappers; key on its core
            core = re.search(r"(Critical injection failure: .+?)(?: No refMap| Using refmap| \[|$)", msg)
            msg = core.group(1) if core else re.sub(r"^(Caused by: )?[\w.$]+: ", "", msg)
            if msg[:160] not in seen:
                seen.add(msg[:160])
                out.append(f"{label}: {hit[1]}: {msg[:300]}")
            break
    for t in sorted(set(re.findall(r"could not find any targets matching '([^']+)' in ([\w/$]+)", text))):
        name = t[0].split("(")[0].split(":")[0].lstrip("L").split(";")[-1]
        out.append(f"  -> check the target: mcsrc.py method {t[1].replace('/', '.')}#{name}")
    # 3. exceptions with the first frames that are not JDK / loader internals;
    #    mixin lines above already carry the message, keep only the frames for those
    for item in exception_summary(lines):
        if item.startswith(("EXCEPTION", "CAUSE")) and any(item.split(": ", 2)[-1][:80] in o for o in out):
            out.append(item.split(": ", 2)[0] + ": (see above)")
        else:
            out.append(item)

    # 4. Gradle could not start or runs on a JDK it cannot use
    if not out:
        for rx in JAVA_PATTERNS:
            m = next((m for m in map(rx.search, lines) if m), None)
            if m:
                out.append(f"JAVA: {m.group(0).strip()}")
                out.append("  -> point JAVA_HOME at a JDK that both Gradle and the project accept, then retry "
                           "(see 'Java version' in the mc-build-loop skill)")
                break

    # 5. Gradle's own "What went wrong" block when nothing above explains it
    if not out:
        for i, line in enumerate(lines):
            if GRADLE_FAIL.match(line):
                block = [s for s in lines[i + 1:i + 8] if s.strip() and not s.startswith("* Try")]
                out.append("GRADLE: " + " | ".join(s.strip() for s in block))
                break
    return out


INTERNAL = ("java.", "jdk.", "sun.", "org.spongepowered.", "net.fabricmc.loader.", "cpw.mods.",
            "net.neoforged.fml.", "net.neoforged.neoforgespi.", "com.google.", "org.gradle.", "io.netty.")


def exception_summary(lines: list[str]) -> list[str]:
    out = []
    i = 0
    shown = 0
    seen: set[tuple] = set()
    while i < len(lines) and shown < 3:
        line = LOG_PREFIX.sub("", lines[i].strip())
        m = re.match(r"(?:Caused by: )?([\w.$]+(?:Exception|Error))(?::\s*(.*))?$", line)
        if m and i + 1 < len(lines) and lines[i + 1].strip().startswith("at "):
            frames = []
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith(("at ", "...")):
                s = lines[j].strip()
                j += 1
                if not s.startswith("at "):
                    continue  # "... 18 more"
                fr = re.sub(r"\s+~?\[[^\]]*\]$", "", s[3:])  # drop "[jar:version]"
                fr = re.sub(r"^[\w.-]+/", "", fr)  # drop "knot/" / module prefixes
                if not fr.startswith(INTERNAL):
                    frames.append(fr)
            # wrappers re-throw with a new message but the same frames
            key = tuple(frames[:4]) if frames else (m.group(1), m.group(2))
            i = j
            if key in seen:
                continue  # same trace logged twice (log + crash report)
            seen.add(key)
            label = "CAUSE" if line.startswith("Caused by") else "EXCEPTION"
            out.append(f"{label}: {m.group(1)}: {(m.group(2) or '')[:240]}")
            for fr in frames[:4]:
                out.append(f"    at {fr}")
            shown += 1
            continue
        i += 1
    return out


def crash_report(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    out = [f"CRASH REPORT: {path}"]
    m = re.search(r"^Description: (.+)$", text, re.M)
    if m:
        out.append(f"  description: {m.group(1)}")
    m = re.search(r"Suspected Mods?: (.+)", text)
    if m:
        out.append(f"  suspected mods: {m.group(1).strip()}")
    out += diagnose(text.split("A detailed walkthrough of the error")[0])
    return out


def newest_crash(root: Path) -> Path | None:
    cands = []
    for run in ("run", "runs/client", "runs/server", "run/server", "runs"):
        cands += list((root / run).glob("crash-reports/crash-*.txt"))
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


# ---------------------------------------------------------------- commands


def run_gradle(root: Path, tasks: list[str]) -> tuple[int, str]:
    cmd = gradlew(root) + tasks + ["--console=plain"]
    print(f"$ {' '.join(['gradlew'] + tasks)}", file=sys.stderr)
    p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout + "\n" + p.stderr


def report(ok: bool, items: list[str], ok_msg: str, log: str = "") -> int:
    if ok and not [i for i in items if i.startswith(("COMPILE", "MIXIN", "EXCEPTION"))]:
        print(ok_msg)
        return 0
    print("FAILED")
    if items:
        print("\n".join(items))
    else:
        tail = [s for s in log.splitlines() if s.strip()][-12:]
        print("No known pattern matched." + (" Last log lines:\n" + "\n".join(tail) if tail else ""))
    return 1


def cmd_build(root: Path, args, tasks: list[str], ok_msg: str) -> int:
    code, log = run_gradle(root, tasks)
    if args.raw:
        print("\n".join(log.splitlines()[-80:]))
    return report(code == 0, diagnose(log, root) if code else [], ok_msg, log)


def cmd_server(root: Path, args) -> int:
    ld = loader(root)
    run_dir = server_dir(root)
    eula = run_dir / "eula.txt"
    if not (eula.is_file() and "eula=true" in eula.read_text(errors="replace")):
        if not args.accept_eula:
            print("BLOCKED: the dedicated server needs the Minecraft EULA accepted "
                  "(https://aka.ms/MinecraftEULA). Ask the user, then re-run with --accept-eula.")
            return 2
        run_dir.mkdir(parents=True, exist_ok=True)
        eula.write_text("eula=true\n")
    started = time.time()
    cmd = gradlew(root) + ["runServer", "--console=plain"]
    if ld == "fabric":
        cmd.append("--args=nogui")
    print(f"$ gradlew runServer (timeout {args.timeout}s)", file=sys.stderr)
    p = subprocess.Popen(cmd, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    log: list[str] = []
    done = threading.Event()
    loaded = threading.Event()

    def pump() -> None:
        assert p.stdout
        for line in p.stdout:
            log.append(line.rstrip("\n"))
            if re.search(r"Done \(\d+[.,]\d+s\)!", line):
                loaded.set()
        done.set()

    threading.Thread(target=pump, daemon=True).start()
    while not done.is_set() and not loaded.is_set() and time.time() - started < args.timeout:
        time.sleep(0.5)
    if loaded.is_set():
        try:
            assert p.stdin
            p.stdin.write("stop\n")
            p.stdin.flush()
        except OSError:
            pass
    if not done.wait(60):
        p.kill()
    text = "\n".join(log)
    if args.raw:
        print("\n".join(log[-80:]))
    if loaded.is_set():
        items = diagnose(text, root)
        items = [i for i in items if i.startswith(("MIXIN", "LOADER"))]  # loaded fine; only warn on these
        print(f"SERVER OK: world loaded in {time.time() - started:.0f}s and stopped cleanly.")
        if items:
            print("Warnings seen during boot:\n" + "\n".join(items))
        return 0
    items = diagnose(text, root)
    crash = newest_crash(root)
    if crash and crash.stat().st_mtime >= started:
        items += crash_report(crash)
    if not done.is_set():
        items.insert(0, f"TIMEOUT: server did not finish loading within {args.timeout}s")
    return report(False, items, "", text)


def main() -> int:
    ap = argparse.ArgumentParser(prog="mcbuild", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=".")
    ap.add_argument("--raw", action="store_true", help="also print the last 80 log lines")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("compile")
    p = sub.add_parser("server")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--accept-eula", action="store_true", help="only after the user agreed to the Minecraft EULA")
    p = sub.add_parser("crash")
    p.add_argument("path", nargs="?")
    p = sub.add_parser("log")
    p.add_argument("path")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if args.cmd == "log":
        items = diagnose(Path(args.path).read_text(encoding="utf-8", errors="replace"))
        print("\n".join(items) if items else "No known failure pattern in this log.")
        return 1 if items else 0
    if args.cmd == "crash" and args.path:
        print("\n".join(crash_report(Path(args.path))))
        return 1
    root = find_root(Path(args.project).resolve())
    if args.cmd == "build":
        return cmd_build(root, args, ["build"], "BUILD OK")
    if args.cmd == "compile":
        return cmd_build(root, args, ["compileJava"], "COMPILE OK")
    if args.cmd == "server":
        return cmd_server(root, args)
    crash = Path(args.path) if args.path else newest_crash(root)
    if not crash:
        print("No crash reports found under run/ or runs/.")
        return 0
    print("\n".join(crash_report(crash)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
