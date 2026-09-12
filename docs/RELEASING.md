# Releasing

## Versioning

Releases are fully automated from merged pull requests on `main`.

Semantic versioning is derived from the PR release label:

- `fix` -> patch
- `feature` -> minor
- `breaking-change` -> major
- `ignore-release` -> no release for that merge

Exactly one of those labels is required on every pull request.

## One-time bootstrap

Create a baseline tag once so generated GitHub release notes have a complete comparison range:

```bash
git checkout main
git pull --ff-only
git tag -a v0.0.0 "$(git rev-list --max-parents=0 HEAD)" -m "v0.0.0"
git push origin v0.0.0
```

## Release checklist

- [ ] Repository setting `Immutable releases` is enabled (Settings -> Code security)
- [ ] Tag protection ruleset for `v*` is active (no updates, no deletions, no force pushes)
- [ ] CI is green on `main`
- [ ] PR labels follow the release label contract
- [ ] Verify generated release notes include `What's Changed`, category sections, `Full Changelog`, and `Contributors`

## How automatic release works

On every push to `main`, `.github/workflows/release.yml`:

1. Finds the latest `v*.*.*` tag
2. Scans merged PR references in the commit range
3. Resolves next SemVer from labels (`breaking-change` > `feature` > `fix`)
4. Skips release if all relevant PRs are labeled `ignore-release`
5. Creates an annotated tag and publishes a GitHub release with generated notes

If `HEAD` is already tagged, the workflow skips and does nothing.

## Manual fallback (emergency)

Use manual dispatch to rerun the same label-based computation for the current `main` history.
It does not use manual label input and does not force an explicit version.

## Commands

```bash
python3 -m unittest -v test_status_lookup.py
python3 smoke_test_report_generator.py
python3 -m mypy --config-file mypy.ini
```

## Tag ruleset baseline

Protect tags matching `v*` with these policy goals:

- disallow tag updates
- disallow tag deletions
- disallow force pushes
- allow creations only for maintainers/release automation

This prevents moved/deleted release tags, which is the core attack pattern seen in the Trivy incident.

If repository rulesets are not available on your current GitHub plan for private repositories, keep the hardened release workflow checks enabled (annotated tags only, and tags must point to `main` HEAD) and rely on immutable releases until rulesets can be enabled.
