# Installation and permissions

[Back to the README](../README.md)


Clone the repository into your agent's skill folder. Keep the folder name `deutsch-loop`: it must match the skill's name.

Claude Code, for all your projects:

```bash
git clone https://github.com/ahmtsahin/deutsch-loop.git "$HOME/.claude/skills/deutsch-loop"
```

Codex, for all your projects:

```bash
git clone https://github.com/ahmtsahin/deutsch-loop.git "$HOME/.agents/skills/deutsch-loop"
```

The commands work in macOS and Linux terminals and in PowerShell. For a single project, clone into `.claude/skills/deutsch-loop` (Claude Code) or `.agents/skills/deutsch-loop` (Codex) inside that project instead. To update later, run `git pull` in the skill folder.

See the official [Claude Code skill guide](https://code.claude.com/docs/en/skills) and [Codex skill guide](https://developers.openai.com/codex/skills/) for discovery rules. Python 3.10+ is required; no Python packages are needed for the runtime. On Windows, the `py -3` launcher works where `python` only opens the Microsoft Store.

### As a Claude Code plugin

The repository is also a plugin with its own marketplace entry. In a terminal:

```bash
claude plugin marketplace add ahmtsahin/deutsch-loop
```

```bash
claude plugin install deutsch-loop@deutsch-loop
```

Start a chat with `/deutsch-loop:deutsch-loop`; a plugin's skills carry its name as a prefix. To update later, run `claude plugin update deutsch-loop@deutsch-loop`. Use either the plugin or the cloned skill folder, so that the skill appears once.

### As a Codex plugin

Codex reads the same marketplace entry. In a terminal:

```bash
codex plugin marketplace add ahmtsahin/deutsch-loop
```

```bash
codex plugin add deutsch-loop@deutsch-loop
```

Start a new chat with `$deutsch-loop:deutsch-loop`. To update later, run `codex plugin marketplace upgrade deutsch-loop`. Use either the plugin or the cloned skill folder here too.

Codex shows the cloned skill under the same name, `deutsch-loop:deutsch-loop`, because the folder contains the plugin manifest. `$deutsch-loop` still starts it.

Codex also lists `nochmal@deutsch-loop`; that is the Claude Code companion below, and Codex has nothing to run it with.

### The Claude Code companion

The marketplace's second plugin adds the status line, the cards while Claude works, and the FehlerDNA and scene panes. It works beside either installation above:

```bash
claude plugin install nochmal@deutsch-loop
```

From a cloned folder, load it for one session with `claude --plugin-dir mods/nochmal`. It needs a Claude Code release with mods (plugin function hooks) and stays silent until you have practised with the tutor once. [Companion guide](companion.md).

### Let it save without asking

The skill keeps your progress in `~/.deutschloop` through a small Python helper. Depending on your host permissions, helper calls may ask for approval or the sandbox may block the state folder. One optional setting removes those interruptions.

**Claude Code** asks before helper calls, and “don't ask again” applies only to the current project. To stop the questions everywhere, add these rules to `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(python *deutsch_loop.py*)",
      "PowerShell(python *deutsch_loop.py*)",
      "Read(~/.claude/skills/deutsch-loop/**)"
    ]
  }
}
```

Use `python3` or `py` instead of `python` if that is how your system runs Python. These rules allow Python commands that mention the helper, so keep them only if you trust the skill folder.

**Codex** runs commands in a sandbox that may write only to your project. Create the state directory in a normal terminal: run `python scripts/deutsch_loop.py recap` from the cloned skill folder or, with the plugin, create the folder `~/.deutschloop` yourself. Then list it as a writable root in `~/.codex/config.toml`:

```toml
[sandbox_workspace_write]
writable_roots = ["/Users/you/.deutschloop"]   # Windows: ['C:\Users\you\.deutschloop']
```

The folder must exist first; a writable root that does not exist yet cannot be created from inside the sandbox. Without this setting, Codex needs your approval to run the helper outside the sandbox.

## Installed under the old name, DeutschDNA?

Your progress carries over without moving anything. While no `~/.deutschloop` folder exists, the helper keeps using `~/.deutschdna`, and it still reads `DEUTSCHDNA_HOME` and `DEUTSCHDNA_UTC_OFFSET`.

The skill is now called `deutsch-loop`. Remove the old `deutsch-dna` skill folder or plugin, then install again as in the quick start, so that the skill appears once. If you added the permission rules above, replace `deutsch_dna.py` with `deutsch_loop.py` and `skills/deutsch-dna` with `skills/deutsch-loop`. A Codex writable root for `~/.deutschdna` stays valid.

## Already installed in an older Codex location?

Some Codex installations also load `~/.codex/skills`. The quick start uses the current documented `~/.agents/skills` location. Keep one copy of the skill to avoid duplicate entries. If the skill does not appear after installation, restart Codex.

## Run the examples from the skill folder

After cloning, change into the location you used before running any `python scripts/...` example:

```bash
# Codex
cd "$HOME/.agents/skills/deutsch-loop"

# Claude Code
cd "$HOME/.claude/skills/deutsch-loop"
```

State is stored in `~/.deutschloop`. To use a different location, set `DEUTSCHLOOP_HOME` or place `--home PATH` before the command.
