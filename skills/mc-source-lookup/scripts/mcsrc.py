#!/usr/bin/env python3
"""mcsrc: look up the real Minecraft / loader API of the project you are in.

Reads the named (deobfuscated) jars that Fabric Loom or NeoForge ModDevGradle
already put on disk, parses the class files directly and prints signatures in
Java syntax plus the descriptor string a mixin needs. No decompiler, no deps.

    mcsrc.py detect
    mcsrc.py class LivingEntity [--inherited]
    mcsrc.py method LivingEntity#damage
    mcsrc.py field LivingEntity#lastDamageTaken
    mcsrc.py search 'Damage.*Source' [--members]
    mcsrc.py source LivingEntity#damage
    mcsrc.py files 'diamond_sword'
    mcsrc.py cat data/minecraft/recipe/diamond_sword.json
    mcsrc.py translate LivingEntity#hurt     # Mojang <-> Yarn <-> intermediary
"""
from __future__ import annotations

import argparse
import difflib
import glob
import hashlib
import json
import os
import re
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling mappings.py

INDEX_VERSION = 2

# ---------------------------------------------------------------- detection


def read_props(path: Path) -> dict[str, str]:
    props: dict[str, str] = {}
    if not path.is_file():
        return props
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        m = re.match(r"([^=:\s]+)\s*[=:]\s*(.*)", line)
        if m:
            props[m.group(1)] = m.group(2).strip()
    return props


def find_root(start: Path) -> Path:
    for d in [start, *start.parents]:
        if any((d / n).is_file() for n in ("build.gradle", "build.gradle.kts")) and (
            (d / "gradle.properties").is_file() or (d / "settings.gradle").is_file()
            or (d / "settings.gradle.kts").is_file()
        ):
            return d
    sys.exit("mcsrc: no Gradle project found here or above. Run inside a mod project.")


def detect(root: Path) -> dict:
    props = read_props(root / "gradle.properties")
    build = ""
    for n in ("build.gradle", "build.gradle.kts"):
        if (root / n).is_file():
            build += (root / n).read_text(encoding="utf-8", errors="replace")
    settings = ""
    for n in ("settings.gradle", "settings.gradle.kts"):
        if (root / n).is_file():
            settings += (root / n).read_text(encoding="utf-8", errors="replace")
    text = build + settings

    info: dict = {"root": str(root)}
    if re.search(r"fabric-loom|net\.fabricmc\.fabric-loom|['\"]fabric-loom", text):
        info["loader"] = "fabric"
        info["loader_version"] = props.get("loader_version")
        info["fabric_api_version"] = props.get("fabric_api_version") or props.get("fabric_version")
        if "officialMojangMappings" in build:
            info["mappings"] = "mojang"
            if "parchment" in build:
                info["mappings"] = "mojang+parchment"
        elif re.search(r"yarn", build):
            info["mappings"] = "yarn"
            info["yarn"] = props.get("yarn_mappings")
        elif not re.search(r"^\s*mappings\b", build, re.M):
            # no mappings dependency at all: an unobfuscated Minecraft (26.1+), named by Mojang
            info["mappings"] = "mojang"
        else:
            info["mappings"] = "unknown"
    elif re.search(r"net\.neoforged\.moddev", text):
        info["loader"] = "neoforge"
        info["plugin"] = "moddevgradle"
    elif re.search(r"net\.neoforged\.gradle", text):
        info["loader"] = "neoforge"
        info["plugin"] = "neogradle"
    elif re.search(r"net\.minecraftforge\.gradle|ForgeGradle", text):
        info["loader"] = "forge"
    else:
        info["loader"] = "unknown"

    if info["loader"] in ("neoforge", "forge"):
        info["loader_version"] = props.get("neo_version") or props.get("forge_version")
        info["mappings"] = "mojang+parchment" if "parchment" in build else "mojang"

    info["minecraft_version"] = props.get("minecraft_version")
    m = (re.search(r"languageVersion(?:\s*=\s*|\.set\(\s*)JavaLanguageVersion\.of\((\d+)\)", build)
         or re.search(r"release(?:\s*=\s*|\.set\(\s*)(\d+)", build)
         or re.search(r"JavaVersion\.VERSION_(?:1_)?(\d+)", build))
    info["java"] = int(m.group(1)) if m else None
    return info


