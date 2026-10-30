"""Sales intelligence request and response schemas."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models import BriefStatus, EvaluationStatus, EvidenceSource, EvidenceStatus, FitLabel

Term = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Terms = Annotated[list[Term], Field(max_length=50)]


def _dedupe(values: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for v in values:
        seen.setdefault(v.lower(), v)
    return list(seen.values())


def _storable(v: str) -> str:
    """Postgres text cannot hold NUL, and lone surrogates cannot be encoded at all."""
    try:
        v.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Text contains invalid characters") from exc
    return v.replace("\x00", "")


class IcpCriteria(BaseModel):
    """Firmographic criteria and evidence keywords. Personal attributes have no place here."""

    model_config = ConfigDict(extra="forbid")

    industries: Terms = []
    excluded_industries: Terms = []
    countries: Terms = []
    min_employees: int | None = Field(default=None, ge=0, le=10_000_000)
    max_employees: int | None = Field(default=None, ge=0, le=10_000_000)
    target_titles: Terms = []
    need_keywords: Terms = []
    intent_keywords: Terms = []
    timing_keywords: Terms = []
    negative_keywords: Terms = []
    # Research older than this stops counting as a current signal.
    signal_ttl_days: int = Field(default=180, ge=1, le=3650)

    @field_validator(
        "industries",
        "excluded_industries",
        "countries",
        "target_titles",
        "need_keywords",
        "intent_keywords",
        "timing_keywords",
        "negative_keywords",
    )
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return _dedupe(v)

    @model_validator(mode="after")
    def _range(self) -> Self:
        low, high = self.min_employees, self.max_employees
        if low is not None and high is not None and low > high:
            raise ValueError("min_employees cannot exceed max_employees")
        return self


class ScoringWeights(BaseModel):
    """Relative weights for the positive components; `negative` is points taken off the score."""

    model_config = ConfigDict(extra="forbid")

    icp_fit: int = Field(default=35, ge=0, le=100)
    need: int = Field(default=20, ge=0, le=100)
    intent: int = Field(default=15, ge=0, le=100)
    timing: int = Field(default=10, ge=0, le=100)
    decision_maker: int = Field(default=10, ge=0, le=100)
    data_quality: int = Field(default=10, ge=0, le=100)
    negative: int = Field(default=25, ge=0, le=100)

    @model_validator(mode="after")
    def _some_positive(self) -> Self:
        if not (
            self.icp_fit
            + self.need
            + self.intent
            + self.timing
            + self.decision_maker
            + self.data_quality
        ):
            raise ValueError("At least one positive weight must be above zero")
        return self


class IcpCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: IcpCriteria
    weights: ScoringWeights = ScoringWeights()


class IcpOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    criteria: IcpCriteria
    weights: ScoringWeights
    created_by_user_id: uuid.UUID | None
    created_at: datetime


class EvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)
    title: str | None = Field(default=None, max_length=300)
    source_url: str | None = Field(default=None, max_length=2048)
    observed_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def _content(cls, v: str) -> str:
        v = _storable(v).strip()
        if not v:
            raise ValueError("Evidence cannot be blank")
        return v

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        return _storable(v).strip() or None if v else None

    @field_validator("source_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        # Rendered as a link, so only web URLs are accepted. It is never fetched from here.
        if v is None or not v.strip():
            return None
        parts = urlsplit(_storable(v).strip())
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("Source URL must start with http:// or https://")
        return v.strip()

    @field_validator("observed_at")
    @classmethod
    def _observed(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        if v > datetime.now(UTC):
            raise ValueError("observed_at cannot be in the future")
        if v.year < 2000:
            raise ValueError("observed_at is too far in the past")
        return v


class EvidenceFetch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)


class EvidenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[EvidenceStatus.accepted, EvidenceStatus.rejected]


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    source_type: EvidenceSource
    source_url: str | None
    title: str | None
    content: str
    status: EvidenceStatus
    screen_flags: list[str]
    observed_at: datetime
    created_by_user_id: uuid.UUID | None
    reviewed_by_user_id: uuid.UUID | None
    reviewed_at: datetime | None
    created_at: datetime


class ScoreComponent(BaseModel):
    name: str
    label: str
    weight: int
    # None means not configured, so the component took no part in the score.
    raw: float | None
    points: float | None


class CitedReason(BaseModel):
    text: str
    evidence_ids: list[uuid.UUID]


class Signal(BaseModel):
    type: str
    keyword: str
    evidence_id: uuid.UUID
    snippet: str
    observed_at: datetime
    expires_at: datetime
    source_type: EvidenceSource
    source_url: str | None


class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    icp_configuration_id: uuid.UUID
    score: int
    fit: FitLabel
    components: list[ScoreComponent]
    reasons: list[CitedReason]
    positive_signals: list[Signal]
    negative_signals: list[Signal]
    missing_information: list[str]
    evidence_ids: list[uuid.UUID]
    model_version: str
    evaluation_status: EvaluationStatus
    created_by_user_id: uuid.UUID | None
    reviewed_by_user_id: uuid.UUID | None
    reviewed_at: datetime | None
    created_at: datetime


class AssessmentDetail(AssessmentOut):
    """An assessment with the stored evidence behind it, as it is now."""

    evidence: list[EvidenceOut]


class AssessmentReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluation_status: Literal[EvaluationStatus.approved, EvaluationStatus.rejected]


class BriefClaim(BaseModel):
    text: str
    evidence_ids: list[uuid.UUID]


class RejectedClaim(BaseModel):
    # Removed by the checks and possibly hostile, so only reviewers receive the wording.
    text: str | None
    problems: list[str]


class BriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    status: BriefStatus
    model_key: str
    served_by: str | None
    prompt_version: str
    summary: str | None
    claims: list[BriefClaim]
    rejected_claims: list[RejectedClaim]
    missing_information: list[str]
    evidence_ids: list[uuid.UUID]
    failure_category: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime
    completed_at: datetime | None


def as_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
