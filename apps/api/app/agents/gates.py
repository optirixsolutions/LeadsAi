"""Deterministic checks around models. Phase 4 measured models obeying planted instructions.

Input gate: evidence that reads like instructions is quarantined before scoring or any model
sees it. Output gate: model text survives only if it is supported by the evidence the model was
given and adds no numbers, links, or addresses of its own.

Patterns can be evaded by rewording, so this reduces risk and does not remove it. The second
line of defence is structural: model output never changes a score or triggers an action.
"""

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.agents.evaluation.metrics import lexical_support, unsupported_numbers
from app.agents.evaluation.tasks import SynthesisOut

# Every pattern here is bounded, and it runs over 20,000 characters of untrusted text.
_RULES: dict[str, re.Pattern[str]] = {
    "instruction_override": re.compile(
        r"\b(ignore|disregard|forget|override|bypass)\b[^.]{0,40}"
        r"\b(instructions?|rules?|prompts?|guidelines?|icp|criteria|above)\b",
        re.IGNORECASE,
    ),
    "addressed_to_ai": re.compile(
        r"\b(system (note|prompt|message)|for ai (readers|assistants|models|agents)"
        r"|ai (assistant|agent|model)s?,|you are now|act as an?|as an ai)\b|\bassistant\s{0,4}:",
        re.IGNORECASE,
    ),
    "score_manipulation": re.compile(
        r"\b(mark|label|classify|rate|score|treat)\b[^.]{0,30}\b(this|the)?\s{0,4}"
        r"(lead|company|prospect|account)?[^.]{0,20}\b(as )?(high|perfect|top|qualified)\b"
        r"(?=[^.]{0,20}\b(fit|score|priority|lead|customer)\b)|\bscore of 100\b"
        r"|\b(always|must) (answer|respond|say|reply)\b|\bperfect customer\b",
        re.IGNORECASE,
    ),
    "exfiltration": re.compile(
        r"\b(tell|ask|instruct)\b[^.]{0,30}\b(rep|user|sales|team)\b[^.]{0,30}"
        r"\b(email|send|forward|contact)\b"
        r"|\b(send|forward|email)\b[^.]{0,40}"
        r"\b(credentials?|passwords?|api keys?|customer list|contacts)\b",
        re.IGNORECASE,
    ),
}

_CONTACT = re.compile(
    r"[\w.+-]{1,64}@[\w.-]{1,253}|https?://\S{1,500}|www\.\S{1,500}"
    r"|\b[\w-]{1,63}\.(?:com|net|org|io|ai|co|app|dev|biz|info|example)\b",
    re.IGNORECASE,
)
_WORD = re.compile(r"[^\W\d_]{2,}")

MIN_LEXICAL_SUPPORT = 0.5
MAX_MISSING_ITEM_CHARS = 200


def _normalized(text: str) -> str:
    """What a reader sees: compatibility forms folded, invisible characters gone, spacing flat."""
    folded = unicodedata.normalize("NFKC", text)
    visible = "".join(c for c in folded if unicodedata.category(c) != "Cf")
    return " ".join(visible.split())


def _has_hidden_characters(text: str) -> bool:
    # Format characters (zero-width, bidi controls, Unicode tags) hide text from reviewers.
    return any(unicodedata.category(c) == "Cf" for c in text)


def _script(char: str) -> str | None:
    name = unicodedata.name(char, "")
    for script in ("LATIN", "CYRILLIC", "GREEK"):
        if name.startswith(script):
            return script
    return None


def _has_mixed_script_word(text: str) -> bool:
    """A word mixing Latin with lookalike letters, such as a Cyrillic letter inside "ignore"."""
    for word in _WORD.findall(text):
        if word.isascii():
            continue
        if len({_script(c) for c in word} - {None}) > 1:
            return True
    return False


def screen_evidence(text: str) -> list[str]:
    """Names of the rules this text matches. Any match sends it to quarantine."""
    normalized = _normalized(text)
    flags = [name for name, rule in _RULES.items() if rule.search(normalized)]
    if _has_hidden_characters(text):
        flags.append("hidden_characters")
    if _has_mixed_script_word(normalized):
        flags.append("mixed_script")
    return flags


def unsupported_contacts(text: str, sources: list[str]) -> list[str]:
    """Links, domains, and addresses in model text that appear in no source."""
    haystack = " ".join(sources).lower()
    return [m for m in _CONTACT.findall(text) if m.lower() not in haystack]


@dataclass
class GateResult:
    summary: str | None
    claims: list[dict[str, Any]] = field(default_factory=list)
    rejected_claims: list[dict[str, Any]] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)


def _claim_problems(text: str, ids: list[str], evidence: Mapping[str, str]) -> list[str]:
    problems = []
    cited = [evidence[i] for i in ids if i in evidence]
    if not ids:
        problems.append("no_citation")
    if any(i not in evidence for i in ids):
        problems.append("unknown_citation")
    if cited and lexical_support(text, cited) < MIN_LEXICAL_SUPPORT:
        problems.append("low_support")
    if cited and unsupported_numbers(text, cited):
        problems.append("unsupported_number")
    if cited and unsupported_contacts(text, cited):
        problems.append("unsupported_contact")
    if screen_evidence(text):
        problems.append("instruction_like")
    return problems


def _free_text_ok(text: str, sources: list[str]) -> bool:
    """Checks for model text that cites nothing, so it can only be held against everything."""
    return (
        not unsupported_numbers(text, sources)
        and not unsupported_contacts(text, sources)
        and not screen_evidence(text)
    )


def check_output(output: SynthesisOut, evidence: Mapping[str, str]) -> GateResult:
    """Keep only text that passes every check. `evidence` holds exactly what the model saw."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for claim in output.claims:
        problems = _claim_problems(claim.text, claim.evidence_ids, evidence)
        if problems:
            rejected.append({"text": claim.text, "problems": problems})
        else:
            # Duplicates add nothing, and a repeat citation is a sign of a looping model.
            kept.append(
                {"text": claim.text, "evidence_ids": list(dict.fromkeys(claim.evidence_ids))}
            )
    sources = list(evidence.values())
    summary_ok = (
        _free_text_ok(output.summary, sources)
        and lexical_support(output.summary, sources) >= MIN_LEXICAL_SUPPORT
    )
    # These name what is unknown, so they need not match the evidence, but they are still shown.
    missing = [
        m
        for m in output.missing_information
        if len(m) <= MAX_MISSING_ITEM_CHARS and _free_text_ok(m, sources)
    ]
    return GateResult(
        summary=output.summary if summary_ok else None,
        claims=kept,
        rejected_claims=rejected,
        missing_information=missing,
    )
