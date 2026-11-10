#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline Agent Skills -> MCP SEP-2640 manifest generator + compliance report.

Zero third-party dependencies. Python 3.8+.

    python skill_manifest.py <skills-dir> --out skills.json --report REPORT.md

The generated skills.json has the shape of a `skills/list` result on the
2026-07-28 MCP wire (resultType / ttlMs / cacheScope included). Every skill
entry carries verbatim frontmatter plus a complete per-file manifest of
{uri, digest, size}, as required by SEP-2640.

This tool is READ ONLY. It never modifies the skills directory.
A digest match proves byte consistency, NOT that the content is trustworthy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

# --- normative limits -----------------------------------------------------
# https://agentskills.io/specification
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESC = 1024
MAX_COMPAT = 500
RECOMMENDED_MAX_LINES = 500
# https://modelcontextprotocol.io/seps/2640-skills-extension
MAX_FILES = 512
MAX_BYTES = 16 * 1024 * 1024  # 16 MiB
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

SKILL_FILE = "SKILL.md"
ERROR = "ERROR"
WARN = "WARN"


@dataclass
class Issue:
    level: str
    code: str
    skill: str
    detail: str


def _scalar(value: str) -> str:
    """Unquote a simple YAML scalar. Nested / typed values stay strings."""
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    # A trailing unquoted comment. Inside quotes it is content, handled above.
    v = re.sub(r"\s+#.*$", "", v)
    return v.strip()


def parse_frontmatter(raw: bytes) -> Tuple[Dict[str, Any], str]:
    """Parse the top-level YAML frontmatter of a SKILL.md.

    Deliberately small: covers plain scalars, quoted scalars, `|`/`>` block
    scalars and one-level nested maps (e.g. `metadata:`). No PyYAML needed.
    Returns (frontmatter, error_code); error_code is "" on success.
    """
    lines = raw.decode("utf-8", "replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "NO_FRONTMATTER"
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, "UNTERMINATED_FRONTMATTER"

    body = lines[1:end]
    fm: Dict[str, Any] = {}
    i = 0
    while i < len(body):
        line = body[i]
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s+(.*))?$", line)
        if not m:
            i += 1
            continue
        key = m.group(1)
        val = (m.group(2) or "").strip()

        if val in ("|", ">", "|-", ">-"):
            j, buf = i + 1, []
            while j < len(body) and (body[j].startswith((" ", "\t")) or not body[j].strip()):
                buf.append(body[j].strip())
                j += 1
            fm[key] = "\n".join(buf).strip()
            i = j
            continue

        if val == "":
            j, sub, seq = i + 1, {}, []
            while j < len(body) and body[j].startswith((" ", "\t")):
                sm = re.match(r"^\s+([\w.-]+):\s*(.*)$", body[j])
                lm = re.match(r"^\s*-\s+(.*)$", body[j])
                if sm:
                    sub[sm.group(1)] = _scalar(sm.group(2))
                elif lm:
                    seq.append(_scalar(lm.group(1)))
                j += 1
            # YAML has two common shapes here: a nested map (metadata:) and a
            # block sequence (allowed-tools:\n  - Read). Missing the second one
            # silently under-reports the ALLOWED_TOOLS_RISK advisory.
            if sub:
                fm[key] = sub
            elif seq:
                fm[key] = seq
            else:
                fm[key] = ""
            i = j if (sub or seq) else i + 1
            continue

        fm[key] = _scalar(val)
        i += 1
    return fm, ""


