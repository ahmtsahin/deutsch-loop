from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODEX_ENTRY = ROOT / ".codex-plugin" / "skills" / "deutsch-loop" / "SKILL.md"


def read_json(name: str, folder: str = ".claude-plugin") -> dict:
    return json.loads((ROOT / folder / name).read_text(encoding="utf-8"))


def skill_frontmatter(path: Path = ROOT / "SKILL.md") -> str:
    return path.read_text(encoding="utf-8").split("---")[1]


class PluginManifestTests(unittest.TestCase):
    def test_the_plugin_version_is_the_skill_version(self):
        # Claude Code keeps users on a plugin version until it changes.
        version = re.search(r'^\s+version: "(.+)"$', skill_frontmatter(), re.M).group(1)
        self.assertEqual(read_json("plugin.json")["version"], version)

    def test_the_root_skill_loads_under_its_own_name(self):
        # A root SKILL.md is the plugin's only skill, so no skills folder or key may replace it.
        name = re.search(r"^name: (.+)$", skill_frontmatter(), re.M).group(1)
        manifest = read_json("plugin.json")
        self.assertEqual(manifest["name"], name)
        self.assertNotIn("skills", manifest)
        self.assertFalse((ROOT / "skills").exists())

    def test_the_marketplace_lists_the_tutor_and_its_companion(self):
        # Codex reads this marketplace file too; the tutor stays the first entry.
        entries = read_json("marketplace.json")["plugins"]
        self.assertEqual([(entry["name"], entry["source"]) for entry in entries],
                         [(read_json("plugin.json")["name"], "./"), ("nochmal", "./mods/nochmal")])
        self.assertNotIn("skills", entries[0])


class CompanionManifestTests(unittest.TestCase):
    """The Claude Code companion in mods/nochmal; `claude plugin test mods/nochmal` tests its hooks."""

    FOLDER = ROOT / "mods" / "nochmal"

    def test_the_companion_manifest_names_its_types_and_hooks_module(self):
        manifest = read_json("plugin.json", "mods/nochmal/.claude-plugin")
        self.assertEqual(manifest["name"], "nochmal")
        self.assertTrue((self.FOLDER / manifest["types"]).is_file())
        hooks = json.loads((self.FOLDER / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(hooks, {"modules": ["./register.tsx"]})
        self.assertTrue((self.FOLDER / "hooks" / "register.tsx").is_file())

    def test_the_companion_finds_the_engine_of_the_repository_it_sits_in(self):
        # From mods/nochmal, two folders up is the repository root.
        module = (self.FOLDER / "hooks" / "register.tsx").read_text(encoding="utf-8")
        self.assertIn("join($.plugin.root, '..', '..', 'scripts', 'deutsch_loop.py')", module)
        self.assertTrue((self.FOLDER.parents[1] / "scripts" / "deutsch_loop.py").is_file())

    def test_the_companion_runs_only_read_and_review_commands(self):
        # It reads state and saves reviews; corrections and scenes stay the tutor's.
        module = (self.FOLDER / "hooks" / "register.tsx").read_text(encoding="utf-8")
        commands = set(re.findall(r"cli\(\$, \[(?:current\.kind === 'pattern' \? )?'([a-z-]+)'", module))
        commands |= set(re.findall(r"engineRun\(\$, \['([a-z-]+)'", module))
        commands |= {"grade", "vocab-grade"} if "'grade' : 'vocab-grade'" in module else set()
        self.assertEqual(commands, {"recap", "due", "vocab-due", "list", "show", "scenarios", "roleplay-show",
                                    "grade", "vocab-grade"})


class CodexPluginTests(unittest.TestCase):
    def setUp(self):
        self.manifest = read_json("plugin.json", ".codex-plugin")

    def test_the_codex_manifest_describes_the_same_plugin(self):
        # Codex takes .codex-plugin/plugin.json before the Claude Code manifest.
        claude = read_json("plugin.json")
        for field in ("name", "version", "description"):
            self.assertEqual(self.manifest[field], claude[field], field)

    def test_codex_loads_the_entry_file(self):
        # Codex loads a plugin's skills only from a subfolder, given as a ./ path inside the plugin.
        skills = self.manifest["skills"]
        self.assertTrue(skills.startswith("./"), skills)
        self.assertEqual((ROOT / skills).resolve(), CODEX_ENTRY.parents[1])
        self.assertTrue(CODEX_ENTRY.is_file())

    def test_the_entry_file_carries_the_root_skill_name_and_description(self):
        root, entry = skill_frontmatter(), skill_frontmatter(CODEX_ENTRY)
        for field in ("name", "description"):
            pattern = rf"^{field}: (.+)$"
            self.assertEqual(re.search(pattern, entry, re.M).group(1), re.search(pattern, root, re.M).group(1), field)

    def test_the_entry_file_leads_to_the_root_skill(self):
        # The agent works out the plugin root from the entry file's own path.
        text = CODEX_ENTRY.read_text(encoding="utf-8")
        self.assertIn(f"`<plugin-root>/{CODEX_ENTRY.relative_to(ROOT).as_posix()}`", text)
        self.assertIn("`<plugin-root>/SKILL.md`", text)
        self.assertEqual(CODEX_ENTRY.parents[3], ROOT)

    def test_a_cloned_skill_folder_still_shows_one_skill(self):
        # Codex skips hidden folders when it scans a skills folder, so the entry file stays out of sight there.
        folders = CODEX_ENTRY.relative_to(ROOT).parts[:-1]
        self.assertTrue(any(folder.startswith(".") for folder in folders), folders)

    def test_codex_accepts_the_default_prompts(self):
        # Codex drops a prompt over 128 characters and any after the third.
        prompts = self.manifest["interface"]["defaultPrompt"]
        self.assertLessEqual(len(prompts), 3)
        for prompt in prompts:
            self.assertLessEqual(len(prompt), 128, prompt)

    def test_the_screenshots_exist(self):
        for path in self.manifest["interface"]["screenshots"]:
            self.assertTrue(path.startswith("./") and (ROOT / path).is_file(), path)


if __name__ == "__main__":
    unittest.main()
