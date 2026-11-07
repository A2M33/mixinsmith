---
name: mc-mixins
description: Write, review or fix Mixin classes in Fabric or NeoForge mods (@Inject, @ModifyArg, @ModifyVariable, @Redirect, MixinExtras @WrapOperation / @ModifyExpressionValue, @Shadow, @Accessor, @Invoker). Use when a feature needs to change vanilla behavior that no loader event covers, or when a mixin fails to apply.
---

# Mixins

## Before writing one

1. **Look for an event first.** Fabric API (`net.fabricmc.fabric.api.*`) and NeoForge events cover
   damage, block breaking, item use, ticking, loot, commands and more. Search with
   `mcsrc.py search 'Events$|Event$'` and prefer the event: it survives updates and cannot conflict
   with other mods.
2. **Read the target.** `mcsrc.py method Class#name` gives the exact descriptor;
   `mcsrc.py source Class#name` shows the body so you can pick the injection point.
3. **Need a private field or method only?** Use an accessor or invoker (below), or an access widener
   (Fabric) / access transformer (NeoForge). No injection required.

## Picking the injector

| Goal | Use |
|------|-----|
| Run code at the start or end of a method, maybe cancel it | `@Inject` at `HEAD` / `RETURN` / `TAIL` |
| Change one argument passed to a call inside the method | `@ModifyArg` |
| Change a local variable | `@ModifyVariable` |
| Change the value a call or field read returns | `@ModifyExpressionValue` (MixinExtras) |
| Wrap a call, run it conditionally or with other args | `@WrapOperation` / `@WrapWithCondition` (MixinExtras) |
| Replace a call outright | `@Redirect`, last resort: two mods redirecting the same call crash |

MixinExtras ships with Fabric Loader 0.15+ and with NeoForge, so you can use it without a dependency.
Prefer it over `@Redirect` and `@Overwrite`. Never use `@Overwrite`.

## Templates

Fill every `method` and `target` from `mcsrc.py` output. The names below are placeholders.

```java
@Mixin(TargetClass.class)
public abstract class TargetClassMixin {
    // void method: CallbackInfo. Non-void: CallbackInfoReturnable<ReturnType>.
    @Inject(method = "name(Lpkg/Arg;F)Z", at = @At("HEAD"), cancellable = true)
    private void mymod$beforeName(Arg arg, float f, CallbackInfoReturnable<Boolean> cir) {
        if (shouldBlock(arg)) cir.setReturnValue(false); // cancels the method
    }

    @ModifyExpressionValue(method = "name(Lpkg/Arg;F)Z",
        at = @At(value = "INVOKE", target = "Lpkg/Owner;called()I"))
    private int mymod$changeResult(int original) {
        return original * 2;
    }
}
```

Handler parameters are the target method's parameters in order, then the callback info. With a
mismatch the mixin fails at load time, after a clean compile.

### Accessing private members

```java
@Mixin(TargetClass.class)
public interface TargetClassAccessor {
    @Accessor("fieldName") int mymod$getFieldName();
    @Invoker("methodName") void mymod$callMethodName(Arg arg);
}
// use: ((TargetClassAccessor) target).mymod$getFieldName()
```

Inside a mixin class, reach target members with `@Shadow` (same name and type as `mcsrc.py field`
reports). Add your own fields and methods with `@Unique`.

## Rules

- Prefix every handler, `@Unique` member and accessor with your mod id (`mymod$...`) so names never
  collide with another mod's mixin into the same class.
- Mixin classes are `abstract`, live in their own package (`com.example.mymod.mixin`) and are never
  referenced from normal code except through accessor/duck interfaces.
- Register every mixin in the mixin config (`mymod.mixins.json`): common ones in `"mixins"`,
  client-only ones in `"client"`. Fabric lists the config in `fabric.mod.json` (`"mixins"`), NeoForge
  in `META-INF/neoforge.mods.toml` (`[[mixins]] config = "mymod.mixins.json"`).
- Client classes (`MinecraftClient`/`Minecraft`, renderers, screens) only in `"client"`, or the
  dedicated server crashes.

## After writing

Run `mcbuild.py compile`, then `mcbuild.py server` (mixins apply at load time). A
`could not find any targets` error means the method name or descriptor is wrong: look it up again,
do not guess a different name.
