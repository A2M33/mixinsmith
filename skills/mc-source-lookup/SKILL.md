---
name: mc-source-lookup
description: Look up the real Minecraft, Fabric API or NeoForge API of the current mod project before writing code against it. Use whenever you are about to call, override, mixin into or reference any net.minecraft.*, com.mojang.*, net.fabricmc.* or net.neoforged.* class, method or field, when a build fails with "cannot find symbol" / "method does not override", or when a mixin fails to apply. Works on any Minecraft version the project uses.
---

# Minecraft source lookup

Your memory of the Minecraft API is wrong for most versions. Method names, parameters and whole classes
change between releases and between mappings (Yarn vs Mojang). The project already has the correct,
named Minecraft jar on disk. Read it instead of guessing.

## Rule

Before you write code that touches a vanilla or loader API, run a lookup for every class and member you
use. If the lookup says the member does not exist, it does not exist in this project: pick from the
"Similar" list or search. Never fall back to what you remember.

## Commands

The script lives next to this file. Run it from the mod project root (or pass `--project <dir>`).

```
python scripts/mcsrc.py detect                         # loader, MC version, mappings, Java, jars
python scripts/mcsrc.py class LivingEntity             # fields + methods with generic types
python scripts/mcsrc.py class LivingEntity --inherited # include every supertype
python scripts/mcsrc.py method LivingEntity#damage     # overloads + mixin descriptor
python scripts/mcsrc.py field LivingEntity#lastDamageTaken
python scripts/mcsrc.py search 'BlockBreak' [--members] # regex over class (and method) names
python scripts/mcsrc.py source LivingEntity#damage     # decompiled body, needs a sources jar
python scripts/mcsrc.py files 'diamond_sword'          # resource paths (assets/, data/) in the jars
python scripts/mcsrc.py cat data/minecraft/recipe/diamond_sword.json  # vanilla JSON for this version
```

Model, blockstate, recipe, loot table and tag formats change between versions too. Copy the vanilla
file from `cat` instead of writing JSON from memory.

`Class` accepts a simple name (`Entity`), a nested name (`PlayerBlockBreakEvents.Before`) or a full name
(`net.minecraft.entity.Entity`). When several classes share a name, the script uses the vanilla
top-level one and lists the others on stderr; pass the full name to pick another.

## Using the output

- **Calling or overriding**: copy the signature exactly. `method` reports where a member is declared;
  override in the subclass you extend, with the same parameter types.
- **Mixins**: put the `mixin target` string in `@Inject(method = "...")`, `@Redirect`, `@ModifyArg` etc.
  Use the `full` form for `@At(value = "INVOKE", target = "...")`. Field targets use `name:descriptor`.
- **Bodies**: `source` prints the decompiled method so you can choose an injection point (`HEAD`,
  `RETURN`, an `INVOKE` inside it). Without a sources jar, Fabric needs `./gradlew genSources`; NeoForge
  ModDevGradle writes one during setup.

## When it cannot find jars

The toolchain creates the named jar on first setup. Run `./gradlew compileJava` (NeoForge) or
`./gradlew build` (Fabric) once, then retry. The first lookup indexes the jars (a few seconds); later
lookups read the cache in `.gradle/mixinsmith/`.
