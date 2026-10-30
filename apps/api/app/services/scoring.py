"""Explainable 0-100 lead score. Pure, deterministic, and free of model output.

A model cannot move the score, so instructions planted in research text cannot either. The
score ranks leads against the organization's ICP. It is not a conversion probability.
Only firmographic facts and configured keywords are used, never personal attributes.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.models import EvaluationStatus, FitLabel

ENGINE_VERSION = "rules-v1"
HIGH_FIT = 70
MEDIUM_FIT = 40
_SNIPPET_RADIUS = 80
_KEYWORD_COMPONENTS = {
    "need": "need_keywords",
    "intent": "intent_keywords",
    "timing": "timing_keywords",
}
_LABELS = {
    "icp_fit": "ICP fit",
    "need": "Business need",
    "intent": "Buying intent",
    "timing": "Timing",
    "decision_maker": "Decision-maker relevance",
    "data_quality": "Data quality",
}


@dataclass(frozen=True)
class Fact:
    value: str | int
    evidence_id: str


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    text: str
    observed_at: datetime
    source_type: str
    source_url: str | None = None


@dataclass
class ScoreResult:
    score: int
    fit: FitLabel
    status: EvaluationStatus
    components: list[dict[str, Any]]
    reasons: list[dict[str, Any]]
    positive_signals: list[dict[str, Any]]
    negative_signals: list[dict[str, Any]]
    missing_information: list[str]
    evidence_ids: list[str]


def _reason(text: str, *evidence_ids: str) -> dict[str, Any]:
    return {"text": text, "evidence_ids": list(evidence_ids)}


def _in(value: str | int, options: list[str]) -> bool:
    return str(value).strip().lower() in {o.strip().lower() for o in options}


def _find(keyword: str, text: str) -> re.Match[str] | None:
    # Keywords are data: escaped, so a configured value can never act as a regex.
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text, re.IGNORECASE)


def _snippet(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - _SNIPPET_RADIUS)
    return " ".join(text[start : match.end() + _SNIPPET_RADIUS].split())


def _signals(
    kind: str, keywords: list[str], items: list[EvidenceItem], ttl: timedelta
) -> list[dict[str, Any]]:
    found = []
    for keyword in keywords:
        for item in items:
            if match := _find(keyword, item.text):
                found.append(
                    {
                        "type": kind,
                        "keyword": keyword,
                        "evidence_id": item.id,
                        "snippet": _snippet(item.text, match),
                        "observed_at": item.observed_at.isoformat(),
                        "expires_at": (item.observed_at + ttl).isoformat(),
                        "source_type": item.source_type,
                        "source_url": item.source_url,
                    }
                )
                break
    return found


def _icp_fit(
    facts: dict[str, Fact], c: dict[str, Any], missing: list[str]
) -> tuple[float | None, list[dict[str, Any]]]:
    """Share of configured firmographic criteria the lead's company is known to meet."""
    checks = 0
    met = 0
    reasons = []

    def check(field: str, label: str, passed: Any) -> None:
        nonlocal checks, met
        checks += 1
        fact = facts.get(field)
        if fact is None:
            missing.append(f"{label} is unknown")
        elif passed(fact.value):
            met += 1
            reasons.append(_reason(f"{label} {fact.value} matches the ICP", fact.evidence_id))
        else:
            reasons.append(_reason(f"{label} {fact.value} is outside the ICP", fact.evidence_id))

    if c.get("industries"):
        check("industry", "Industry", lambda v: _in(v, c["industries"]))
    if c.get("countries"):
        check("country", "Country", lambda v: _in(v, c["countries"]))
    low, high = c.get("min_employees"), c.get("max_employees")
    if low is not None or high is not None:
        check(
            "employee_count",
            "Company size",
            lambda v: (low is None or int(v) >= low) and (high is None or int(v) <= high),
        )
    return (met / checks if checks else None), reasons


