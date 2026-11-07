# mixinsmith

Instructions for coding agents working in a Minecraft mod project (Fabric or NeoForge, any version).

1. Start every modding task with `skills/mc-project-detect/SKILL.md`.
2. Before using any `net.minecraft.*`, `com.mojang.*`, `net.fabricmc.*` or `net.neoforged.*` class,
   method or field, follow `skills/mc-source-lookup/SKILL.md` and look it up in the project's own jars.
   Do not write Minecraft API calls from memory.