# ---------------------------------------------------------------- jar discovery


def _newest(paths: list[str]) -> list[str]:
    return sorted(set(paths), key=lambda p: os.path.getmtime(p), reverse=True)


def _is_version(base: str, mc: str) -> bool:
    """True if a jar file name carries exactly this Minecraft version ('1.21' must not match '1.21.1')."""
    return mc == "*" or re.search(rf"-{re.escape(mc)}(?:-|\.jar$)", base) is not None


def find_jars(root: Path, info: dict) -> dict[str, list[str]]:
    """Return {'minecraft': [...], 'api': [...]} of named class jars, plus 'resources' jars without classes."""
    mc = info.get("minecraft_version") or "*"
    home = Path.home() / ".gradle" / "caches"
    out: dict[str, list[str]] = {"minecraft": [], "api": [], "resources": []}

    if info["loader"] == "fabric":
        pats = [
            str(root / ".gradle/loom-cache/minecraftMaven/net/minecraft/**/*.jar"),
            str(home / "fabric-loom/minecraftMaven/net/minecraft/**/*.jar"),
        ]
        cands = []
        for p in pats:
            cands += glob.glob(p, recursive=True)
        cands = [
            c for c in cands
            if "intermediary" not in os.path.basename(c)
            and not c.endswith("-sources.jar")
            and _is_version(os.path.basename(c), mc)
        ]
        # project-local cache first: it matches the project's exact mappings
        local = [c for c in cands if str(root) in c]
        out["minecraft"] = _newest(local)[:1] or _newest(cands)[:1]
        api = glob.glob(str(root / ".gradle/loom-cache/remapped_mods/**/*.jar"), recursive=True)
        out["api"] = sorted(a for a in api if not a.endswith("-sources.jar"))
    elif info["loader"] == "neoforge":
        # ModDevGradle writes neoforge-<v>.jar (vanilla + NeoForge classes), -sources.jar, -merged.jar
        # (the same classes plus resources) and -client-extra-aka-minecraft-resources.jar (vanilla
        # assets and data, no classes). The global neoformruntime cache only holds intermediate,
        # partly obfuscated jars, so it is never searched.
        cands = glob.glob(str(root / "build/moddev/artifacts/*.jar"))
        cands += glob.glob(str(root / "build/neoForm/**/*.jar"), recursive=True)
        out["resources"] = sorted(c for c in cands if "-client-extra" in os.path.basename(c))
        cands = [c for c in cands if not c.endswith("-sources.jar") and c not in out["resources"]]
        want = f"neoforge-{info.get('loader_version')}.jar"
        exact = [c for c in cands if os.path.basename(c) == want]
        plain = [c for c in cands if not c.endswith("-merged.jar")]
        out["minecraft"] = exact[:1] or _newest(plain)[:1] or _newest(cands)[:1]
    return out


def sources_for(jar: str) -> str | None:
    s = jar[:-4] + "-sources.jar"
    if os.path.isfile(s):
        return s
    # Loom names genSources output after the jar; ModDevGradle uses '-sources' too.
    hits = glob.glob(os.path.join(os.path.dirname(jar), "*-sources.jar"))
    return hits[0] if hits else None


# ---------------------------------------------------------------- class file parsing

ACC = {
    0x0001: "public", 0x0002: "private", 0x0004: "protected", 0x0008: "static",
    0x0010: "final", 0x0400: "abstract",
}
PRIMS = {"B": "byte", "C": "char", "D": "double", "F": "float", "I": "int",
         "J": "long", "S": "short", "Z": "boolean", "V": "void"}


