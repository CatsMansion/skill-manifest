# skill-manifest report

- source: `fixtures` (label only; no absolute path is stored)
- skills: 3
- files: 4
- total bytes: 734
- largest skill: 2 files / 436 bytes
- limits: 512 files and 16777216 bytes per skill
- errors: 4 | warnings: 1

> A digest match proves byte consistency, NOT that the content is
> trustworthy. SEP-2640 digests are unsigned and supplied by the
> same server that supplies the content.

## Per-skill findings

| skill | level | code | detail |
|---|---|---|---|
| `bad-name-skill` | ERROR | `NAME_MISMATCH` | name='totally-different' does not match directory name |
| `no-frontmatter` | ERROR | `DESCRIPTION_MISSING` | frontmatter has no non-empty `description` |
| `no-frontmatter` | ERROR | `NAME_MISSING` | frontmatter has no non-empty `name` |
| `no-frontmatter` | ERROR | `NO_FRONTMATTER` | SKILL.md frontmatter could not be parsed |
| `no-frontmatter` | WARN | `LICENSE_MISSING` | no `license` field; reuse terms are undefined |

## Clean skills

`1` of `3` skills have no ERROR-level finding.