def score_lead(
    facts: dict[str, Fact],
    evidence: list[EvidenceItem],
    criteria: dict[str, Any],
    weights: dict[str, int],
    *,
    now: datetime,
) -> ScoreResult:
    """`facts` and `evidence` must already exclude quarantined and rejected items."""
    missing: list[str] = []
    reasons: list[dict[str, Any]] = []
    ttl = timedelta(days=int(criteria.get("signal_ttl_days", 180)))
    research = [e for e in evidence if e.source_type != "crm_record"]
    fresh = [e for e in research if e.observed_at + ttl >= now]
    if len(fresh) < len(research):
        missing.append(
            f"{len(research) - len(fresh)} evidence item(s) older than {ttl.days} days were ignored"
        )

    raws: dict[str, float | None] = {}
    raws["icp_fit"], fit_reasons = _icp_fit(facts, criteria, missing)
    reasons += fit_reasons

    positive: list[dict[str, Any]] = []
    for name, key in _KEYWORD_COMPONENTS.items():
        keywords = criteria.get(key) or []
        hits = _signals(name, keywords, fresh, ttl)
        raws[name] = (1.0 if hits else 0.0) if keywords else None
        positive += hits
        if keywords and not hits:
            missing.append(f"No evidence of {_LABELS[name].lower()}")
        reasons += [
            _reason(f'{_LABELS[h["type"]]}: evidence mentions "{h["keyword"]}"', h["evidence_id"])
            for h in hits
        ]

    titles = criteria.get("target_titles") or []
    title = facts.get("title")
    if not titles:
        raws["decision_maker"] = None
    elif title is None:
        raws["decision_maker"] = 0.0
        missing.append("Job title is unknown")
    elif any(_find(t, str(title.value)) for t in titles):
        raws["decision_maker"] = 1.0
        reasons.append(_reason(f"Title {title.value} matches a target role", title.evidence_id))
    else:
        raws["decision_maker"] = 0.0
        reasons.append(_reason(f"Title {title.value} is not a target role", title.evidence_id))

    quality_fields = ("email", "title", "company", "industry", "employee_count", "country")
    known = [facts[f] for f in quality_fields if f in facts]
    raws["data_quality"] = len(known) / len(quality_fields)
    if known:
        reasons.append(
            _reason(
                f"{len(known)} of {len(quality_fields)} key CRM fields are filled in",
                *[f.evidence_id for f in known],
            )
        )

    negative = _signals("negative", criteria.get("negative_keywords") or [], fresh, ttl)
    reasons += [
        _reason(f'Negative signal: evidence mentions "{h["keyword"]}"', h["evidence_id"])
        for h in negative
    ]
    industry = facts.get("industry")
    excluded = bool(industry and _in(industry.value, criteria.get("excluded_industries") or []))
    if excluded and industry:
        reasons.append(
            _reason(f"Industry {industry.value} is excluded by the ICP", industry.evidence_id)
        )

    # Criteria nobody configured are left out, so an empty section cannot drag every lead down.
    active = {k: v for k, v in raws.items() if v is not None and weights.get(k, 0) > 0}
    total_weight = sum(weights[k] for k in active)
    earned = sum(weights[k] * v for k, v in active.items())
    base = 100 * earned / total_weight if total_weight else 0.0
    penalty = weights.get("negative", 0) if negative else 0
    score = max(0, min(100, int(base - penalty + 0.5)))

    components = [
        {
            "name": name,
            "label": label,
            "weight": weights.get(name, 0),
            "raw": raws[name],
            "points": round(100 * weights[name] * active[name] / total_weight, 1)
            if name in active
            else None,
        }
        for name, label in _LABELS.items()
    ]
    components.append(
        {
            "name": "negative",
            "label": "Negative signals",
            "weight": weights.get("negative", 0),
            "raw": 1.0 if negative else 0.0,
            "points": -penalty,
        }
    )

    if excluded or score < MEDIUM_FIT:
        fit = FitLabel.low
    elif score >= HIGH_FIT:
        fit = FitLabel.high
    else:
        fit = FitLabel.medium
    # CRM fields alone cannot show need or intent, so a person has to look before relying on this.
    status = EvaluationStatus.pending_review if fresh else EvaluationStatus.insufficient_evidence
    if not fresh:
        missing.append("No current research evidence; this rests on CRM fields only")

    used = dict.fromkeys(i for r in reasons for i in r["evidence_ids"])
    return ScoreResult(
        score=score,
        fit=fit,
        status=status,
        components=components,
        reasons=reasons,
        positive_signals=positive,
        negative_signals=negative,
        missing_information=missing,
        evidence_ids=list(used),
    )