def lvt_params(code: bytes, acc: int, desc: str, utf8: dict[int, str]) -> list[str] | None:
    """Parameter names from a Code attribute's LocalVariableTable.

    NeoForge recompiles Minecraft with Parchment names in the debug info but writes no
    MethodParameters attribute, so this is where its parameter names live.
    """
    if not desc.startswith("("):
        return None
    slots, slot = [], 0 if acc & 0x0008 else 1
    for t in re.findall(r"\[*(?:L[^;]+;|[BCDFIJSZ])", desc[1:desc.index(")")]):
        slots.append(slot)
        slot += 2 if t in ("J", "D") else 1
    if not slots:
        return None
    (code_len,) = struct.unpack_from(">I", code, 4)
    p = 8 + code_len
    (n_exc,) = struct.unpack_from(">H", code, p)
    p += 2 + 8 * n_exc
    (n_attr,) = struct.unpack_from(">H", code, p)
    p += 2
    for _ in range(n_attr):
        ai, al = struct.unpack_from(">HI", code, p)
        if utf8.get(ai) == "LocalVariableTable":
            (n,) = struct.unpack_from(">H", code, p + 6)
            names = {}
            for j in range(n):
                start, _, name_i, _, index = struct.unpack_from(">HHHHH", code, p + 8 + j * 10)
                if start == 0:
                    names[index] = utf8.get(name_i, "")
            found = [names.get(s) for s in slots]
            return found if all(found) else None
        p += 6 + al
    return None


def parse_class(data: bytes) -> dict | None:
    if data[:4] != b"\xca\xfe\xba\xbe":
        return None
    pos = 8
    (count,) = struct.unpack_from(">H", data, pos)
    pos += 2
    utf8: dict[int, str] = {}
    cls: dict[int, int] = {}
    i = 1
    while i < count:
        tag = data[pos]
        pos += 1
        if tag == 1:
            (ln,) = struct.unpack_from(">H", data, pos)
            utf8[i] = data[pos + 2:pos + 2 + ln].decode("utf-8", errors="replace")
            pos += 2 + ln
        elif tag == 7:
            cls[i] = struct.unpack_from(">H", data, pos)[0]
            pos += 2
        elif tag in (8, 16, 19, 20):
            pos += 2
        elif tag == 15:
            pos += 3
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            pos += 4
        elif tag in (5, 6):
            pos += 8
            i += 1
        else:
            return None
        i += 1

    def cname(idx: int) -> str | None:
        return utf8.get(cls.get(idx, 0)) if idx else None

    access, this_i, super_i, n_if = struct.unpack_from(">HHHH", data, pos)
    pos += 8
    ifaces = []
    for _ in range(n_if):
        ifaces.append(cname(struct.unpack_from(">H", data, pos)[0]))
        pos += 2

    def members() -> list[list]:
        nonlocal pos
        (n,) = struct.unpack_from(">H", data, pos)
        pos += 2
        res = []
        for _ in range(n):
            acc, ni, di, na = struct.unpack_from(">HHHH", data, pos)
            pos += 8
            sig = None
            params: list[str] | None = None
            for _ in range(na):
                ai, al = struct.unpack_from(">HI", data, pos)
                aname = utf8.get(ai)
                body = data[pos + 6:pos + 6 + al]
                if aname == "Signature":
                    sig = utf8.get(struct.unpack_from(">H", body)[0])
                elif aname == "MethodParameters":
                    k = body[0]
                    params = [utf8.get(struct.unpack_from(">H", body, 1 + j * 4)[0], "") for j in range(k)]
                elif aname == "Code" and params is None:
                    params = lvt_params(body, acc, utf8.get(di) or "", utf8)
                pos += 6 + al
            res.append([acc, utf8.get(ni), utf8.get(di), sig, params])
        return res

    fields = members()
    methods = members()
    return {
        "name": cname(this_i), "access": access, "super": cname(super_i),
        "interfaces": ifaces, "fields": fields, "methods": methods,
    }


# ---------------------------------------------------------------- index


def cache_dir(root: Path) -> Path:
    d = root / ".gradle" / "mixinsmith"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_index(root: Path, jars: list[str]) -> dict:
    key = hashlib.sha1(
        json.dumps([[j, os.path.getmtime(j)] for j in jars] + [INDEX_VERSION]).encode()
    ).hexdigest()[:16]
    path = cache_dir(root) / f"index-{key}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    for old in cache_dir(root).glob("index-*.json"):
        old.unlink()
    classes: dict[str, dict] = {}
    for jar in jars:
        with zipfile.ZipFile(jar) as z:
            for n in z.namelist():
                if not n.endswith(".class") or n.endswith(("module-info.class", "package-info.class")):
                    continue
                c = parse_class(z.read(n))
                if c and c["name"] and c["name"] not in classes:
                    c["jar"] = jar
                    classes[c["name"]] = c
    idx = {"classes": classes}
    path.write_text(json.dumps(idx), encoding="utf-8")
    return idx


