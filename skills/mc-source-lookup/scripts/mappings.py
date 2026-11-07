"""Cross-mappings table: the same class or member under Mojang, Yarn and intermediary names.

Joins on the obfuscated ("official") names, which every mappings set shares:
  - Mojang:        ProGuard client.txt (named -> official), published by Mojang for 1.14.4+
  - intermediary + Yarn: Fabric tiny v2 file (official -> intermediary -> named)

Files come from local Gradle caches when present, otherwise they are downloaded once into
~/.cache/mixinsmith/<mc version>/.
"""
from __future__ import annotations

import glob
import gzip
import io
import json
import os
import re
import urllib.request
import zipfile
from pathlib import Path

CACHE = Path(os.environ.get("MIXINSMITH_CACHE", Path.home() / ".cache" / "mixinsmith"))
MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
YARN_META = "https://meta.fabricmc.net/v2/versions/yarn/{mc}"
YARN_JAR = "https://maven.fabricmc.net/net/fabricmc/yarn/{v}/yarn-{v}-v2.jar"
TABLE_VERSION = 1
PRIM = {"byte": "B", "char": "C", "double": "D", "float": "F", "int": "I",
        "long": "J", "short": "S", "boolean": "Z", "void": "V"}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mixinsmith"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


# ---------------------------------------------------------------- sources


def mojang_txt(mc: str) -> str:
    dst = CACHE / mc / "client.txt"
    if dst.is_file():
        return dst.read_text(encoding="utf-8")
    info = None
    for p in glob.glob(str(Path.home() / ".gradle/caches/fabric-loom" / mc / "mojang_minecraft_info.json")):
        info = json.loads(Path(p).read_text(encoding="utf-8"))
    if info is None:
        man = json.loads(_get(MANIFEST))
        url = next((v["url"] for v in man["versions"] if v["id"] == mc), None)
        if not url:
            raise LookupError(f"Minecraft {mc} is not in Mojang's version manifest")
        info = json.loads(_get(url))
    dl = info.get("downloads", {}).get("client_mappings")
    if not dl:
        raise LookupError(f"Mojang published no mappings for {mc} (they start at 1.14.4)")
    text = _get(dl["url"]).decode("utf-8")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    return text


def yarn_tiny(mc: str, project_root: Path | None = None) -> str:
    local = glob.glob(str(Path.home() / ".gradle/caches/fabric-loom" / mc / "net.fabricmc.yarn.*" / "mappings.tiny"))
    if local:
        return Path(sorted(local)[-1]).read_text(encoding="utf-8")
    dst = CACHE / mc / "yarn.tiny"
    if dst.is_file():
        return dst.read_text(encoding="utf-8")
    builds = json.loads(_get(YARN_META.format(mc=mc)))
    if not builds:
        raise LookupError(f"no Yarn mappings exist for {mc}")
    v = builds[0]["version"]  # meta lists newest build first
    with zipfile.ZipFile(io.BytesIO(_get(YARN_JAR.format(v=v)))) as z:
        text = z.read("mappings/mappings.tiny").decode("utf-8")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    return text


# ---------------------------------------------------------------- parsers


def parse_tiny(text: str) -> tuple[dict, dict]:
    """-> classes {official: {ns: name}}, members {(owner_off, kind, name_off, desc_off): {ns: name}}"""
    lines = text.splitlines()
    header = lines[0].split("\t")
    ns = header[3:]
    classes: dict[str, dict] = {}
    members: dict[tuple, dict] = {}
    owner = None
    for line in lines[1:]:
        parts = line.split("\t")
        if parts[0] == "c":
            names = dict(zip(ns, parts[1:]))
            owner = names[ns[0]]
            classes[owner] = names
        elif len(parts) > 2 and parts[0] == "" and parts[1] in ("m", "f") and owner:
            kind, desc, *names = parts[1:]
            names_d = dict(zip(ns, names))
            members[(owner, kind, names_d[ns[0]], desc)] = names_d
    return classes, members


def _jtype(t: str, cls_map: dict[str, str]) -> str:
    dims = t.count("[]")
    base = t.replace("[]", "")
    d = PRIM.get(base)
    if d is None:
        d = "L" + cls_map.get(base, base.replace(".", "/")) + ";"
    return "[" * dims + d


