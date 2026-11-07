#!/usr/bin/env python3
"""Score benchmark runs. Re-checks every run independently of what the agent reported.

    python verify.py <bench dir> [--no-boot]

Per run: builds attempted, first build green, final compile, dedicated-server boot (mods load and the
world starts), and task-specific file checks. Prints a markdown table.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MCBUILD = HERE.parent / "skills/mc-build-loop/scripts/mcbuild.py"
RES = "src/main/resources"


def jload(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def find(root: Path, pattern: str) -> list[Path]:
    return sorted((root / RES).glob(pattern))


def java_text(root: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in (root / "src").rglob("*.java"))


def lang(root: Path) -> dict:
    return jload(root / RES / "assets/villagerswarm/lang/en_us.json") or {}


def check(task: str, root: Path) -> list[str]:
    """Return a list of missing requirements (empty = all present)."""
    miss = []
    j = java_text(root)
    if task == "ruby-item":
        if lang(root).get("item.villagerswarm.ruby") != "Ruby":
            miss.append("lang")
        models = find(root, "assets/villagerswarm/models/item/ruby.json")
        if not models or "villagerswarm:item/ruby" not in models[0].read_text(encoding="utf-8"):
            miss.append("model")
        recipes = [jload(p) for p in find(root, "data/villagerswarm/recipe*/*.json")]
        if not any(r and "shapeless" in r.get("type", "") and "emerald" in json.dumps(r) for r in recipes):
            miss.append("recipe")
        if "INGREDIENTS" not in j:
            miss.append("creative tab")
    elif task == "ruby-block":
        if lang(root).get("block.villagerswarm.ruby_block") != "Block of Ruby":
            miss.append("lang")
        if not find(root, "assets/villagerswarm/blockstates/ruby_block.json"):
            miss.append("blockstate")
        if not find(root, "assets/villagerswarm/models/block/ruby_block.json"):
            miss.append("block model")
        if not find(root, "data/villagerswarm/loot_table*/blocks/ruby_block.json"):
            miss.append("loot table")
        tags = [p.read_text(encoding="utf-8") for p in find(root, "data/minecraft/tags/block*/mineable/pickaxe.json")]
        if not any("ruby_block" in t for t in tags):
            miss.append("pickaxe tag")
    elif task == "villager-armor":
        if not re.search(r"@Mixin\(\s*(VillagerEntity|LivingEntity|MerchantEntity|PassiveEntity)", j):
            miss.append("mixin")
    elif task == "wake-message":
        if "Good morning!" not in j or "@Mixin" not in j:
            miss.append("mixin/message")
    elif task == "diamond-xp":
        if "PlayerBlockBreakEvents" not in j or "DIAMOND_ORE" not in j:
            miss.append("event")
    elif task.startswith("port"):
        props = (root / "gradle.properties").read_text(encoding="utf-8")
        if "minecraft_version=1.21.4" not in props:
            miss.append("not on 1.21.4")
        # 1.21.4 renders items from item model definitions in assets/<ns>/items/
        if not find(root, "assets/villagerswarm/items/ruby_block.json"):
            miss.append("item model definition")
        if not find(root, "assets/villagerswarm/blockstates/ruby_block.json"):
            miss.append("blockstate")
    elif task == "zombie-torch":
        if "Goal" not in j or "TORCH" not in j:
            miss.append("goal")
    if "@Mixin" in j:
        cfgs = find(root, "*.mixins.json")
        mod = jload(root / RES / "fabric.mod.json") or {}
        if not cfgs or not mod.get("mixins"):
            miss.append("mixin config not registered")
    return miss


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout + p.stderr


def main() -> None:
    bench = Path(sys.argv[1])
    boot = "--no-boot" not in sys.argv
    rows = []
    for d in sorted(p for p in bench.iterdir() if p.is_dir()):
        task, _, arm = d.name.rpartition("-")
        att = [json.loads(l) for l in (d / "bench-attempts.jsonl").read_text().splitlines()] \
            if (d / "bench-attempts.jsonl").is_file() else []
        code, _ = run([sys.executable, "build.py", "compile"], d)
        boot_ok = None
        if boot and code == 0:
            env_java = jload(d / "bench-env.json") or {}
            import os
            env = dict(os.environ, JAVA_HOME=env_java.get("java_home", os.environ.get("JAVA_HOME", "")))
            p = subprocess.run([sys.executable, str(MCBUILD), "server", "--accept-eula", "--timeout", "600"],
                               cwd=d, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
            boot_ok = p.returncode == 0
            (d / "bench-boot.log").write_text(p.stdout + p.stderr, encoding="utf-8")
        miss = check(task, d)
        rows.append({"task": task, "arm": arm, "builds": len(att),
                     "first_ok": bool(att) and att[0]["ok"], "compiles": code == 0,
                     "boots": boot_ok, "missing": miss,
                     "pass": code == 0 and boot_ok is not False and not miss})
    (bench / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("| task | arm | builds | first build green | compiles | server boots | missing | pass |")
    print("|---|---|---|---|---|---|---|---|")
    yn = {True: "yes", False: "no", None: "-"}
    for r in rows:
        print(f"| {r['task']} | {r['arm']} | {r['builds']} | {yn[r['first_ok']]} | {yn[r['compiles']]} | "
              f"{yn[r['boots']]} | {', '.join(r['missing']) or '-'} | {yn[r['pass']]} |")
    for arm in ("plain", "smith"):
        rs = [r for r in rows if r["arm"] == arm]
        if rs:
            print(f"\n{arm}: {sum(r['pass'] for r in rs)}/{len(rs)} pass, "
                  f"{sum(r['first_ok'] for r in rs)}/{len(rs)} first build green, "
                  f"{sum(r['builds'] for r in rs) / len(rs):.1f} builds per task")


if __name__ == "__main__":
    main()