# ---------------------------------------------------------------- formatting


def simple(internal: str) -> str:
    return internal.rsplit("/", 1)[-1].replace("$", ".")


def parse_type(desc: str, i: int) -> tuple[str, int]:
    dims = 0
    while desc[i] == "[":
        dims += 1
        i += 1
    if desc[i] == "L":
        j = desc.index(";", i)
        t = simple(desc[i + 1:j])
        i = j + 1
    else:
        t = PRIMS[desc[i]]
        i += 1
    return t + "[]" * dims, i


class _Sig:
    """Minimal JVM generic-signature reader (JVMS 4.7.9.1) producing Java syntax."""

    def __init__(self, s: str):
        self.s, self.i = s, 0

    def peek(self) -> str:
        return self.s[self.i]

    def type_params(self) -> str:
        if self.peek() != "<":
            return ""
        self.i += 1
        out = []
        while self.peek() != ">":
            j = self.s.index(":", self.i)
            name = self.s[self.i:j]
            self.i = j
            bounds = []
            while self.peek() == ":":
                self.i += 1
                if self.peek() not in ":>":
                    b = self.ref()
                    if b != "Object":
                        bounds.append(b)
            out.append(name + (" extends " + " & ".join(bounds) if bounds else ""))
        self.i += 1
        return "<" + ", ".join(out) + ">"

    def type(self) -> str:
        c = self.peek()
        if c in PRIMS:
            self.i += 1
            return PRIMS[c]
        return self.ref()

    def ref(self) -> str:
        c = self.peek()
        if c == "[":
            self.i += 1
            return self.type() + "[]"
        if c == "T":
            j = self.s.index(";", self.i)
            name = self.s[self.i + 1:j]
            self.i = j + 1
            return name
        self.i += 1  # 'L'
        name, args = "", ""
        while True:
            c = self.peek()
            if c in "<.;":
                if c == "<":
                    args = self.type_args()
                    continue
                self.i += 1
                if c == ";":
                    return simple(name) + args
                name, args = name + "$", ""  # Outer<T>.Inner -> Outer.Inner
                continue
            name += c
            self.i += 1

    def type_args(self) -> str:
        self.i += 1
        out = []
        while self.peek() != ">":
            c = self.peek()
            if c == "*":
                self.i += 1
                out.append("?")
            elif c in "+-":
                self.i += 1
                out.append(("? extends " if c == "+" else "? super ") + self.ref())
            else:
                out.append(self.ref())
        self.i += 1
        return "<" + ", ".join(out) + ">"

    def method(self) -> tuple[str, list[str], str]:
        tp = self.type_params()
        self.i += 1  # '('
        args = []
        while self.peek() != ")":
            args.append(self.type())
        self.i += 1
        ret = "void" if self.peek() == "V" else self.type()
        return tp, args, ret


def sig_field(sig: str | None, desc: str) -> str:
    if sig:
        try:
            return _Sig(sig).ref()
        except (IndexError, ValueError, KeyError):
            pass
    return parse_type(desc, 0)[0]


def sig_method(sig: str | None, desc: str) -> tuple[str, list[str], str]:
    args, ret = method_types(desc)
    if sig:
        try:
            tp, gargs, gret = _Sig(sig).method()
            # signatures omit synthetic params (e.g. enum ctor name/ordinal); only trust a full match
            if len(gargs) == len(args):
                return tp, gargs, gret
            return tp, args, gret
        except (IndexError, ValueError, KeyError):
            pass
    return "", args, ret


def method_types(desc: str) -> tuple[list[str], str]:
    args = []
    i = 1
    while desc[i] != ")":
        t, i = parse_type(desc, i)
        args.append(t)
    ret, _ = parse_type(desc, i + 1)
    return args, ret


