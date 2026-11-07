---
description: Port the current mod to another Minecraft version
argument-hint: "<target Minecraft version>"
---

Port this mod to Minecraft $ARGUMENTS.

Follow the `mc-port-version` skill step by step. Ask for the target version if none was given. Stop
and ask before updating build files if the jump crosses more than one major release (for example
1.19 to 1.21) to agree on doing it in steps.

Report at the end: versions before and after, renames applied, errors fixed by hand, and the
`mcbuild.py server` result.
