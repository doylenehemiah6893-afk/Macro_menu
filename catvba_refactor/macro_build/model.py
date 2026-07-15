import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


GIT_OBJECT_ID_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SHA256_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TOOL_VERSION_PATTERN = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


class SnapshotMode(StrEnum):
    CANDIDATE = "candidate"
    WORKTREE = "worktree"


class Origin(StrEnum):
    UPSTREAM = "upstream"
    NEW = "new"
    OVERRIDE = "override"
    SHARED = "shared"
    GENERATED = "generated"
    QUARANTINE = "quarantine"


@dataclass(frozen=True, order=True)
class Diagnostic:
    code: str
    path: str
    message: str
    details: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class ValidationReport:
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.diagnostics

    def sorted(self) -> "ValidationReport":
        return replace(self, diagnostics=tuple(sorted(self.diagnostics)))


@dataclass(frozen=True)
class InputSnapshot:
    mode: SnapshotMode
    upstream_repository: str
    upstream_ref: str
    upstream_commit: str
    fork_repository: str
    fork_dev_commit: str
    work_repository: str
    work_branch: str
    work_commit: str
    work_tree: str
    manifest_digest: str
    tool_version: str
    formal_eligible: bool


@dataclass(frozen=True)
class SourceMember:
    path: str
    blob_oid: str | None
    raw_sha256: str
    role: str
    data: bytes = field(repr=False, compare=False)


@dataclass(frozen=True)
class Component:
    source_id: str
    origin: Origin
    component_type: str
    vb_name: str
    members: tuple[SourceMember, ...]
    package_id: str | None
    disposition: str
    encoding_decision: str | None


@dataclass(frozen=True)
class Inventory:
    components: tuple[Component, ...]
    report: ValidationReport
    formal_eligible: bool


@dataclass(frozen=True)
class ResolvedSourceSet:
    components: tuple[Component, ...]
    quarantined: tuple[Component, ...]
    report: ValidationReport


@dataclass(frozen=True)
class GeneratedSourceSet:
    components: tuple[Component, ...]
    report: ValidationReport


@dataclass(frozen=True)
class GeneratedSourceDescriptor:
    source_id: str
    vb_name: str
    path: str


@dataclass(frozen=True)
class ResolvedCatalog:
    snapshot: InputSnapshot
    components: tuple[Component, ...]
    packages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...]
    report: ValidationReport


@dataclass(frozen=True)
class BuildKitReceipt:
    kit_id: str
    kit_dir: str
    zip_path: str
    zip_sha256: str
    manifest_sha256: str


@dataclass(frozen=True)
class VerificationReport:
    ok: bool
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class BuildKitInspection:
    files: tuple[tuple[str, bytes], ...]
    kit_id: str | None
    catalog_sha256: str | None
    manifest_sha256: str | None
    manifest_digest: str | None
    upstream_commit: str | None
    fork_dev_commit: str | None
    work_commit: str | None
    work_tree: str | None
    work_branch: str | None
    canonical_zip_sha256: str | None
    report: VerificationReport