def mods(acc: int, skip_abstract_iface: bool = False) -> str:
    words = [w for bit, w in ACC.items() if acc & bit]
    if skip_abstract_iface and "abstract" in words:
        words.remove("abstract")
    return " ".join(words)


def fmt_method(owner: str, m: list) -> str:
    acc, name, desc, sig, params = m
    tp, args, ret = sig_method(sig, desc)
    if params and len(params) == len(args):
        args = [f"{a} {p}" for a, p in zip(args, params)]
    if acc & 0x0080 and args:  # varargs
        args[-1] = args[-1].replace("[]", "...", 1) if "[]" in args[-1] else args[-1]
    shown = simple(owner) if name == "<init>" else name
    head = " ".join(x for x in (mods(acc), tp) if x)
    head = head + " " if head else ""
    ret_s = "" if name == "<init>" else f"{ret} "
    return f"{head}{ret_s}{shown}({', '.join(args)})"


def fmt_field(m: list) -> str:
    acc, name, desc, sig, _ = m
    t = sig_field(sig, desc)
    head = f"{mods(acc)} " if mods(acc) else ""
    return f"{head}{t} {name}"


def mixin_target(owner: str, m: list) -> str:
    return f"L{owner};{m[1]}{m[2]}" if m[2].startswith("(") else f"L{owner};{m[1]}:{m[2]}"


# ---------------------------------------------------------------- queries


def resolve(idx: dict, name: str) -> list[str]:
    classes = idx["classes"]
    n = name.replace(".", "/")
    if n in classes:
        return [n]
    # "Outer.Inner" may arrive as "Outer/Inner"; also accept a bare "Inner"
    nested = n.replace("/", "$")
    hits = [c for c in classes
            if c.split("/")[-1] == nested or c.endswith("/" + n) or c.endswith("$" + nested)]
    # top-level before nested, vanilla before loader API, shallow packages first
    return sorted(hits, key=lambda c: (
        "$" in c.split("/")[-1] and "$" not in nested,
        not c.startswith(("net/minecraft/", "com/mojang/")),
        c.count("/"), c,
    ))


def pick_class(idx: dict, name: str) -> str:
    hits = resolve(idx, name)
    if not hits:
        sys.exit(f"mcsrc: no class named '{name}' in this project's jars. Try: mcsrc.py search {name}")
    if len(hits) > 1:
        print(f"# {len(hits)} classes match '{name}', using the first. Others: "
              + ", ".join(h.replace('/', '.') for h in hits[1:6]), file=sys.stderr)
    return hits[0]


def supers(idx: dict, cname: str) -> list[str]:
    chain, seen, todo = [], set(), [cname]
    while todo:
        c = todo.pop(0)
        if c in seen or c not in idx["classes"]:
            continue
        seen.add(c)
        chain.append(c)
        k = idx["classes"][c]
        todo += [k["super"]] + [i for i in k["interfaces"] if i]
    return chain


def cmd_class(idx: dict, args) -> None:
    cn = pick_class(idx, args.name)
    k = idx["classes"][cn]
    kind = "interface" if k["access"] & 0x0200 else ("enum" if k["access"] & 0x4000 else "class")
    print(f"{mods(k['access'] & ~0x0020, kind == 'interface')} {kind} {cn.replace('/', '.')}".strip())
    if k["super"] and k["super"] != "java/lang/Object":
        print(f"  extends {k['super'].replace('/', '.')}")
    if k["interfaces"]:
        print(f"  implements {', '.join(i.replace('/', '.') for i in k['interfaces'])}")
    owners = supers(idx, cn) if args.inherited else [cn]
    for owner in owners:
        ok = idx["classes"][owner]
        if owner != cn:
            print(f"\n  -- from {owner.replace('/', '.')}")
        for f in ok["fields"]:
            if f[0] & 0x1000:  # synthetic
                continue
            print(f"  {fmt_field(f)};")
        for m in ok["methods"]:
            if m[0] & 0x1040 or m[1] == "<clinit>":  # synthetic/bridge
                continue
            if owner != cn and m[1] == "<init>":
                continue
            print(f"  {fmt_method(owner, m)};")