def validate_frontmatter(fm: Dict[str, Any], dir_name: str,
                         line_count: int) -> List[Issue]:
    """Return spec violations (ERROR) and advisories (WARN)."""
    issues: List[Issue] = []
    name = fm.get("name")
    if not isinstance(name, str) or not name:
        issues.append(Issue(ERROR, "NAME_MISSING", dir_name, "frontmatter has no non-empty `name`"))
    else:
        if len(name) > MAX_NAME:
            issues.append(Issue(ERROR, "NAME_TOO_LONG", dir_name,
                                "name is %d chars, limit %d" % (len(name), MAX_NAME)))
        if not NAME_RE.match(name):
            issues.append(Issue(ERROR, "NAME_CHARS", dir_name,
                                "name must be lowercase alphanumeric + single hyphens, "
                                "no leading/trailing/doubled hyphens"))
        if name != dir_name:
            issues.append(Issue(ERROR, "NAME_MISMATCH", dir_name,
                                "name=%r does not match directory name" % name))

    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        issues.append(Issue(ERROR, "DESCRIPTION_MISSING", dir_name,
                            "frontmatter has no non-empty `description`"))
    elif len(desc) > MAX_DESC:
        issues.append(Issue(ERROR, "DESCRIPTION_TOO_LONG", dir_name,
                            "description is %d chars, limit %d" % (len(desc), MAX_DESC)))

    compat = fm.get("compatibility")
    if compat and len(str(compat)) > MAX_COMPAT:
        issues.append(Issue(ERROR, "COMPATIBILITY_TOO_LONG", dir_name,
                            "compatibility is %d chars, limit %d"
                            % (len(str(compat)), MAX_COMPAT)))

    if line_count > RECOMMENDED_MAX_LINES:
        issues.append(Issue(WARN, "BODY_TOO_LONG", dir_name,
                            "SKILL.md is %d lines, spec recommends < %d"
                            % (line_count, RECOMMENDED_MAX_LINES)))
    if not fm.get("license"):
        issues.append(Issue(WARN, "LICENSE_MISSING", dir_name,
                            "no `license` field; reuse terms are undefined"))
    if fm.get("allowed-tools"):
        issues.append(Issue(WARN, "ALLOWED_TOOLS_RISK", dir_name,
                            "`allowed-tools` is experimental and MUST be ignored "
                            "for MCP-origin skills (SEP-2640 Security Implications)"))
    return issues


def check_limits(n_files: int, total_bytes: int, dir_name: str) -> List[Issue]:
    issues: List[Issue] = []
    if n_files > MAX_FILES:
        issues.append(Issue(ERROR, "TOO_MANY_FILES", dir_name,
                            "%d files, limit %d" % (n_files, MAX_FILES)))
    if total_bytes > MAX_BYTES:
        issues.append(Issue(ERROR, "TOO_MANY_BYTES", dir_name,
                            "%d bytes, limit %d" % (total_bytes, MAX_BYTES)))
    return issues


def uri_prefix(fm: Dict[str, Any], dir_name: str) -> str:
    """URI segment: the declared name when valid, else the directory name."""
    name = fm.get("name")
    if (isinstance(name, str) and name and len(name) <= MAX_NAME
            and NAME_RE.match(name)):
        return name
    return dir_name


