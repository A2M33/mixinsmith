---
name: mc-build-loop
description: Compile, build or boot a Minecraft mod (Fabric or NeoForge) and get a short diagnosis of compile errors, mixin failures, missing dependencies and crash reports. Use after every code change to a mod, when the user reports a crash or a build failure, or when you need to prove a mod loads.
---

# Minecraft build loop

Never tell the user a mod change works until this loop passes. Raw Gradle output runs to hundreds of
lines; the script keeps the parts that matter. It is `scripts/mcbuild.py` in this skill's folder; run it
with the mod project as the working directory or pass `--project <dir>`.

```
python scripts/mcbuild.py compile          # compileJava only: run after each edit
python scripts/mcbuild.py build            # full build incl. remap/jar: run before you finish
python scripts/mcbuild.py server           # boot a dedicated server, stop when the world loads
python scripts/mcbuild.py crash [file]     # summarize the newest crash report under run/ or runs/
python scripts/mcbuild.py log <file>       # diagnose a log the user pasted into a file
```

Add `--raw` to see the last 80 log lines too. Exit code 0 means success.

## Loop

1. `compile`. On `COMPILE ERRORS`, look up every name in "Unknown symbols" with `mc-source-lookup`
   before you change code. A missing symbol almost always means the name differs in this
   version or mappings, so do not rename it from memory.
2. Repeat until `COMPILE OK`, then `build`.
3. If the change touches mixins, registration, entities, data files or anything that runs at startup,
   run `server`. Mixins apply at load time, so a clean compile proves nothing about them.
4. On `MIXIN:` lines, re-check the target with `mcsrc.py method Class#name` and the injection point with
   `mcsrc.py source Class#name`.

## The server check and the EULA

A dedicated server only starts after someone accepts the Minecraft EULA (https://aka.ms/MinecraftEULA).
The script refuses without it. Ask the user once. If they agree, run
`mcbuild.py server --accept-eula`; it writes `eula=true` into the run directory and later runs reuse it.
Client-only code (rendering, screens, keybinds) does not run on a server; for those, ask the user to
start `./gradlew runClient` and paste the result or the crash file.

## Java version

A `JAVA:` line means Gradle could not start on the current JDK. Gradle needs a JDK that satisfies both
the Gradle plugin and Gradle itself:

- "JAVA_HOME is not set": no JDK found. Point `JAVA_HOME` at one.
- "Dependency requires at least JVM runtime version N": the plugin (Fabric Loom 1.19 needs 25)
  wants JDK N or newer.
- "Unsupported class file major version N": the JDK is too new for this Gradle version (JDK 25 needs
  Gradle 9.1 or newer). Use an older JDK, such as 21.

Minecraft compiles against the toolchain version in `build.gradle`, so the JDK that runs Gradle may be
newer than the one Minecraft targets.
