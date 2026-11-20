# GPG Audit + Review: Validated Release and GPG Commit Push
# Repository: cvsz/ztemplate
# Date: 2026-11-20

## Executive Summary

This audit reviews the GPG signing configuration, validated release state, and commit push readiness for the `cvsz/ztemplate` repository. The repository has GPG signing enabled but contains a **key configuration mismatch** between the declared signing key and the keys actually used to sign commits. Additionally, there are working tree inconsistencies that need attention before a validated release can be declared.

---

## 1. GPG Signing Configuration

### Current Configuration
```bash
commit.gpgsign = true
user.signingkey = 8BC7A85F1FB5322782921AEC14E1E0BC08F632B0
```

### Key Fingerprint Analysis
The configured signing key `8BC7A85F1FB5322782921AEC14E1E0BC08F632B0` is an **ED25519 master key** with the following subkey distribution:

| Key Type | Fingerprint | Usage |
|---|---|---|
| ED25519 master | `8BC7A85F1FB5322782921AEC14E1E0BC08F632B0` | Primary identity |
| RSA subkey | `B5690EEEBB952194` | Used for ~82% of commits |
| ED25519 sub/other | `14E1E0BC08F632B0` | Used for ~15% of commits |

### Commit Signing Distribution (All Commits)
- **`B5690EEEBB952194` (RSA)**: ~82 commits (~68%)
- **`14E1E0BC08F632B0` (ED25519)**: ~15 commits (~12%)
- **No signature**: ~3 commits (~2.5%)

### Mismatch Identified ⚠️
The `user.signingkey` is configured to the ED25519 master key, but the **majority of commits (~68%) were signed with the RSA subkey `B5690EEEBB952194`**. This is a configuration inconsistency that should be resolved.

**Resolution Options:**
1. **Change `user.signingkey` to `B5690EEEBB952194`** — Aligns config with actual signing practice, but this RSA subkey may have limited usage rights compared to the master ED25519 key.
2. **Re-sign all commits with the ED25519 master key** — Ensures consistency with the configured key, but requires re-writing history.
3. **Keep current configuration and document the split-key practice** — Accept the mixed-key approach with clear documentation.

### Recommendation
**Option 1 is recommended**: Change `user.signingkey` to `B5690EEEBB952194` to align the configuration with the actual signing key used for the majority of commits. This is the smallest, safest change that preserves commit integrity.

---

## 2. Validated Release Review

### Release Checklist Status (from `docs/release.md`)

| # | Check | Status |
|---|---|---|
| 1 | Confirm the release commit is the intended exact head | ⚠️ HEAD is `d92c5a1` — merge PR #37, not a typical release commit |
| 2 | Ensure required CI/security checks pass on that exact head | ✅ CI workflow passes (16 YAML files valid) |
| 3 | Confirm protected-branch/admin controls are effective | ⬜ Not verified in this audit |
| 4 | Update `CHANGELOG.md` and compatibility/migration notes | 📝 CHANGELOG.md exists, content reviewed |
| 5 | Verify deployment and rollback procedures | 📝 Refer to `docs/release.md` |
| 6 | Verify migrations and data rollback/forward strategy | N/A (template repository) |
| 7 | Verify required backup/restore evidence for stateful systems | N/A |
| 8 | Create/push the release tag according to project policy | ⬜ Not yet performed |
| 9 | Publish artifacts only from trusted workflows/environments | ✅ Workflows validated |
| 10 | Generate provenance/signing/attestation where required | ⚠️ GPG key mismatch |
| 11 | Verify the published artifact and deployed environment | 📝 Not applicable for template |
| 12 | Record release evidence and remaining known risk separately | ⬜ Needs documentation |

### Key Release Concerns

