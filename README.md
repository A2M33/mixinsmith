![mixinsmith banner: two real lookups in a terminal. In a NeoForge 1.21.1 Parchment project, mcsrc.py method LivingEntity#hurt prints public boolean hurt(DamageSource source, float amount); in a Fabric 1.21.1 Yarn project, LivingEntity#damage prints the same method as damage, with its mixin target. A callout on that line says the descriptor is read from the jars Gradle already downloaded.](assets/banner.png)

# mixinsmith

[![test](https://img.shields.io/github/actions/workflow/status/A2M33/mixinsmith/test.yml?label=test&style=flat-square&labelColor=111a2d&color=22304b)](https://github.com/A2M33/mixinsmith/actions/workflows/test.yml)

Your coding agent remembers the Minecraft API of some old version. Your mod targets a different one, so
the agent writes `damage()` where your mappings say `hurt()`, invents methods that never existed, and you
burn a build cycle on every guess.

![A mixin aimed at the Mojang name hurt compiles, crashes the server, and mcsrc points to Entity#damage, after which the server boots](assets/demo.gif)

mixinsmith gives the agent the API of *your* project. A small script reads the named Minecraft, Fabric
API and NeoForge jars that Gradle already downloaded and prints real signatures, plus the exact descriptor
a mixin needs:

```
$ python mcsrc.py method LivingEntity#damage
public boolean damage(DamageSource source, float amount)
  mixin target: damage(Lnet/minecraft/entity/damage/DamageSource;F)Z
  full:         Lnet/minecraft/entity/LivingEntity;damage(Lnet/minecraft/entity/damage/DamageSource;F)Z
```

Pasted a snippet written for Mojang names into a Yarn project? `translate` maps it for you:

```
$ python mcsrc.py method LivingEntity#hurt
mcsrc: LivingEntity has no method 'hurt' (searched the class and its supertypes).
In yarn mappings (this project) that name is: Entity#damage
```

The build loop catches what compiles but breaks at startup, like a mixin aimed at a method that does
not exist:

```
$ python mcbuild.py server
FAILED
MIXIN: mixin target not found: Critical injection failure: @Inject annotation on mymod$onHurt
       could not find any targets matching 'hurt' in net/minecraft/entity/LivingEntity.
  -> check the target: mcsrc.py method net.minecraft.entity.LivingEntity#hurt
```

Targets Fabric (1.14+, Yarn or Mojang mappings) and NeoForge (1.20.2+). Needs Python 3.9+ and nothing else.

## What's inside

| Piece | Does |
|-------|------|
| `mc-source-lookup` | `mcsrc.py`: classes, methods, fields, decompiled source, vanilla JSON resources, Mojang/Yarn translation |
| `mc-build-loop` | `mcbuild.py`: compile, build, boot a dedicated server, summarize crash reports |
| `mc-port-version` | `mcport.py`: every class and member a version bump renames or removes, where your mod uses it, import rewrites |
| `mc-project-detect` | loader, Minecraft version, mappings and Java version of the project |
| `mc-mixins`, `mc-blocks-items`, `mc-entities` | how to build each kind of feature for the version you are on |
| agents | `mod-designer`, `mixin-specialist`, `entity-specialist`, `asset-builder`, `mod-reviewer` |
| commands | `/new-mod`, `/fix-crash`, `/port-version` |

## Install

Claude Code:

```
/plugin marketplace add A2M33/mixinsmith
/plugin install mixinsmith@mixinsmith
```

Codex, Cursor and other agents: clone this repo and point your agent at `AGENTS.md`. If you copy
`skills/` somewhere else, fix the paths in `AGENTS.md` to match.

The scripts run on Windows, macOS and Linux. Where `python` is missing, use `python3`.

## Status

Early. Tested on Fabric 1.21.1 (Yarn) and NeoForge 1.21.1 (ModDevGradle with Parchment); ports checked
between 1.20.4, 1.21.1 and 1.21.4. The benchmark harness lives in `bench/`, with no results published yet.

## Development

```
python -m unittest discover -s tests
```

The class-file tests compile small Java fixtures and skip themselves when no JDK is on `PATH` or in
`JAVA_HOME`. CI runs the suite on Windows, macOS and Linux.

## License

MIT
