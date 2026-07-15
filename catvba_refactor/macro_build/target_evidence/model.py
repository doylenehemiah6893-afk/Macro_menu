from dataclasses import dataclass
from enum import StrEnum

from ..model import Diagnostic


class EvidencePhase(StrEnum):
    CAPTURE = "capture"
    SEALED = "sealed"


class SessionMode(StrEnum):
    DISCOVERY = "discovery"
    G2 = "g2"
    G3_C = "g3-c"


class GateId(StrEnum):
    DISCOVERY = "DISCOVERY"
    G2 = "G2"
    G3_C = "G3-C"


class ComputedOutcome(StrEnum):
    ELIGIBLE = "eligible"
    FAIL = "fail"
    BLOCKED = "blocked"


@dataclass(frozen=True, order=True)
class PayloadMember:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class TargetEvidenceReport:
    phase: EvidencePhase
    session_id: str | None
    evidence_payload_digest: str | None
    payload_members: tuple[PayloadMember, ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return not self.diagnostics


@dataclass(frozen=True)
class TargetSessionReceipt:
    session_id: str
    session_dir: str
    mode: SessionMode
    kit_id: str
    evidence_payload_digest: str


@dataclass(frozen=True)
class GateEvaluation:
    gate_id: GateId
    computed_outcome: ComputedOutcome
    reason: str
    evidence_payload_digest: str
    receipt_path: str
    receipt_sha256: str
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class TargetEvidenceBundleReceipt:
    session_id: str
    bundle_dir: str
    zip_path: str
    zip_sha256: str
    evidence_payload_digest: str
    bundle_content_digest: str
