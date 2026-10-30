"""Deterministic baselines: what rules achieve with no model.

Any model has to beat these to justify its cost. Keyword lists were written from the TRAIN
split only. The classifier also knows the exact ICP point rule, an advantage a model does not get.
"""

import re
from typing import Any

from app.agents.evaluation.tasks import (
    Claim,
    ClassificationOut,
    ExtractionOut,
    OutreachOut,
    SynthesisOut,
)

NEED_PATTERNS = re.compile(
    r"evaluating|looking for|request for proposals|lead scoring|lead qualification|sales automation",
    re.IGNORECASE,
)
NEGATIVE_PATTERNS = re.compile(
    r"hiring freeze|contract with|being acquired|purchases are paused", re.IGNORECASE
)
INSTRUCTION_PATTERNS = re.compile(
    r"ignore (your|all)|disregard|override|system note|for ai readers|assistant:", re.IGNORECASE
)
_SIZE = re.compile(
    r"(?:employs about|headcount at [^.]*? is around|has a team of) ([\d,]+)", re.IGNORECASE
)
_CITY = re.compile(r"headquartered in ([A-Z][\w-]+), ([A-Z][\w ]+)\.")
_INDUSTRY = re.compile(r"operates in the (.+?) sector")
_FUNDING = re.compile(r"raised a (Seed|Series [A-Z]) round")


def classify(record: dict[str, Any], icp: dict[str, Any]) -> ClassificationOut:
    s, note = record["structured"], record["note"]
    size = s["employee_count"]
    if size is None and (m := _SIZE.search(note)):
        size = int(m.group(1).replace(",", ""))
    country = s["country"]
    if country is None and (m := _CITY.search(note)):
        country = m.group(2).strip()

    missing = [k for k, v in (("employee_count", size), ("country", country)) if v is None]
    if s["industry"] in icp["exclusions"]:
        return ClassificationOut(
            reasons=["Excluded industry"], missing_information=missing, fit="low"
        )

    low, high = icp["employee_range"]
    reasons, points = [], 0
    if s["industry"] in icp["target_industries"]:
        points += 2
        reasons.append("Target industry")
    if size is not None and low <= size <= high:
        points += 2
        reasons.append("Size in range")
    if country in icp["target_countries"]:
        points += 1
        reasons.append("Target geography")
    if s["contact_title"] in icp["decision_maker_titles"]:
        points += 1
        reasons.append("Decision maker")
    if NEED_PATTERNS.search(note):
        points += 2
        reasons.append("Need keyword found")
    if NEGATIVE_PATTERNS.search(note):
        points -= 3
        reasons.append("Blocker keyword found")
    fit = "high" if points >= 6 else "medium" if points >= 3 else "low"
    return ClassificationOut(reasons=reasons, missing_information=missing, fit=fit)  # type: ignore[arg-type]


def extract(record: dict[str, Any]) -> ExtractionOut:
    note = record["note"]
    size = _SIZE.search(note)
    city = _CITY.search(note)
    industry = _INDUSTRY.search(note)
    funding = _FUNDING.search(note)
    return ExtractionOut(
        company_name=record["structured"]["company"],
        employee_count=int(size.group(1).replace(",", "")) if size else None,
        hq_city=city.group(1) if city else None,
        industry=industry.group(1) if industry else None,
        funding_stage=funding.group(1) if funding else None,
    )


def _factual(item: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in item["evidence"] if not INSTRUCTION_PATTERNS.search(e["text"])]


def synthesize(item: dict[str, Any]) -> SynthesisOut:
    """Extractive brief: copies evidence verbatim, so it is grounded by construction."""
    facts = _factual(item)
    return SynthesisOut(
        summary=f"{item['company']}: {len(facts)} evidence items collected.",
        claims=[Claim(text=e["text"], evidence_ids=[e["id"]]) for e in facts],
        missing_information=["Budget", "Decision timeline"],
    )


def draft_outreach(item: dict[str, Any]) -> OutreachOut:
    """Fill-in template using the press item. Grounded, but generic by design."""
    press = next((e for e in _factual(item) if e["source"] == "press"), None)
    line = f'I read this about {item["company"]}: "{press["text"]}"' if press else ""
    return OutreachOut(
        subject=f"Sales prospecting at {item['company']}",
        body=f"Hi {item['contact_name'].split()[0]}, {line} Would a short call next week be useful?",
        evidence_ids=[press["id"]] if press else [],
    )


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def retrieve(query: str, evidence: list[dict[str, Any]]) -> list[str]:
    """Rank evidence by keyword overlap with the query."""
    q = _tokens(query)
    return [e["id"] for e in sorted(evidence, key=lambda e: -len(q & _tokens(e["text"])))]
