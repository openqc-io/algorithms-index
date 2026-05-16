#!/usr/bin/env python3
"""Build INDEX.json + seed.json by scanning openqc-io/algo-* repos + community submissions.

Runs as a GitHub Action (every 6h, on SUBMISSIONS.json push, on manual dispatch).
Uses the GitHub API to discover repos, fetch and validate each algorithm.json
against schema.json + TAXONOMY.json, pin the current commit_sha, and emit
INDEX.json + seed.json.

INDEX.json is the source of truth for the catalog. vortex-platform syncs
from it every 6h. seed.json is a slim copy bundled into the vortex-platform
image for cold-start ergonomics (air-gapped install, first run before sync
completes) — data only, never code.

Usage:
  GITHUB_TOKEN=ghp_xxx python scripts/build_index.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import urllib.error
import urllib.request

import jsonschema

GITHUB_API = "https://api.github.com"
ORG = os.environ.get("OPENQC_GITHUB_ORG", "openqc-io")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

REPO_ROOT = Path(__file__).parent.parent
INDEX_FILE = REPO_ROOT / "INDEX.json"
SEED_FILE = REPO_ROOT / "seed.json"
SUBMISSIONS_FILE = REPO_ROOT / "SUBMISSIONS.json"
SCHEMA_FILE = REPO_ROOT / "schema.json"
TAXONOMY_FILE = REPO_ROOT / "TAXONOMY.json"

SKIP_REPOS = {"algorithms-index", "algo-template"}

# Fields excluded from seed.json (frequently-changing metadata not needed
# at cold start; first authoritative sync overwrites them anyway).
SEED_EXCLUDE_FIELDS = {"stars", "last_updated", "default_branch"}


def github_get(url: str) -> dict | list | None:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Error: {e}: {url}", file=sys.stderr)
        return None


def fetch_algorithm_json(repo: str, sha: str) -> dict | None:
    """Fetch algorithm.json pinned at a specific commit sha."""
    url = f"{GITHUB_API}/repos/{repo}/contents/algorithm.json?ref={sha}"
    data = github_get(url)
    if data and "content" in data:
        try:
            return json.loads(base64.b64decode(data["content"]).decode("utf-8"))
        except Exception:
            return None
    return None


def latest_commit_sha(repo: str, branch: str) -> str | None:
    """Return the head commit sha of the given branch — what we pin to."""
    url = f"{GITHUB_API}/repos/{repo}/branches/{branch}"
    data = github_get(url)
    if data and "commit" in data:
        return data["commit"].get("sha")
    return None


def repo_meta(repo: str) -> dict | None:
    return github_get(f"{GITHUB_API}/repos/{repo}")


def discover_org_repos() -> list[dict]:
    """Find non-archived repos under ORG that look like algorithm repos."""
    repos = []
    page = 1
    while True:
        url = f"{GITHUB_API}/orgs/{ORG}/repos?per_page=100&page={page}&type=public&sort=updated"
        # Fall back to /users/ when /orgs/ 404s (personal account during migration).
        data = github_get(url)
        if data is None:
            data = github_get(
                f"{GITHUB_API}/users/{ORG}/repos?per_page=100&page={page}&sort=updated"
            ) or []
        if not data:
            break
        for r in data:
            if r.get("archived"):
                continue
            if r["name"] in SKIP_REPOS:
                continue
            # algo-* by convention, but accept anything with algorithm.json
            repos.append(r)
        if len(data) < 100:
            break
        page += 1
    return repos


def load_community_submissions() -> list[dict]:
    if not SUBMISSIONS_FILE.exists():
        return []
    with open(SUBMISSIONS_FILE) as f:
        data = json.load(f)
    return data.get("community_repos", [])


def resolve_owner(repo_full_name: str, declared: str | None) -> str:
    """Resolve the canonical ``owner`` axis for an entry.

    Repo location sets the *upper bound* on what an algorithm can claim:
    outside the openqc-io org, the owner is always ``community`` (a
    contributor can't unilaterally publish under ``owner=openqc``).

    Within openqc-io we honor the algorithm.json ``owner`` field, so a
    community-authored algorithm can be hosted in openqc-io for
    operational convenience (shared SSH key, centralized CI) while still
    being correctly tagged ``owner=community``. Authorship, not hosting,
    determines the axis.
    """
    in_org = repo_full_name.startswith(f"{ORG}/")
    if not in_org:
        return "community"
    if declared == "community":
        return "community"
    return "openqc"


def build_entry(
    repo_full_name: str,
    branch: str,
    algo: dict,
    sha: str,
    info: dict,
    schema: dict,
    taxonomy: dict,
) -> dict | None:
    """Validate + compose a single INDEX.json entry. Returns None on failure."""
    try:
        jsonschema.validate(algo, schema)
    except jsonschema.ValidationError as e:
        print(f"::warning::Schema fail {repo_full_name}@{sha[:7]}: {e.message}", file=sys.stderr)
        return None

    valid_industries = set(taxonomy["industries"].keys())
    valid_techniques = set(taxonomy["techniques"].keys())
    valid_computation = set(taxonomy["computation_models"].keys())

    bad = [i for i in algo["industries"] if i not in valid_industries]
    if bad:
        print(f"::warning::Invalid industries {bad} in {repo_full_name}", file=sys.stderr)
        return None
    bad = [t for t in algo["techniques"] if t not in valid_techniques]
    if bad:
        print(f"::warning::Invalid techniques {bad} in {repo_full_name}", file=sys.stderr)
        return None
    if algo["computation_model"] not in valid_computation:
        print(
            f"::warning::Invalid computation_model {algo['computation_model']} in {repo_full_name}",
            file=sys.stderr,
        )
        return None

    # Owner resolution honors algorithm.json's ``owner`` field when the
    # algorithm declares ``community``, even if hosted inside the
    # openqc-io org. Repo location only sets the upper bound.
    declared = algo.get("owner")
    owner = resolve_owner(repo_full_name, declared)
    if declared == "openqc" and owner == "community":
        print(
            f"::warning::owner downgrade in {repo_full_name}: algorithm.json claims "
            f"'openqc' but repo is outside openqc-io; resolved to 'community'.",
            file=sys.stderr,
        )

    entry = {
        "slug": algo["slug"],
        "name": algo["name"],
        "description": algo.get("description", ""),
        "repo": repo_full_name,
        "commit_sha": sha,
        "default_branch": branch,
        "version": algo.get("version", "1.0.0"),
        "author": algo.get("author", repo_full_name.split("/")[0]),
        "license": algo.get("license", "Apache-2.0"),

        # Four-axis model
        "owner": owner,
        "scope": "catalog",
        "access": algo["access"],
        "implementation_mode": algo["implementation_mode"],

        # Classification
        "industries": algo["industries"],
        "techniques": algo["techniques"],
        "difficulty": algo["difficulty"],
        "computation_model": algo["computation_model"],
        "algorithm_type": algo.get("algorithm_type", "circuit"),
        "qubit_count": algo["qubit_count"],
        "tags": algo.get("tags", []),

        # Discovery metadata (changes frequently — excluded from seed.json)
        "stars": info.get("stargazers_count", 0),
        "last_updated": info.get("pushed_at", ""),

        "status": algo.get("status", "available"),
    }

    # Optional fields surfaced only when set
    for k in ("min_qubits", "recommended_backends", "access_reason", "provider_url",
              "pricing", "input_schema", "output_schema", "blockers", "metadata",
              "circuit_qasm_path", "template_path"):
        if k in algo and algo[k] is not None:
            entry[k] = algo[k]

    return entry


def build():
    schema = json.loads(SCHEMA_FILE.read_text())
    taxonomy = json.loads(TAXONOMY_FILE.read_text())
    print(f"Loaded schema (required fields: {len(schema['required'])}) + "
          f"TAXONOMY v{taxonomy['version']}")

    org_repos = discover_org_repos()
    community = load_community_submissions()
    print(f"Discovered {len(org_repos)} org repos + {len(community)} community submissions")

    all_targets: list[tuple[str, str]] = []
    seen: set[str] = set()

    for r in org_repos:
        full = r["full_name"]
        if full in seen:
            continue
        seen.add(full)
        all_targets.append((full, r.get("default_branch", "main")))

    for c in community:
        full = c.get("repo", "")
        if not full or full in seen:
            continue
        seen.add(full)
        info = repo_meta(full) or {}
        all_targets.append((full, info.get("default_branch", "main")))

    print(f"Total candidate repos: {len(all_targets)}")

    entries: list[dict] = []
    skipped: list[str] = []

    for repo_full, branch in sorted(all_targets):
        print(f"  Scanning {repo_full}...")
        sha = latest_commit_sha(repo_full, branch)
        if not sha:
            print(f"    no commit_sha — skipping")
            skipped.append(f"{repo_full}: no commit_sha")
            continue
        algo = fetch_algorithm_json(repo_full, sha)
        if not algo:
            print(f"    no algorithm.json at {sha[:7]} — skipping")
            skipped.append(f"{repo_full}@{sha[:7]}: no algorithm.json")
            continue
        info = repo_meta(repo_full) or {}
        entry = build_entry(repo_full, branch, algo, sha, info, schema, taxonomy)
        if entry is None:
            skipped.append(f"{repo_full}@{sha[:7]}: validation failed")
            continue
        entries.append(entry)
        print(f"    + {entry['slug']} ({entry['owner']}/{entry['access']}, {sha[:7]})")

    # Stable ordering: openqc first, then community, then by slug.
    entries.sort(key=lambda e: (0 if e["owner"] == "openqc" else 1, e["slug"]))

    now = datetime.now(timezone.utc).isoformat()
    index = {
        "generated_at": now,
        "schema_version": schema.get("$id", "schema.json"),
        "taxonomy_version": taxonomy["version"],
        "total": len(entries),
        "skipped_count": len(skipped),
        "skipped": skipped,
        "algorithms": entries,
    }
    INDEX_FILE.write_text(json.dumps(index, indent=2) + "\n")
    print(f"\nINDEX.json written: {len(entries)} algorithms, {len(skipped)} skipped")

    # seed.json = slim metadata copy for cold-start hydration. Same shape,
    # frequently-changing fields stripped to keep the bundled artifact small.
    seed_entries = [
        {k: v for k, v in e.items() if k not in SEED_EXCLUDE_FIELDS}
        for e in entries
    ]
    seed = {
        "generated_at": now,
        "schema_version": index["schema_version"],
        "taxonomy_version": taxonomy["version"],
        "total": len(seed_entries),
        "algorithms": seed_entries,
    }
    SEED_FILE.write_text(json.dumps(seed, indent=2) + "\n")
    print(f"seed.json written: {len(seed_entries)} entries (stripped {sorted(SEED_EXCLUDE_FIELDS)})")


if __name__ == "__main__":
    build()