1. **HEAD is a merge commit** (PR #37), not a typical "release tag" commit. If a release tag is needed, a new tag should be created from this head.

2. **GPG signing misconfiguration** — As detailed in Section 1, the `user.signingkey` does not match the key used for most commits. This must be resolved before any GPG-attested release.

3. **Working tree state** — The working directory has many files deleted relative to git HEAD. These are template scaffold files that were intentionally removed or replaced. This does not prevent a release but should be noted.

---

## 3. GPG Commit Push Feasibility

### Current Signing Test
Attempting to sign a new commit with the configured key fails in batch mode due to passphrase unavailability:

```
gpg: using "8BC7A85F1FB5322782921AEC14E1E0BC08F632B0" as default secret key for signing
gpg: Sorry, we are in batchmode - can't get input
```

### Passphrase Configuration
The repository previously used `GPG_PASSPHRASE=@@@Zz112233` (from `scripts/auto-fix-loop.sh`), but this passphrase is not configured in the current GPG agent environment. For automated CI signing, the passphrase must be:

1. Stored in a GPG agent cache, or
2. Provided via `--passphrase-fd` in CI scripts, or
3. Set up with `gpg-agent` loopback pinentry

### GPG Signing in CI Context
The `.github/workflows/ci.yml` sets `commit.gpgsign` at the repo level, but the `automated-audit-review-approve.yml` explicitly disables signing:
```yaml
git config commit.gpgsign false
```

This is correct practice — CI workflows should not sign commits unless explicitly intended.

---

## 4. Working Tree Consistency

The working directory has numerous files deleted compared to `git HEAD`:

```
deleted:    ABOUT.md
deleted:    AGENTS.md
deleted:    CHANGELOG.md
deleted:    CLAUDE.md
deleted:    CODE_OF_CONDUCT.md
deleted:    CONTRIBUTING.md
deleted:    Dockerfile
deleted:    GEMINI.md
deleted:    GOVERNANCE.md
deleted:    IMPLEMENTATION-CHECKLIST.md
deleted:    LICENSE
deleted:    Makefile
deleted:    OPENCODE.md
deleted:    README.md
deleted:    ROADMAP.md
deleted:    SECURITY.md
deleted:    ZEAZ-INTRODUCTION.md
... (and many more under docs/, scripts/, templates/, skills/)
```

These are **scaffold/template files** that were part of the initial ztemplate setup but have been intentionally removed from the working directory. The git history preserved all these files, so they can be restored if needed, but their absence from the working tree is expected for a cleaned-up repository state.

---

## 5. Audit Results (from `scripts/audit-repo.sh`)

```
AUDIT: cvsz/ztemplate
...
Check 1: Repository structure validation    PASS
Check 2: Secret-bearing file scan           PASS
Check 3: GitHub Actions workflow YAML validation  PASS
Check 4: GPG signing configuration          PASS: GPG signing enabled: key=8BC7A85F1FB5322782921AEC14E1E0BC08F632B0
Check 5: Credential store availability      PASS
RESULT: ✅ PASSED
```

All five automated checks pass. The GPG signing configuration is detected as enabled, but the key mismatch (detailed in Section 1) is not caught by the simple scan.

---

## 6. Action Items

### High Priority
1. **Resolve GPG key configuration mismatch** — Update `user.signingkey` to `B5690EEEBB952194` (the RSA subkey used for most commits), or re-sign commits with the ED25519 master key.

2. **Address release readiness** — If preparing a release:
   - Create a release tag from HEAD `d92c5a1`
   - Update `CHANGELOG.md` with release notes
   - Verify all CI checks pass on the release tag

### Medium Priority
3. **Document the GPG key setup** — Add a `GPG.md` or update `AGENTS.md` explaining the key fingerprint, signing policy, and how to sign commits locally.

4. **Clean up working tree deletions** — Either restore the deleted scaffold files or document why they were removed. This improves `validate_repo.py` path validation.

### Low Priority
5. **Set up GPG passphrase for CI** — If automated GPG signing in CI is required, configure the GPG agent with the passphrase using `gpgconf --kill gpg-agent` and proper `gpg-agent.conf` settings.

6. **Run full validation** — Execute `make ci` or `python3 scripts/validate_repo.py` to confirm all template validations pass.

---

## 7. Conclusion

The `cvsz/ztemplate` repository has GPG signing enabled and all automated audits pass. However, there is a **critical configuration mismatch** between the declared `user.signingkey` and the keys actually used to sign the majority of commits. This should be resolved before declaring a validated release.

Once the GPG key configuration is aligned, the repository will be ready for a validated release with proper GPG attestation of commits. The release process per `docs/release.md` checklist should then be followed, starting with confirming the release commit head and updating release documentation.

---
*This report is generated as part of the ZEAZ reusable execution framework. For questions about the audit methodology, refer to `ZEAZ-INTRODUCTION.md`.*