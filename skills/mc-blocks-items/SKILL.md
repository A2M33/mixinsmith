---
name: mc-blocks-items
description: Add or change blocks, items, block entities, creative tabs, recipes, models, textures and translations in a Fabric or NeoForge mod. Use for any "add a block/item/tool/food/armor" request or when an item shows as a missing texture or "Item id not set" crash.
---

# Blocks and items

Registration code, model JSON layout and item data change across versions more than anything else.
Find the right shape for *this* project, then copy it.

## 1. Find the pattern in this version

- Read how vanilla does it: `mcsrc.py source Items` (or `Blocks`) and copy the shape of a similar
  vanilla entry, e.g. `Items#DIAMOND_SWORD`. Vanilla always matches the project's version.
- Registry access: `mcsrc.py search '^Registries$|^BuiltInRegistries$|^Registry$'`.
- NeoForge registers through `DeferredRegister`: `mcsrc.py class DeferredRegister` and its nested
  classes show the helpers this version offers.
- Settings builder: `mcsrc.py class Item.Settings` (Yarn) or `Item.Properties` (Mojang).

## 2. Version cliffs to check

| Version | Change | What breaks if you ignore it |
|---------|--------|------------------------------|
| 1.19.3 | Registries moved to `Registries` / `BuiltInRegistries` | `Registry.ITEM` no longer exists |
| 1.20.5 | Item NBT replaced by data components | `getNbt()`/`getTag()` style code fails to compile |
| 1.21 | Resource id constructor made private | use the static factory (`Identifier.of` / `ResourceLocation.fromNamespaceAndPath`) |
| 1.21.2 | Item and block settings need their registry key before construction | crash "Item id not set" / "Block id not set" at startup |
| 1.21.4 | Item model definitions in `assets/<modid>/items/<name>.json` | item renders as the purple-black missing texture |

Verify each against the project with a lookup instead of trusting the table blindly.

## 3. Files per new item or block

- Java: registration, plus the block/item class if it has behavior.
- `assets/<modid>/lang/en_us.json`: `item.<modid>.<name>` / `block.<modid>.<name>`.
- Models, blockstates and textures: `mcsrc.py files 'diamond_sword|oak_planks'` shows every file
  vanilla uses for a similar item or block in this version; `mcsrc.py cat <path>` prints each one.
  Mirror the same paths under your mod id.
- Recipes, loot tables and tags: same approach. Folder names changed between versions (`recipe/` vs
  `recipes/`), so copy the folders the `files` output shows.
- Creative tab entry, or the item is unreachable without commands.

## 4. Verify

`mcbuild.py compile`, then `mcbuild.py server` (registration errors happen at startup). Missing
textures only show in the client: ask the user to run `./gradlew runClient` and check.