def parse_proguard(text: str) -> tuple[dict, dict]:
    """-> classes {official: mojang}, members keyed like parse_tiny with official descriptors"""
    named_to_off: dict[str, str] = {}
    for line in text.splitlines():
        if line and not line.startswith((" ", "#")) and line.endswith(":"):
            named, off = line[:-1].split(" -> ")
            named_to_off[named] = off.replace(".", "/")
    classes = {off: named.replace(".", "/") for named, off in named_to_off.items()}
    members: dict[tuple, str] = {}
    owner = None
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if not line.startswith(" "):
            owner = named_to_off.get(line[:-1].split(" -> ")[0])
            continue
        body, off_name = line.strip().rsplit(" -> ", 1)
        body = re.sub(r"^\d+:\d+:", "", body)
        m = re.match(r"(\S+) ([\w$<>]+)\((.*)\)(?::\d+:\d+)?$", body)
        if m:
            ret, name, args = m.groups()
            desc = "(" + "".join(_jtype(a, named_to_off) for a in args.split(",") if a) + ")" + _jtype(ret, named_to_off)
            members[(owner, "m", off_name, desc)] = name
        else:
            typ, name = body.split(" ", 1)
            members[(owner, "f", off_name, _jtype(typ, named_to_off))] = name
    return classes, members


# ---------------------------------------------------------------- table


def build_table(mc: str) -> dict:
    path = CACHE / mc / f"table-v{TABLE_VERSION}.json.gz"
    if path.is_file():
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    t_cls, t_mem = parse_tiny(yarn_tiny(mc))
    p_cls, p_mem = parse_proguard(mojang_txt(mc))
    classes = []
    for off, names in t_cls.items():
        classes.append({"official": off, "intermediary": names.get("intermediary"),
                        "yarn": names.get("named"), "mojang": p_cls.get(off)})
    # field names are unique per class, so match fields without the descriptor
    p_fields = {(k[0], k[2]): v for k, v in p_mem.items() if k[1] == "f"}
    members = []
    for key, names in t_mem.items():
        owner, kind, off, desc = key
        moj = p_mem.get(key) if kind == "m" else p_fields.get((owner, off))
        members.append({"owner": owner, "kind": kind, "official": off,
                        "intermediary": names.get("intermediary"), "yarn": names.get("named"), "mojang": moj})
    table = {"mc": mc, "classes": classes, "members": members}
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(table, f)
    return table


def cached(mc: str) -> bool:
    return (CACHE / mc / f"table-v{TABLE_VERSION}.json.gz").is_file()


def _simple(n: str | None) -> str:
    return (n or "").rsplit("/", 1)[-1].replace("$", ".")


def translate(table: dict, query: str, member_hint_owner: str | None = None) -> list[dict]:
    """query: 'Class', 'Class#member' or 'member'. Names may be in any mappings set."""
    cls_q, _, mem_q = query.partition("#") if "#" in query else ("", "", query)
    if "#" not in query and query[:1].isupper():
        cls_q, mem_q = query, ""
    by_off = {c["official"]: c for c in table["classes"]}
    out = []
    owners = None
    if cls_q:
        qs = cls_q.replace(".", "/")
        owners = {c["official"] for c in table["classes"]
                  if any(n and (n == qs or n.endswith("/" + qs) or _simple(n) == cls_q) for n in
                         (c["yarn"], c["mojang"], c["intermediary"]))}
        if not mem_q:
            return [{"kind": "class", **by_off[o]} for o in owners]
    def scan(only: set | None) -> list[dict]:
        res = []
        for m in table["members"]:
            if only is not None and m["owner"] not in only:
                continue
            if mem_q in (m["yarn"], m["mojang"], m["intermediary"]):
                c = by_off.get(m["owner"], {})
                res.append({**m, "owner_yarn": c.get("yarn"), "owner_mojang": c.get("mojang")})
        return res

    out = scan(owners)
    if not out and owners:
        out = scan(None)  # declared in a supertype: show every owner, caller filters by context
    return out
