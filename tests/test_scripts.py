"""Tests for mcsrc.py, mappings.py and mcbuild.py. Standard library only.

Run: python -m unittest discover -s tests
Class-file tests compile small Java fixtures and skip when no `javac` is on PATH (or in JAVA_HOME).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/mc-source-lookup/scripts"))
sys.path.insert(0, str(ROOT / "skills/mc-build-loop/scripts"))

import mappings  # noqa: E402
import mcbuild  # noqa: E402
import mcsrc  # noqa: E402


def javac() -> str | None:
    home = os.environ.get("JAVA_HOME")
    if home:
        for n in ("javac", "javac.exe"):
            p = Path(home) / "bin" / n
            if p.is_file():
                return str(p)
    return shutil.which("javac")


JAVA = {
    "net/minecraft/entity/Entity.java": """
        package net.minecraft.entity;
        public class Entity {
            protected int age;
            public boolean damage(Object source, float amount) { return true; }
            public static <T extends Comparable<T>> T pick(java.util.List<? extends T> xs, String... tags) { return null; }
            public static class Inner { public void tick() {} }
        }
    """,
    "net/minecraft/entity/LivingEntity.java": """
        package net.minecraft.entity;
        public abstract class LivingEntity extends Entity {
            protected float lastDamageTaken;
            private final java.util.Map<String, java.util.List<Integer>> effects = null;
            public abstract void wakeUp();
        }
    """,
    "net/minecraft/client/render/debug/Entity.java": """
        package net.minecraft.client.render.debug;
        public class Entity {}
    """,
}


@unittest.skipUnless(javac(), "javac not found")
class ClassFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / "src"
        for rel, code in JAVA.items():
            p = src / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textwrap.dedent(code), encoding="utf-8")
        out = cls.tmp / "classes"
        subprocess.run([javac(), "-parameters", "-d", str(out)] + [str(src / r) for r in JAVA],
                       check=True, capture_output=True)
        cls.jar = str(cls.tmp / "minecraft.jar")
        with zipfile.ZipFile(cls.jar, "w") as z:
            for f in out.rglob("*.class"):
                z.write(f, f.relative_to(out).as_posix())
            z.writestr("data/minecraft/recipe/stick.json", '{"type": "minecraft:crafting_shaped"}')
        cls.idx = mcsrc.load_index(cls.tmp, [cls.jar])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def method(self, owner, name):
        k = self.idx["classes"][owner]
        return next(m for m in k["methods"] if m[1] == name)

    def test_signature_and_mixin_descriptor(self):
        m = self.method("net/minecraft/entity/Entity", "damage")
        self.assertEqual(mcsrc.fmt_method("net/minecraft/entity/Entity", m),
                         "public boolean damage(Object source, float amount)")
        self.assertEqual(m[2], "(Ljava/lang/Object;F)Z")

    def test_generics_and_varargs(self):
        m = self.method("net/minecraft/entity/Entity", "pick")
        self.assertEqual(mcsrc.fmt_method("net/minecraft/entity/Entity", m),
                         "public static <T extends Comparable<T>> T pick(List<? extends T> xs, String... tags)")
        f = next(f for f in self.idx["classes"]["net/minecraft/entity/LivingEntity"]["fields"] if f[1] == "effects")
        self.assertEqual(mcsrc.fmt_field(f), "private final Map<String, List<Integer>> effects")

    def test_resolution_prefers_vanilla_top_level(self):
        self.assertEqual(mcsrc.resolve(self.idx, "Entity")[0], "net/minecraft/entity/Entity")
        self.assertEqual(mcsrc.resolve(self.idx, "Entity.Inner"), ["net/minecraft/entity/Entity$Inner"])
        self.assertEqual(mcsrc.resolve(self.idx, "LivingEntity"), ["net/minecraft/entity/LivingEntity"])

    def test_inherited_lookup(self):
        chain = mcsrc.supers(self.idx, "net/minecraft/entity/LivingEntity")
        self.assertEqual(chain[:2], ["net/minecraft/entity/LivingEntity", "net/minecraft/entity/Entity"])

    def test_resources(self):
        with zipfile.ZipFile(self.jar) as z:
            self.assertIn("data/minecraft/recipe/stick.json", z.namelist())


TINY = "\n".join([
    "tiny\t2\t0\tofficial\tintermediary\tnamed",
    "c\tbwf\tnet/minecraft/class_1309\tnet/minecraft/entity/LivingEntity",
    "\tf\tF\tbl\tfield_6253\tlastDamageTaken",
    "c\tbsr\tnet/minecraft/class_1297\tnet/minecraft/entity/Entity",
    "\tm\t(Lcxz;F)Z\ta\tmethod_5643\tdamage",
    "c\tcxz\tnet/minecraft/class_1282\tnet/minecraft/entity/damage/DamageSource",
    "c\takr\tnet/minecraft/class_2960\tnet/minecraft/util/Identifier",
])
PROGUARD = "\n".join([
    "# comment",
    "net.minecraft.world.entity.LivingEntity -> bwf:",
    "    float lastHurt -> bl",
    "net.minecraft.world.entity.Entity -> bsr:",
    "    1:5:boolean hurt(net.minecraft.world.damagesource.DamageSource,float) -> a",
    "net.minecraft.world.damagesource.DamageSource -> cxz:",
    "net.minecraft.resources.ResourceLocation -> akr:",
])


class MappingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old_cache = mappings.CACHE
        mappings.CACHE = self.tmp
        (self.tmp / "9.9").mkdir()
        (self.tmp / "9.9" / "client.txt").write_text(PROGUARD, encoding="utf-8")
        (self.tmp / "9.9" / "yarn.tiny").write_text(TINY, encoding="utf-8")
        self._orig_yarn = mappings.yarn_tiny
        mappings.yarn_tiny = lambda mc, project_root=None: TINY  # ignore any real Loom cache
        self.table = mappings.build_table("9.9")

    def tearDown(self):
        mappings.CACHE = self.old_cache
        mappings.yarn_tiny = self._orig_yarn
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_proguard_descriptor_uses_official_names(self):
        _, mem = mappings.parse_proguard(PROGUARD)
        self.assertEqual(mem[("bsr", "m", "a", "(Lcxz;F)Z")], "hurt")

    def test_method_mojang_to_yarn(self):
        rows = mappings.translate(self.table, "Entity#hurt")
        self.assertEqual([(r["yarn"], r["mojang"]) for r in rows], [("damage", "hurt")])

    def test_inherited_member_falls_back_to_any_owner(self):
        rows = mappings.translate(self.table, "LivingEntity#hurt")
        self.assertEqual(rows[0]["owner_yarn"], "net/minecraft/entity/Entity")

    def test_field_and_class(self):
        self.assertEqual(mappings.translate(self.table, "LivingEntity#lastHurt")[0]["yarn"], "lastDamageTaken")
        cls = mappings.translate(self.table, "ResourceLocation")[0]
        self.assertEqual(cls["yarn"], "net/minecraft/util/Identifier")
        self.assertTrue(mappings.cached("9.9"))


class DetectTests(unittest.TestCase):
    def project(self, files: dict[str, str]) -> Path:
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        for name, text in files.items():
            (d / name).write_text(textwrap.dedent(text), encoding="utf-8")
        return d

    def test_fabric_yarn(self):
        d = self.project({
            "build.gradle": "plugins { id 'net.fabricmc.fabric-loom-remap' version '1.19' }\n"
                            "dependencies { mappings \"net.fabricmc:yarn:${project.yarn_mappings}:v2\" }\n"
                            "java { toolchain { languageVersion = JavaLanguageVersion.of(21) } }",
            "gradle.properties": "minecraft_version=1.21.1\nyarn_mappings=1.21.1+build.3\nloader_version=0.16.0",
        })
        info = mcsrc.detect(d)
        self.assertEqual((info["loader"], info["mappings"], info["minecraft_version"], info["java"]),
                         ("fabric", "yarn", "1.21.1", 21))

    def test_neoforge_moddev_parchment(self):
        d = self.project({
            "build.gradle": "plugins { id 'net.neoforged.moddev' version '2.0.148' }\nneoForge { parchment { } }",
            "gradle.properties": "minecraft_version=1.21.1\nneo_version=21.1.265",
        })
        info = mcsrc.detect(d)
        self.assertEqual((info["loader"], info["plugin"], info["mappings"]),
                         ("neoforge", "moddevgradle", "mojang+parchment"))


class DiagnoseTests(unittest.TestCase):
    def test_javac_errors_windows_paths_deduped(self):
        log = "\n".join([
            r"C:\mods\my mod\src\main\java\a\B.java:32: error: cannot find symbol",
            "        villager.stopSleeping();",
            "                ^",
            "  symbol:   method stopSleeping()",
            "  location: variable villager of type VillagerEntity",
            "* What went wrong:",
            r"C:\mods\my mod\src\main\java\a\B.java:32: error: cannot find symbol",
        ])
        out = mcbuild.diagnose(log)
        self.assertEqual(out[0], "COMPILE ERRORS: 1")
        self.assertIn("method stopSleeping()", out[-1])

    def test_mixin_failure_collapsed_with_hint(self):
        msg = ("Critical injection failure: @Inject annotation on mod$onHurt could not find any targets "
               "matching 'hurt' in net/minecraft/entity/LivingEntity. No refMap loaded.")
        log = "\n".join([
            f"[14:25:15] [main/ERROR] (FabricLoader/Mixin) Mixin apply for mod mod failed mod.mixins.json:M "
            f"-> net.minecraft.entity.LivingEntity: InvalidInjectionException {msg}",
            f"Caused by: org.spongepowered.asm.mixin.injection.throwables.InvalidInjectionException: {msg}",
            "\tat org.spongepowered.asm.mixin.Foo.bar(Foo.java:1)",
            "\tat knot/com.example.Mod.init(Mod.java:9) [main/:?]",
            "\t... 18 more",
        ])
        out = mcbuild.diagnose(log)
        mixin = [o for o in out if o.startswith("MIXIN")]
        self.assertEqual(len(mixin), 1)
        self.assertIn("mcsrc.py method net.minecraft.entity.LivingEntity#hurt", "\n".join(out))
        self.assertIn("    at com.example.Mod.init(Mod.java:9)", out)
        self.assertNotIn("more", "\n".join(out))


if __name__ == "__main__":
    unittest.main()
