# skill-manifest

Offline generator for a **SEP-2640 `skills/list` manifest** plus a human-readable
compliance report for a directory of [Agent Skills](https://agentskills.io/specification).

Zero third-party dependencies. Python 3.8+. **Read only** — your skills are never modified.
No network calls, no API key, no account.

```bash
python skill_manifest.py ./my-skills --out skills.json --report REPORT.md --verify
python -m unittest discover -s tests -v
```

`--verify` recomputes every SHA-256 digest and byte size after generating, so a
broken manifest fails loudly instead of looking fine. `--strict` exits 1 when any
ERROR-level finding exists (handy in CI).

## What it does

1. Walks every subdirectory containing a `SKILL.md`.
2. Parses the YAML frontmatter (plain scalars, quoted scalars, `|`/`>` blocks,
   one-level nested maps) without pulling in PyYAML.
3. Emits `skills.json`: a `skills/list` result shaped for the **2026-07-28** MCP
   wire — `resultType: "complete"`, `ttlMs`, `cacheScope`, and one entry per skill
   with verbatim `frontmatter` and a **complete** `resources` array of
   `{uri, digest, size}` triples (including `SKILL.md` itself).
4. Emits `REPORT.md`: per-skill findings, totals, and the limits actually applied.

URIs follow `skill://<name>/<relative-path>` where `<name>` is the declared
frontmatter name, as required by
[SEP-2640 §Resource Mapping](https://modelcontextprotocol.io/seps/2640-skills-extension).
The report stores only a source label, never an absolute local path.

## Checks

| Check | Level | Source |
|---|---|---|
| `name` 1–64 chars, lowercase/digits/single hyphens, matches directory name | ERROR | [Agent Skills spec §Name field](https://agentskills.io/specification) |
| `description` 1–1024 chars, non-empty | ERROR | §Description field |
| `compatibility` ≤ 500 chars | ERROR | §Compatibility field |
| ≤ 512 files and ≤ 16 MiB per skill | ERROR | [SEP-2640 §Size limits](https://modelcontextprotocol.io/seps/2640-skills-extension) |
| `frontmatter` parses at all | ERROR | §Frontmatter |
| `SKILL.md` < 500 lines | WARN | §Progressive disclosure |
| `license` present | WARN | §License field |
| `allowed-tools` present | WARN | [SEP-2640 §Security Implications](https://modelcontextprotocol.io/seps/2640-skills-extension) |

## Why this is not an MCP server

The [official implementations list](https://github.com/modelcontextprotocol/ext-skills/blob/main/docs/implementations.md)
already tracks many conforming servers and official SDK work, and the
[extension support matrix](https://modelcontextprotocol.io/extensions/client-matrix)
shows that mainstream hosts (Claude Code, Cursor, VS Code Copilot) do not yet load
MCP-served skills. Writing another server would duplicate that work.

This tool solves the smaller, immediately useful half: **make a local skill
library verifiable and ready** before a host ever asks for it. The output can be
served later by any conforming server, statically hosted, or just used as an audit.

## Protocol notes

- MCP protocol revision **2026-07-28 removed the `initialize` handshake**. Servers
  implement `server/discover`, and every request carries its version and capabilities
  in `_meta`. The `2025-11-25` and earlier handshake-based revisions are *Legacy*.
  See [Versioning and Compatibility](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning).
- SEP-2640 is **Final** (merged 2026-09-13), but the extension is at the **Beta**
  stage of the extension lifecycle; the source of truth is
  `specification/beta/skills.mdx` in `modelcontextprotocol/ext-skills`. Fields may move.
- `skills/list` entries must be complete manifests — no follow-up call to fill in
  metadata. This tool emits complete entries.

## Security note

> **A digest match is not a trust boundary.** SEP-2640 digests are unsigned and
> supplied by the same server that supplies the content. A match proves that the
> listing and the bytes agree, not that the bytes are safe. A fully verified skill
> can still contain hostile instructions. Treat all skill content as untrusted
> input, ignore `allowed-tools` for MCP-origin skills, and require explicit
> per-skill approval before running anything.

## Layout

```
skill_manifest.py              CLI + library (all logic)
tests/test_skill_manifest.py   unit tests, incl. a tampered-file positive control
tests/fixtures/                three tiny fixture skills
examples/                      sample output generated from the fixtures
```

`python skill_manifest.py tests/fixtures --out examples/skills.example.json \
    --report examples/REPORT.example.md --label fixtures --verify`

## License

MIT. See [LICENSE](LICENSE).
