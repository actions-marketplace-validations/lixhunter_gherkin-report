# Releasing

## Versioning

Use semantic versioning:

- patch: bug fixes
- minor: backward-compatible features
- major: breaking changes

## Release checklist

- [ ] Repository setting `Immutable releases` is enabled (Settings -> Code security)
- [ ] Tag protection ruleset for `v*` is active (no updates, no deletions, no force pushes)
- [ ] Run tests and mypy
- [ ] Create an **annotated** tag on `main` HEAD (`vX.Y.Z`)
- [ ] Push tag
- [ ] Verify release notes include `What's Changed`, category sections, `Full Changelog`, and `Contributors`

## Commands

```bash
python3 -m unittest -v test_status_lookup.py
python3 smoke_test_report_generator.py
python3 -m mypy --config-file mypy.ini

git checkout main
git pull --ff-only
git tag -a v1.0.0 -m "v1.0.0"
git push origin v1.0.0
```

## Tag ruleset baseline

Protect tags matching `v*` with these policy goals:

- disallow tag updates
- disallow tag deletions
- disallow force pushes
- allow creations only for maintainers/release automation

This prevents moved/deleted release tags, which is the core attack pattern seen in the Trivy incident.

If repository rulesets are not available on your current GitHub plan for private repositories, keep the hardened release workflow checks enabled (annotated tags only, and tags must point to `main` HEAD) and rely on immutable releases until rulesets can be enabled.

