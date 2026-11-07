---
description: Create a new Fabric or NeoForge mod project for any Minecraft version
argument-hint: "<fabric|neoforge> <minecraft version> <mod id> [what the mod should do]"
---

Create a new mod project: $ARGUMENTS

Ask for anything missing among loader, Minecraft version and mod id (lowercase, `[a-z0-9_]`, 2 to 64
characters). Do not pick a version yourself.

Start from the official template so the build files match the version, never from memory:

- **NeoForge**: clone `https://github.com/NeoForgeMDKs/MDK-<version>-ModDevGradle` (for example
  `MDK-1.21.1-ModDevGradle`). If that repo does not exist, list the org's repos and pick the matching one.
- **Fabric**: clone `https://github.com/FabricMC/fabric-example-mod`, check out the branch for the
  version if one exists, then set `minecraft_version`, `yarn_mappings`, `loader_version` and
  `fabric_api_version` in `gradle.properties` from `https://meta.fabricmc.net/v2/versions/` (game,
  yarn and loader endpoints) and the Fabric API Maven metadata at
  `https://maven.fabricmc.net/net/fabricmc/fabric-api/fabric-api/maven-metadata.xml`.

Then:
1. Delete the template's `.git`, rename the package, mod id, mod name and entry classes to the user's
   values (`fabric.mod.json` or `META-INF/neoforge.mods.toml` included), and run `git init`.
2. Run `mc-project-detect` and confirm the result matches the request.
3. Run `mcbuild.py compile`. Gradle downloads Minecraft on the first run, which takes a few minutes.
4. If the user described features, build them with lookups from `mc-source-lookup` and finish with the
   build loop.
5. Report the project path, the detected setup and how to start the game (`./gradlew runClient`).
