---
name: mc-port-version
description: Port a Fabric or NeoForge mod from one Minecraft version to another. Lists every class and member the bump renames or removes, shows where the mod uses them, and rewrites renamed imports. Use when the user asks to update, port or "make it work on" another Minecraft version.
---

# Port to another Minecraft version

```
python scripts/mcport.py --from 1.21.1 --to 1.21.4               # report for ./src
python scripts/mcport.py --from 1.21.1 --to 1.21.4 --apply-imports
python scripts/mcport.py --from 1.21.1 --to 1.21.4 --all         # include ambiguous member names
python scripts/mcport.py --from 1.20.4 --to 1.21.1 --summary     # size of the jump only
```

It joins both versions' mappings on intermediary names, which never change, so a rename it reports is
real. It reads the project's mappings set (Yarn or Mojang) from the build files; pass `--ns` to force one.
Mappings download once per version into `~/.cache/mixinsmith/`.

## Steps

1. `mc-project-detect`, note the current version. Commit or stash first so the port is one reviewable diff.
2. `--summary` for the size of the jump. Several big releases at once: port one step at a time
   (1.20.4 -> 1.20.6 -> 1.21.1), since each step's errors are easier to read.
3. Update the build: `minecraft_version`, mappings, loader, Fabric API / NeoForge versions and the Java
   toolchain. Take version numbers from the sources `/new-mod` lists, never from memory.
4. Run the build once so Gradle sets up the new Minecraft, then `mcport.py ... --apply-imports`.
5. Fix the reported member renames. Look up each new name with `mcsrc.py method` first: mappings
   show the new name, not changed parameters or behavior.
6. Loop `mcbuild.py compile` until clean. Remaining errors are signature or behavior changes: read the
   new code with `mcsrc.py source` and the version cliffs table in `mc-blocks-items`.
7. Port data and assets: compare folders with `mcsrc.py files` (recipe, loot table, model and tag
   folders moved between versions).
8. `mcbuild.py server`, then ask the user to test in the client.

## Limits

Mappings carry names only. Constructors made private, new parameters, removed overloads and moved
logic show up as compile errors in step 6, not in the report.