def split_member(spec: str) -> tuple[str, str]:
    if "#" not in spec:
        sys.exit("mcsrc: use Class#member, e.g. LivingEntity#damage")
    c, m = spec.split("#", 1)
    return c, m


def cmd_method(idx: dict, args) -> None:
    cname, mname = split_member(args.spec)
    cn = pick_class(idx, cname)
    found = False
    for owner in supers(idx, cn):
        for m in idx["classes"][owner]["methods"]:
            if m[1] == mname and not m[0] & 0x1040:
                found = True
                where = "" if owner == cn else f"   (declared in {simple(owner)})"
                print(f"{fmt_method(owner, m)}{where}")
                print(f"  mixin target: {m[1]}{m[2]}")
                print(f"  full:         {mixin_target(owner, m)}")
        if found:
            break  # nearest declaration wins; overrides higher up are noise
    if not found:
        names = {m[1] for o in supers(idx, cn) for m in idx["classes"][o]["methods"]
                 if not m[1].startswith("<") and not m[0] & 0x1040}  # skip lambda$ and bridges
        near = sorted(n for n in names if mname.lower() in n.lower())
        near += [n for n in difflib.get_close_matches(mname, names, n=6, cutoff=0.6) if n not in near]
        msg = f"mcsrc: {simple(cn)} has no method '{mname}' (searched the class and its supertypes)."
        if near:
            msg += " Similar: " + ", ".join(near[:12])
        sys.exit(msg + translation_hint(args.info, args.spec, supers(idx, cn)))


def cmd_field(idx: dict, args) -> None:
    cname, fname = split_member(args.spec)
    cn = pick_class(idx, cname)
    for owner in supers(idx, cn):
        for f in idx["classes"][owner]["fields"]:
            if f[1] == fname:
                where = "" if owner == cn else f"   (declared in {simple(owner)})"
                print(f"{fmt_field(f)}{where}")
                print(f"  mixin target: {mixin_target(owner, f)}")
                return
    near = sorted({f[1] for o in supers(idx, cn) for f in idx["classes"][o]["fields"]
                   if fname.lower() in f[1].lower()})
    sys.exit(f"mcsrc: {simple(cn)} has no field '{fname}'." + (" Similar: " + ", ".join(near[:12]) if near else "")
             + translation_hint(args.info, args.spec, supers(idx, cn)))


def cmd_search(idx: dict, args) -> None:
    rx = re.compile(args.pattern, re.I)
    n = 0
    # loader mixin classes are implementation details, never something a mod should call
    items = [(cn, k) for cn, k in idx["classes"].items() if "/mixin/" not in cn]
    items.sort(key=lambda it: (not it[0].startswith(("net/minecraft/", "com/mojang/")), it[0]))
    for cn, k in items:
        if rx.search(cn.split("/")[-1]):
            print(cn.replace("/", "."))
            n += 1
        if args.members:
            for m in k["methods"]:
                if rx.search(m[1]) and not m[0] & 0x1040:
                    print(f"{simple(cn)}#{m[1]}    {fmt_method(cn, m)}")
                    n += 1
        if n >= args.limit:
            print(f"# stopped at {args.limit} results, refine the pattern")
            return


