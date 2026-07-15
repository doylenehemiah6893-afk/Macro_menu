# Evidence Task 4 Implementation Report

## Outcome

Implemented structured package Reference contracts, bound them and the work
branch into immutable Kit identity, and added authenticated one-shot directory
and ZIP inspection. The intended commit subject is
`feat: bind reference contracts into kits`.

## RED evidence

The initial focused run, after adding the contract and integration tests but
before production code, exited 2 during collection with the expected:

```text
ModuleNotFoundError: No module named
'catvba_refactor.macro_build.reference_contract'
```

A later fail-closed path-policy test produced the expected single RED because a
definition root was not required to be present in the global allowed roots.
After the focused implementation was green, the first full run retained as
compatibility evidence reported `8 failed, 752 passed`; every failure used the
same legacy `test_audit.py` fixture package without `reference_contract`.
Updating that one shared fixture then exposed its legacy schema-v1 companion
reader, which rejected the new v2 shape as expected.

## GREEN evidence

Commands used the required offline interpreter environment:

```text
UV_NO_SYNC=1
UV_PYTHON=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3
UV_CACHE_DIR=/tmp/uv-cache
```

- Reference contracts: `21 passed in 0.06s`.
- Seven planned focused files: `350 passed, 19 warnings in 7.70s`.
- Audit compatibility: `61 passed, 19 warnings in 10.24s`.
- Full suite after the compatibility fix: `760 passed, 19 warnings in 18.82s`.
- `git diff --check`: clean.

Warnings are pre-existing oletools/pyparsing deprecations; no test warning came
from this implementation.

## Changed files

- Added `macro_build/reference_contract.py` and
  `tests/test_reference_contract.py`.
- Updated `config/packages.json`, `schemas/packages.schema.json`,
  `macro_build/manifests.py`, `macro_build/model.py`, and `macro_build/kit.py`.
- Updated the planned manifest/Kit/end-to-end/generator/policy/resolver fixtures.
- Minimally updated `macro_build/audit.py` and `tests/test_audit.py` after the
  full-suite RED showed the existing audit consumer still required a v1
  companion. This was explicitly authorized as compatibility work; consuming
  `BuildKitInspection.files` and structured returned-Reference comparison remain
  Task 7 responsibilities.

## Contract self-review

- The discovery form is the exact six-field package-specific contract for
  Core, Fleet-SPA, and Fleet-FTA. Approved contracts require definitions, all
  five ordered observation arrays, all four adjacent exact transitions, global
  and per-definition path policy, x64/B28 provenance, matching body digests,
  and complete observation approval provenance.
- Stable IDs are derived only from canonical uppercase-braced GUID and integer
  major/minor values. Definitions, point references, transition deltas,
  normalization-colliding aliases, unresolved identities, path roots,
  provenance, allowlists, and both approval digests fail closed.
- Body hashing names the four body fields explicitly and canonicalizes objects,
  so it does not depend on dictionary insertion order and excludes status,
  contract identity/version, approval metadata, and self digests.
- `reference_companion()` is the only companion producer. Creator and verifier
  both pass catalog packages through the same semantic boundary and both derive
  the exact v2 companion through that function.

## Inspection self-review

- `inspect_build_kit` captures directory or ZIP bytes exactly once, verifies
  that file map, and exposes identity only when the report is clean. Invalid
  snapshots retain captured bytes for diagnostics but all identity fields are
  `None`.
- Kit ID, both JSON hashes, manifest digest, Git OIDs/tree/branch, and canonical
  ZIP SHA-256 are derived solely from authenticated captured bytes.
- `verify_build_kit` delegates directly to `inspect_build_kit(...).report`.
- `work_branch` now changes catalog/Kit identity. Repository paths, repository
  labels, and non-work-branch ref labels remain excluded.

## Concerns and later-task boundary

No Task 4 implementation blocker remains. The existing audit reader still uses
its own authenticated directory reader and token-only allowlist comparison;
per the approved plan, Task 7 will switch evidence consumers to
`BuildKitInspection.files` and implement structured returned-Reference checks.
