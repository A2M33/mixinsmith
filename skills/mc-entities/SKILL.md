---
name: mc-entities
description: Create or change entities and mob behavior in a Fabric or NeoForge mod: custom mobs, AI goals, brains, attributes, spawning, renderers and models. Use for "add a mob", "make X follow/attack/flee", or changes to how vanilla mobs behave.
---

# Entities and mob AI

## Pick the closest vanilla mob and copy its shape

`mcsrc.py class ZombieEntity --inherited` (Yarn) or `Zombie` (Mojang) lists everything a mob class
overrides. `mcsrc.py source <Mob>#initGoals` (`registerGoals` in Mojang names) shows how it sets up AI.
Find the method names for this version that way, never from memory.

## Two AI systems

- **Goals** (`GoalSelector`): most hostile and simple mobs. Add a goal class extending the goal base
  class with a priority. Check names: `mcsrc.py search 'Goal$'`.
- **Brain** (memories, sensors, activities): villagers, piglins, axolotls, frogs, wardens, allays.
  Do not add goals to brain mobs; they ignore the goal selector. Write memories instead, e.g. set a walk
  target memory. Look at how vanilla tasks do it: `mcsrc.py search 'Task$|Behavior$'`.

To change a vanilla mob, prefer an event (entity load / spawn / tick) that adds goals or memories over a
mixin into its constructor.

## A new mob needs

1. Entity class + `EntityType` registration (copy the builder chain from a vanilla entry in
   `EntityType` with `mcsrc.py source EntityType`).
2. Default attributes registration: Fabric `FabricDefaultAttributeRegistry`, NeoForge
   `EntityAttributeCreationEvent`. A living entity without attributes crashes on spawn.
3. Client: renderer + model registration in client-only code, model layer, texture under
   `assets/<modid>/textures/entity/`.
4. Spawn egg, spawn rules / biome modifications if it spawns naturally, loot table, lang entries.

## Verify

`mcbuild.py compile` and `mcbuild.py server`. Behavior needs the client: ask the user to run
`./gradlew runClient`, spawn the mob and report what it does.
