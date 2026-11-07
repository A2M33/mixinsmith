---
description: Diagnose and fix a Minecraft mod crash or build failure
argument-hint: "[crash file, log file, or a description]"
---

Fix the crash or build failure the user describes: $ARGUMENTS

1. Run `mc-project-detect`.
2. Get a diagnosis with `mc-build-loop`:
   - a crash file or log path in the arguments: `mcbuild.py crash <file>` or `mcbuild.py log <file>`
   - nothing given: `mcbuild.py crash` for the newest report, otherwise `mcbuild.py compile`
3. Find the cause in the user's mod code, not in Minecraft or the loader. Frames under the mod's own
   package and the "Suspected mods" line point to it. If the crash comes from a different mod, say so
   and stop.
4. Look up every Minecraft or loader member involved with `mc-source-lookup` before editing.
5. Fix it with the smallest change, then run the build loop again (`compile`, then `server` if the crash
   happened at startup) until it passes.
6. Tell the user the cause in one sentence, what you changed, and how you verified it.
