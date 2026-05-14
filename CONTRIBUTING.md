# Contributing Algorithms to OpenQC

Thank you for contributing. Every algorithm makes quantum computing more accessible.

## How the Catalog Works

OpenQC's algorithm system models every algorithm with four orthogonal axes (full spec in [PRPs/community-algorithms/taxonomy.md](../PRPs/community-algorithms/taxonomy.md)):

- `owner` — `openqc` (maintained by the team) or `community` (everyone else)
- `scope` — `catalog` (this repo + the index) or `workspace` (your private workspace, never published)
- `access` — `open` / `gated` / `paid` / `private` — distribution policy
- `implementation_mode` — `catalog_synced` (code in your repo at a pinned SHA) or `hosted_api` (executable lives on your provider URL)

You'll set `owner`, `access`, and `implementation_mode` in your `algorithm.json`. `scope=catalog` is implicit — every published algorithm is in the catalog namespace.

## Quick Path: Use Our Template

1. Go to [openqc-io/algo-template](https://github.com/openqc-io/algo-template).
2. Click **Use this template** → creates a new repo in your account or org.
3. Rename it `algo-{your-slug}` (recommended convention; not required).
4. Fill in:
   - **`algorithm.json`** — metadata + the four axes. Validates against [schema.json](https://github.com/openqc-io/algorithms-index/blob/main/schema.json) + [TAXONOMY.json](https://github.com/openqc-io/algorithms-index/blob/main/TAXONOMY.json).
   - **`circuit.qasm`** — OpenQASM 2.0 circuit (omit if `implementation_mode=hosted_api`).
   - **`template.py`** — `build()` + `interpret()` (omit if `hosted_api`).
   - **`README.md`** — explanation, math, diagrams.
5. Push. CI runs `validate.yml` against schema + TAXONOMY automatically.
6. Submit a PR to [openqc-io/algorithms-index](https://github.com/openqc-io/algorithms-index) adding your repo to `SUBMISSIONS.json`:
   ```json
   {
     "community_repos": [
       {"repo": "your-username/algo-your-slug", "submitted_by": "your-username", "submitted_at": "YYYY-MM-DD"}
     ]
   }
   ```
7. Maintainers review → merge → the next index build (6h cron, or instant via webhook) picks it up. Your algorithm appears on the platform.

## Alternate Path: Use Your Existing Repo

Already have a quantum-algorithm repo? Just add `algorithm.json` at the root, push, then PR to `algorithms-index`. Same review flow.

## Persona Recipes

### Open community algorithm

```json
{
  "slug": "my-grover-variant",
  "owner": "community",
  "scope": "catalog",
  "access": "open",
  "implementation_mode": "catalog_synced",
  "industries": ["foundational"],
  "techniques": ["gate"],
  "difficulty": "intermediate",
  "computation_model": "gate",
  "qubit_count": 4
}
```

### Gated (citation required)

```json
{
  "access": "gated",
  "access_reason": "Cite our 2026 paper to unlock execution.",
  "implementation_mode": "catalog_synced"
}
```

Code stays visible in the public repo; the platform enforces the access check at run time.

### Paid

```json
{
  "access": "paid",
  "implementation_mode": "hosted_api",
  "provider_url": "https://your-provider.example.com/run",
  "pricing": { "model": "per_run", "price_usd": 0.50 }
}
```

Code stays on your infrastructure. Platform charges via Stripe Connect (70% you / 30% platform).

### Private (invite-only)

```json
{
  "access": "private",
  "implementation_mode": "hosted_api",
  "provider_url": "https://your-provider.example.com/run"
}
```

Metadata visible only to invited users; execution restricted by entitlement.

## Validation Rules (enforced in CI)

- `industries` and `techniques` must validate against `TAXONOMY.json`. Notable absences vs older docs:
  - `optimization` is **not** an industry. Tag with the applied domain (`logistics`, `finance`, etc.) and the technique facet (`qaoa`, `annealing`).
  - `education` is **not** an industry. Use `industries=["foundational"]` for quantum primitives; `difficulty=beginner` is the audience signal.
  - `vqa` is **not** a technique. Use the specific family (`vqe` or `qaoa`).
- `access=paid` requires a `pricing` object; other access tiers must not include `pricing`.
- `implementation_mode=hosted_api` requires `provider_url`.
- `slug` must match `^[a-z0-9][a-z0-9-]*[a-z0-9]$`.
- `owner` declared in `algorithm.json` must match the repo location — only repos under `openqc-io/` can publish with `owner=openqc`.

## What Happens After Merge

1. `build-index.yml` runs on the next 6h cron (or instantly via webhook).
2. Your repo's current commit SHA is pinned in `INDEX.json` — future updates require a new PR with a new SHA. This prevents silent breaking changes and malicious force-pushes.
3. `vortex-platform` syncs `INDEX.json` to its `algorithm_templates` collection (within ~6h, faster via webhook).
4. Your algorithm shows up on `openqc.io/algorithms` with `owner` and `access` badges.

## Quality Guidelines

- **README.md** — Explain the algorithm clearly enough for a university student.
- **circuit.qasm** — Must be valid OpenQASM 2.0.
- **template.py** — Must define `build()` and `interpret()`. Runs in a sandbox (no imports beyond math; no file/network access).
- **benchmarks/** — Include expected results for at least one backend, where applicable.
- **tags** — Use existing tags from `TAXONOMY.json` when possible; free-form `tags` array is fine for additional discovery.

## Review Process

1. Submit PR to `algorithms-index`.
2. CI checks: schema valid? TAXONOMY values valid? QASM parses? No duplicate slug?
3. Maintainer reviews: quality, accuracy, no malicious code.
4. Merge → indexed within 6 hours (or seconds via webhook) → live on platform.

## Questions

- Schema or taxonomy questions → file an issue on [algorithms-index](https://github.com/openqc-io/algorithms-index/issues).
- Run-time / sandbox questions → file an issue on the main `openqc` repo.
- Pricing / payments → see [monetization.md](../PRPs/community-algorithms/monetization.md).

## License

By contributing, you agree your contribution will be licensed under the Apache License 2.0 (see `LICENSE`).
