---
name: mc-project-detect
description: Identify a Minecraft mod project's loader (Fabric or NeoForge), Minecraft version, mappings and Java version before planning or writing mod code. Use at the start of any Minecraft modding task, when opening an unfamiliar mod repo, or when the user asks to create, port or debug a mod.
---

# Minecraft project detect

Run this first. Every later decision (class names, registration style, file layout) depends on it.

```
python ../mc-source-lookup/scripts/mcsrc.py detect
```

It prints JSON: `loader`, `minecraft_version`, `mappings`, `java`, `loader_version` and the jars that
`mc-source-lookup` will read. Say the result back to the user in one line, for example
"Fabric 1.21.1, Yarn mappings, Java 21".

## What the fields change

| Field | Consequence |
|-------|-------------|
| `loader: fabric` | Entry points in `fabric.mod.json`, events from Fabric API (`net.fabricmc.fabric.api.*`), mixins are the main tool. |
| `loader: neoforge` | Entry point is the `@Mod` class, events on the mod or game event bus, metadata in `META-INF/neoforge.mods.toml`. |
| `mappings: yarn` | Yarn names (`LivingEntity#damage`, `Identifier`). Never paste Mojang-named code. |
| `mappings: mojang*` | Official names (`LivingEntity#hurt`, `ResourceLocation`). Parchment adds parameter names only. |
| `java` | Language level you may use. 8 for 1.16 and older, 16 for 1.17, 17 for 1.18 to 1.20.4, 21 for 1.20.5 to 1.21.x. For newer versions trust the detected value. |

Names differ per mappings set and per version. Do not translate between them from memory: look each
name up with `mc-source-lookup`.

## If detection says `unknown`

Read `build.gradle(.kts)` and `settings.gradle(.kts)` yourself. Architectury or multi-loader templates
keep each loader in a subproject (`fabric/`, `neoforge/`): run detect with `--project fabric` etc.
