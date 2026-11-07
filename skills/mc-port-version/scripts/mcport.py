#!/usr/bin/env python3
"""mcport: list what a Minecraft version bump renames or removes, and where your mod uses it.

Intermediary names (class_1309, method_5643) stay the same across versions, so joining two versions'
mappings on them yields exact renames for Yarn and Mojang names alike.

    mcport.py --from 1.20.4 --to 1.21.1                 # scan ./src with the project's mappings
    mcport.py --from 1.20.4 --to 1.21.1 --ns mojang     # force a mappings set
    mcport.py --from 1.20.4 --to 1.21.1 --apply-imports # also rewrite renamed imports in place
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "mc-source-lookup" / "scripts"))

import mappings  # noqa: E402
import mcsrc  # noqa: E402

IDENT = re.compile(r"\b[A-Za-z_$][\w$]*\b")
IMPORT = re.compile(r"^(\s*import\s+(?:static\s+)?)([\w.$]+)(\s*;)", re.M)


def dotted(internal: str | None) -> str | None:
    return internal.replace("/", ".").replace("$", ".") if internal else None


def simple(internal: str | None) -> str:
    return (internal or "").rsplit("/", 1)[-1].rsplit("$", 1)[-1]


def diff(old: dict, new: dict, ns: str) -> dict:
    oc = {c["intermediary"]: c for c in old["classes"] if c.get("intermediary")}
    nc = {c["intermediary"]: c for c in new["classes"] if c.get("intermediary")}
    om = {(m["kind"], m["intermediary"]): m for m in old["members"] if m.get("intermediary")}
    nm = {(m["kind"], m["intermediary"]): m for m in new["members"] if m.get("intermediary")}
    new_cls_names = {c.get(ns) for c in nc.values()}
    new_by_off = {c["official"]: c for c in new["classes"]}
    new_mem_names = {m.get(ns) for m in nm.values()}

    classes, members, removed_cls, removed_mem = {}, {}, set(), set()
    for k, c in oc.items():
        a = c.get(ns)
        if not a or re.search(r"\$\d+$", a):  # anonymous classes come and go
            continue
        if k in nc:
            b = nc[k].get(ns)
            if b and b != a:
                classes[a] = b
        elif a not in new_cls_names:
            removed_cls.add(a)
    for k, m in om.items():
        a = m.get(ns)
        if not a or a.startswith(("method_", "field_", "comp_", "<")):
            continue
        if k in nm:
            b = nm[k].get(ns)
            if b and b != a:
                owner = new_by_off.get(nm[k]["owner"], {}).get(ns)
                members.setdefault(a, set()).add((b, owner))
        elif a not in new_mem_names:
            removed_mem.add(a)
    # a member name that still exists elsewhere in the new version is ambiguous: report, never auto-fix
    for a in list(members):
        if a in new_mem_names:
            members[a] = {(b, o, "still exists elsewhere") for b, o in members[a]}
    return {"classes": classes, "members": members, "removed_classes": removed_cls, "removed_members": removed_mem}


def scan(src: Path, d: dict, apply_imports: bool, show_all: bool = False) -> int:
    by_full = {dotted(a): dotted(b) for a, b in d["classes"].items()}
    by_simple: dict[str, set] = {}
    for a, b in d["classes"].items():
        if simple(a) != simple(b):
            by_simple.setdefault(simple(a), set()).add(simple(b))
    removed_simple = {simple(c) for c in d["removed_classes"]}
    hits = 0
    for f in sorted(src.rglob("*.java")):
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = f.relative_to(src.parent) if src.parent in f.parents else f
        out_lines = []

        def fix_import(m: re.Match) -> str:
            name = m.group(2)
            target = by_full.get(name)
            if not target:
                return m.group(0)
            return m.group(1) + target + m.group(3)

        if apply_imports:
            new_text = IMPORT.sub(fix_import, text)
            if new_text != text:
                f.write_text(new_text, encoding="utf-8")
                out_lines.append("  imports rewritten")
                text = new_text
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith(("//", "*", "/*")):
                continue
            im = IMPORT.match(line)
            if im:
                name = im.group(2)
                if name in by_full:
                    out_lines.append(f"  {i}: import {name} -> {by_full[name]}")
                elif dotted_removed(name, d):
                    out_lines.append(f"  {i}: import {name} -> REMOVED in target version")
                continue
            notes = []
            for tok in set(IDENT.findall(line)):
                if tok in by_simple:
                    notes.append(f"class {tok} -> {', '.join(sorted(by_simple[tok]))}")
                elif tok in removed_simple and tok[:1].isupper():
                    notes.append(f"class {tok} REMOVED")
                if re.search(rf"[.:]\s*{re.escape(tok)}\s*\(|\.{re.escape(tok)}\b", line) and tok in d["members"]:
                    cands = d["members"][tok]
                    ambiguous = any(len(x) > 2 for x in cands)
                    if ambiguous and not show_all:
                        scan.hidden += 1
                    else:
                        opts = sorted({f"{simple(x[1])}#{x[0]}" for x in cands})
                        notes.append(f"{tok} -> {', '.join(opts[:4])}"
                                     + (" (ambiguous: check the receiver type)" if ambiguous else ""))
                elif tok in d["removed_members"] and re.search(rf"\.{re.escape(tok)}\s*\(", line):
                    notes.append(f"{tok} REMOVED (look for a replacement with mcsrc.py search)")
            if notes:
                out_lines.append(f"  {i}: " + "; ".join(sorted(notes)))
        if out_lines:
            print(rel)
            print("\n".join(out_lines))
            hits += len(out_lines)
    return hits


def dotted_removed(name: str, d: dict) -> bool:
    return any(dotted(c) == name for c in d["removed_classes"])


def main() -> int:
    ap = argparse.ArgumentParser(prog="mcport", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="old", required=True, help="current Minecraft version")
    ap.add_argument("--to", dest="new", required=True, help="target Minecraft version")
    ap.add_argument("--ns", choices=["yarn", "mojang"], help="mappings set (default: detect from project)")
    ap.add_argument("--project", default=".")
    ap.add_argument("--src", help="source dir (default: <project>/src)")
    ap.add_argument("--apply-imports", action="store_true", help="rewrite renamed imports in place")
    ap.add_argument("--all", action="store_true", help="also list ambiguous member renames")
    ap.add_argument("--summary", action="store_true", help="print rename counts only")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    root = Path(args.project).resolve()
    ns = args.ns
    if not ns:
        info = mcsrc.detect(mcsrc.find_root(root))
        ns = mcsrc.project_ns(info)
    print(f"# {ns} names, {args.old} -> {args.new} (mappings download once per version)", file=sys.stderr)
    try:
        old, new = mappings.build_table(args.old), mappings.build_table(args.new)
    except Exception as e:
        print(f"mcport: could not load mappings: {e}")
        return 2
    d = diff(old, new, ns)
    print(f"{len(d['classes'])} classes renamed, {len(d['members'])} member names changed, "
          f"{len(d['removed_classes'])} classes and {len(d['removed_members'])} members removed")
    if args.summary:
        return 0
    src = Path(args.src) if args.src else root / "src"
    if not src.is_dir():
        print(f"mcport: no source dir at {src}")
        return 2
    scan.hidden = 0
    hits = scan(src, d, args.apply_imports, args.all)
    if scan.hidden:
        print(f"# {scan.hidden} calls use names that changed on some classes but still exist on others; "
              "--all lists them")
    if not hits:
        print("No renamed or removed names found in your sources.")
    else:
        print("\nVerify each member suggestion with mcsrc.py method/field after switching the project to "
              f"{args.new}; mappings cannot see signature or behavior changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
