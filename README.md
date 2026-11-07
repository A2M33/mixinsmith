# mixinsmith

Your coding agent remembers the Minecraft API of some old version. Your mod targets a different one, so
the agent writes `damage()` where your mappings say `hurt()`, invents methods that never existed, and you
burn a build cycle on every guess.

mixinsmith gives the agent the API of *your* project. A small script reads the named Minecraft, Fabric
API and NeoForge jars that Gradle already downloaded and prints real signatures, plus the exact descriptor
a mixin needs:

```
$ python mcsrc.py method LivingEntity#damage
public boolean damage(DamageSource source, float amount)
  mixin target: damage(Lnet/minecraft/entity/damage/DamageSource;F)Z
  full:         Lnet/minecraft/entity/LivingEntity;damage(Lnet/minecraft/entity/damage/DamageSource;F)Z
```

Works with Fabric (1.14+, Yarn or Mojang mappings) and NeoForge (1.20.2+). Needs Python 3.9+ and nothing else.

## Install

Claude Code:

```
/plugin marketplace add A2M33/mixinsmith
/plugin install mixinsmith@mixinsmith
```

Codex, Cursor and other agents: copy `skills/` into your agent's skills folder and point it at `AGENTS.md`.

## Status

Early. Source lookup and project detection work. Build loop, crash diagnosis, version porting and
agent roles come next.

## License

MIT