def build_resources(root: Path, prefix: str) -> List[Dict[str, Any]]:
    """Complete manifest: SKILL.md itself plus every supporting file."""
    out: List[Dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        data = path.read_bytes()
        out.append({
            "uri": "skill://%s/%s" % (prefix, rel),
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })
    return out


def verify_resources(root: Path, resources: List[Dict[str, Any]]) -> List[str]:
    """Recompute every digest/size. Returns human-readable mismatches."""
    bad: List[str] = []
    for item in resources:
        if not DIGEST_RE.match(item["digest"]):
            bad.append("bad digest format: " + item["uri"])
            continue
        rel = item["uri"].split("/", 3)[-1]
        path = root / rel
        if not path.is_file():
            bad.append("missing file: " + item["uri"])
            continue
        data = path.read_bytes()
        want = "sha256:" + hashlib.sha256(data).hexdigest()
        if want != item["digest"] or len(data) != item["size"]:
            bad.append("digest/size mismatch: " + item["uri"])
    return bad


def generate(skills_dir: Path) -> Tuple[Dict[str, Any], List[Issue], Dict[str, int]]:
    result: Dict[str, Any] = {
        "resultType": "complete",
        "skills": [],
        "ttlMs": 300000,
        "cacheScope": "public",
    }
    issues: List[Issue] = []
    stats = {"skills": 0, "files": 0, "bytes": 0,
             "max_files": 0, "max_bytes": 0,
             "errors": 0, "warnings": 0}

    dirs = sorted(p for p in skills_dir.iterdir()
                  if p.is_dir() and (p / SKILL_FILE).is_file())
    for d in dirs:
        raw = (d / SKILL_FILE).read_bytes()
        fm, err = parse_frontmatter(raw)
        if err:
            issues.append(Issue(ERROR, err, d.name,
                                "SKILL.md frontmatter could not be parsed"))
            fm = {}
        line_count = len(raw.decode("utf-8", "replace").splitlines())
        issues.extend(validate_frontmatter(fm, d.name, line_count))

        prefix = uri_prefix(fm, d.name)
        resources = build_resources(d, prefix)
        total = sum(r["size"] for r in resources)
        issues.extend(check_limits(len(resources), total, d.name))

        result["skills"].append({
            "uri": "skill://%s/%s" % (prefix, SKILL_FILE),
            "frontmatter": fm,
            "resources": resources,
        })
        stats["skills"] += 1
        stats["files"] += len(resources)
        stats["bytes"] += total
        stats["max_files"] = max(stats["max_files"], len(resources))
        stats["max_bytes"] = max(stats["max_bytes"], total)

    stats["errors"] = sum(1 for x in issues if x.level == ERROR)
    stats["warnings"] = sum(1 for x in issues if x.level == WARN)
    return result, issues, stats


def render_report(result: Dict[str, Any], issues: List[Issue],
                  stats: Dict[str, int], label: str) -> str:
    by_skill: Dict[str, List[Issue]] = {}
    for i in issues:
        by_skill.setdefault(i.skill, []).append(i)
    lines = [
        "# skill-manifest report",
        "",
        "- source: `%s` (label only; no absolute path is stored)" % label,
        "- skills: %d" % stats["skills"],
        "- files: %d" % stats["files"],
        "- total bytes: %d" % stats["bytes"],
        "- largest skill: %d files / %d bytes" % (stats["max_files"], stats["max_bytes"]),
        "- limits: %d files and %d bytes per skill" % (MAX_FILES, MAX_BYTES),
        "- errors: %d | warnings: %d" % (stats["errors"], stats["warnings"]),
        "",
        "> A digest match proves byte consistency, NOT that the content is",
        "> trustworthy. SEP-2640 digests are unsigned and supplied by the",
        "> same server that supplies the content.",
        "",
        "## Per-skill findings",
        "",
        "| skill | level | code | detail |",
        "|---|---|---|---|",
    ]
    if not issues:
        lines.append("| (all skills) | OK | - | no findings |")
    for skill in sorted(by_skill):
        for i in sorted(by_skill[skill], key=lambda x: (x.level, x.code)):
            detail = i.detail.replace("|", "\\|")
            lines.append("| `%s` | %s | `%s` | %s |" % (skill, i.level, i.code, detail))
    lines += ["", "## Clean skills", "",
              "`%d` of `%d` skills have no ERROR-level finding." % (
                  stats["skills"] - len({i.skill for i in issues if i.level == ERROR}),
                  stats["skills"]), ""]
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate a SEP-2640 skills/list manifest and a compliance report, offline.")
    ap.add_argument("skills_dir", help="directory containing skill subdirectories")
    ap.add_argument("--out", default="skills.json", help="output manifest path")
    ap.add_argument("--report", default="REPORT.md", help="output report path")
    ap.add_argument("--label", default="", help="source label written into the report")
    ap.add_argument("--verify", action="store_true",
                    help="recompute every digest/size as a self-check")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when any ERROR-level finding exists")
    a = ap.parse_args(argv)

    root = Path(a.skills_dir).resolve()
    if not root.is_dir():
        print("not a directory: %s" % root, file=sys.stderr)
        return 2

    label = a.label or root.name
    result, issues, stats = generate(root)

    if a.verify:
        mismatches: List[str] = []
        for entry in result["skills"]:
            prefix = entry["uri"].split("/")[2]
            d = root / prefix
            # prefix may be a declared name rather than a directory name
            if not d.is_dir():
                for cand in root.iterdir():
                    fm = cand / SKILL_FILE
                    if fm.is_file() and parse_frontmatter(fm.read_bytes())[0].get("name") == prefix:
                        d = cand
                        break
            mismatches.extend(verify_resources(d, entry["resources"]))
        if mismatches:
            for m in mismatches:
                print("VERIFY FAIL: " + m, file=sys.stderr)
            return 3
        print("verify  : %d resources recomputed, 0 mismatches" % stats["files"])

    Path(a.out).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(a.report).write_text(
        render_report(result, issues, stats, label), encoding="utf-8")

    print("skills  : %d" % stats["skills"])
    print("files   : %d" % stats["files"])
    print("bytes   : %d" % stats["bytes"])
    print("errors  : %d | warnings: %d" % (stats["errors"], stats["warnings"]))
    print("out     : %s" % a.out)
    print("report  : %s" % a.report)
    return 1 if (a.strict and stats["errors"]) else 0


if __name__ == "__main__":
    sys.exit(main())