def cmd_source(idx: dict, args) -> None:
    cname, _, mname = args.spec.partition("#")
    cn = pick_class(idx, cname)
    jar = idx["classes"][cn]["jar"]
    src = sources_for(jar)
    if not src:
        hint = "./gradlew genSources" if "loom" in jar else "./gradlew build (ModDevGradle writes sources jars on setup)"
        sys.exit(f"mcsrc: no sources jar next to {os.path.basename(jar)}. Generate it with: {hint}")
    outer = cn.split("$")[0] + ".java"
    with zipfile.ZipFile(src) as z:
        try:
            text = z.read(outer).decode("utf-8", errors="replace")
        except KeyError:
            sys.exit(f"mcsrc: {outer} not in {os.path.basename(src)}")
    lines = text.splitlines()
    if not mname:
        print("\n".join(lines[: args.lines]))
        return
    shown = 0
    for i, line in enumerate(lines):
        if re.search(rf"\b{re.escape(mname)}\s*\(", line) and not line.strip().startswith(("//", "*", "return", "this.")) \
                and re.search(r"^\s*(public|protected|private|static|final|abstract|synchronized|default|<|[A-Z\w<>\[\],\s]+\s)", line) \
                and not re.search(r"[=;]\s*$", line.split("//")[0]) and "new " not in line:
            depth, end = 0, i
            for j in range(i, min(len(lines), i + args.lines)):
                depth += lines[j].count("{") - lines[j].count("}")
                end = j
                if depth <= 0 and "{" in "".join(lines[i:j + 1]):
                    break
                if depth == 0 and lines[j].rstrip().endswith(";"):
                    break
            print(f"// {outer}:{i + 1}")
            print("\n".join(lines[i:end + 1]))
            print()
            shown += 1
    if not shown:
        sys.exit(f"mcsrc: '{mname}' not found in {outer}")


def project_ns(info: dict) -> str:
    return "yarn" if info.get("mappings") == "yarn" else "mojang"


def in_hierarchy(rows: list[dict], ns: str, owners: list[str] | None) -> list[dict]:
    """Keep members declared in the queried class or its supertypes (names in the project's mappings).

    mappings.translate falls back to every class with a member of that name when the queried class
    does not declare it; the project's own class hierarchy narrows that back down.
    """
    if not owners:
        return rows
    keep = [r for r in rows if r.get("kind") == "class" or r.get("owner_" + ns) in owners]
    return keep or rows


def translation_hint(info: dict, spec: str, owners: list[str] | None = None) -> str:
    """One line naming the member in this project's mappings, if the table is already cached."""
    mc = info.get("minecraft_version")
    if not mc:
        return ""
    try:
        import mappings
        if not mappings.cached(mc):
            return f"\nIf '{spec.split('#')[-1]}' is a name from other mappings, run: mcsrc.py translate {spec}"
        rows = mappings.translate(mappings.build_table(mc), spec)
    except Exception:
        return ""
    ns = project_ns(info)
    rows = in_hierarchy(rows, ns, owners)
    names = sorted({f"{simple(r['owner_' + ns])}#{r[ns]}" for r in rows if r.get(ns)})
    if not names:
        return ""
    return f"\nIn {ns} mappings (this project) that name is: " + ", ".join(names[:6])


def project_hierarchy(table: dict, query: str, ns: str, root: Path, jars: dict) -> list[str]:
    """Supertypes (project names) of the class in 'Class#member', read from the project's jars."""
    import mappings
    cls_q = query.partition("#")[0] if "#" in query else ""
    if not cls_q or not jars["minecraft"]:
        return []
    idx = load_index(root, jars["minecraft"] + jars["api"])
    owners: list[str] = []
    for r in mappings.translate(table, cls_q):
        if r.get(ns) in idx["classes"]:
            owners += supers(idx, r[ns])
    return owners


def cmd_translate(info: dict, args, root: Path, jars: dict) -> None:
    mc = info.get("minecraft_version")
    if not mc:
        sys.exit("mcsrc: unknown Minecraft version; cannot pick mappings")
    import mappings
    if not mappings.cached(mc):
        print(f"# building the Mojang/Yarn table for {mc} (one-time download)", file=sys.stderr)
    try:
        table = mappings.build_table(mc)
    except Exception as e:
        sys.exit(f"mcsrc: could not load mappings for {mc}: {e}")
    rows = mappings.translate(table, args.query)
    if not rows:
        sys.exit(f"mcsrc: '{args.query}' is not a name in Mojang, Yarn or intermediary for {mc}")
    ns = project_ns(info)
    rows = in_hierarchy(rows, ns, project_hierarchy(table, args.query, ns, root, jars))
    print(f"# this project uses {ns} names")
    for r in rows[:args.limit]:
        if r["kind"] == "class":
            print(f"class  yarn: {r['yarn']}  mojang: {r['mojang']}  intermediary: {r['intermediary']}")
        else:
            kind = "method" if r["kind"] == "m" else "field"
            print(f"{kind}  yarn: {simple(r['owner_yarn'])}#{r['yarn']}  "
                  f"mojang: {simple(r['owner_mojang'])}#{r['mojang']}  intermediary: {r['intermediary']}")


def cmd_files(jars: list[str], args) -> None:
    rx = re.compile(args.pattern, re.I)
    n = 0
    seen: set[str] = set()  # NeoForge ships some vanilla data in two jars
    for jar in jars:
        with zipfile.ZipFile(jar) as z:
            for name in z.namelist():
                if not name.endswith(("/", ".class")) and rx.search(name) and name not in seen:
                    seen.add(name)
                    print(name)
                    n += 1
                    if n >= args.limit:
                        print(f"# stopped at {args.limit} results, refine the pattern")
                        return
    if not n:
        sys.exit(f"mcsrc: no resource matches '{args.pattern}'")


def cmd_cat(jars: list[str], args) -> None:
    for jar in jars:
        with zipfile.ZipFile(jar) as z:
            try:
                data = z.read(args.path)
            except KeyError:
                continue
        if args.path.endswith((".png", ".ogg", ".nbt")):
            sys.exit(f"mcsrc: {args.path} is binary ({len(data)} bytes)")
        print(data.decode("utf-8", errors="replace"))
        return
    sys.exit(f"mcsrc: {args.path} not found. List candidates with: mcsrc.py files '<pattern>'")


# ---------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(prog="mcsrc", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=".", help="mod project directory (default: current)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect", help="loader, Minecraft version, mappings, jars")
    p = sub.add_parser("class", help="list a class's fields and methods")
    p.add_argument("name")
    p.add_argument("--inherited", action="store_true", help="include supertypes")
    p = sub.add_parser("method", help="overloads of Class#method with mixin descriptors")
    p.add_argument("spec")
    p = sub.add_parser("field", help="Class#field with its descriptor")
    p.add_argument("spec")
    p = sub.add_parser("search", help="regex over class (and --members method) names")
    p.add_argument("pattern")
    p.add_argument("--members", action="store_true")
    p.add_argument("--limit", type=int, default=60)
    p = sub.add_parser("source", help="print decompiled source of Class or Class#method")
    p.add_argument("spec")
    p.add_argument("--lines", type=int, default=80)
    p = sub.add_parser("files", help="regex over resource paths (assets/, data/) in the jars")
    p.add_argument("pattern")
    p.add_argument("--limit", type=int, default=60)
    p = sub.add_parser("translate", help="same class/member in Mojang, Yarn and intermediary names")
    p.add_argument("query", help="Class, Class#member or member, in any mappings")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("cat", help="print a resource file, e.g. data/minecraft/recipe/diamond_sword.json")
    p.add_argument("path")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    root = find_root(Path(args.project).resolve())
    info = detect(root)
    jars = find_jars(root, info)
    args.info = info
    if args.cmd == "translate":
        cmd_translate(info, args, root, jars)
        return

    if args.cmd == "detect":
        info["jars"] = {k: v[:3] + ([f"... {len(v) - 3} more"] if len(v) > 3 else []) for k, v in jars.items()}
        info["sources"] = sources_for(jars["minecraft"][0]) if jars["minecraft"] else None
        print(json.dumps(info, indent=2))
        return

    if not jars["minecraft"]:
        task = "./gradlew compileJava" if info["loader"] == "neoforge" else "./gradlew build"
        sys.exit(f"mcsrc: no named Minecraft jar found for {info['loader']} {info.get('minecraft_version')}. "
                 f"Run `{task}` once so the toolchain sets up Minecraft, then retry.")
    if args.cmd in ("files", "cat"):
        all_jars = jars["minecraft"] + jars["resources"] + jars["api"]
        (cmd_files if args.cmd == "files" else cmd_cat)(all_jars, args)
        return
    idx = load_index(root, jars["minecraft"] + jars["api"])
    {"class": cmd_class, "method": cmd_method, "field": cmd_field,
     "search": cmd_search, "source": cmd_source}[args.cmd](idx, args)


if __name__ == "__main__":
    main()
