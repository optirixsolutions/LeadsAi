"""CSV import: preview, mapping, dedupe policies, idempotency, error reporting."""

from typing import Any

import pytest

CSV = """Name,Email,Company,Website,Title,Notes
Ada Lovelace,ada@engines.com,Analytical Engines,https://www.engines.com,CTO,met at expo
Grace Hopper,grace@navy.mil,Navy,,Admiral,
Dup Inside,ADA@engines.com,Analytical Engines,,,
Bad Email,not-an-email,,,,
  ,,Lonely Co,,Buyer,
Gmail User,someone@gmail.com,,,,
"""

MAPPING = {
    "Name": "full_name",
    "Email": "email",
    "Company": "company_name",
    "Website": "website",
    "Title": "title",
}


@pytest.fixture
def org(make_org: Any) -> tuple[Any, str]:
    return make_org("Import Co")


def _run(api: Any, oid: str, content: str = CSV, **extra: Any) -> Any:
    body = {"filename": "leads.csv", "content": content, "mapping": MAPPING, **extra}
    return api.post(f"/organizations/{oid}/lead-imports", body)


def test_preview_suggests_mapping(org: tuple[Any, str]) -> None:
    owner, oid = org
    r = owner.api.post(
        f"/organizations/{oid}/lead-imports/preview", {"filename": "leads.csv", "content": CSV}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["headers"][:3] == ["Name", "Email", "Company"]
    assert body["total_rows"] == 6
    assert len(body["sample_rows"]) == 5
    assert body["suggested_mapping"] == {**MAPPING, "Notes": None}


def test_import_counts_dedupes_and_reports_errors(org: tuple[Any, str]) -> None:
    owner, oid = org
    r = _run(owner.api, oid)
    assert r.status_code == 201, r.text
    result = r.json()
    assert result["total_rows"] == 6
    assert result["created_count"] == 3  # Ada, Grace, Gmail user
    assert result["skipped_count"] == 1  # duplicate email inside the file
    assert result["error_count"] == 2
    assert {e["row"] for e in result["errors"]} == {5, 6}
    assert any("Invalid email" in e["error"] for e in result["errors"])

    leads = owner.api.get(f"/organizations/{oid}/leads", params={"sort": "email"}).json()["items"]
    ada = next(lead for lead in leads if lead["email"] == "ada@engines.com")
    assert (ada["first_name"], ada["last_name"]) == ("Ada", "Lovelace")
    assert ada["company"]["domain"] == "engines.com"
    assert ada["source"] == "csv_import"
    gmail = next(lead for lead in leads if lead["email"] == "someone@gmail.com")
    assert gmail["company"] is None, "free email domains must not create companies"


def test_identical_import_is_replayed_not_duplicated(org: tuple[Any, str]) -> None:
    owner, oid = org
    first = _run(owner.api, oid).json()
    again = _run(owner.api, oid)
    assert again.status_code == 200
    assert again.json()["id"] == first["id"] and again.json()["replayed"] is True
    assert owner.api.get(f"/organizations/{oid}/leads").json()["total"] == 3


def test_skip_policy_leaves_existing_leads_untouched(org: tuple[Any, str]) -> None:
    owner, oid = org
    owner.api.post(f"/organizations/{oid}/leads", {"email": "ada@engines.com", "title": "Founder"})
    result = _run(owner.api, oid).json()
    assert result["created_count"] == 2 and result["skipped_count"] == 2
    lead = owner.api.get(f"/organizations/{oid}/leads", params={"q": "ada@"}).json()["items"][0]
    assert lead["title"] == "Founder"


def test_update_policy_fills_fields_without_blanking(org: tuple[Any, str]) -> None:
    owner, oid = org
    owner.api.post(
        f"/organizations/{oid}/leads",
        {"email": "grace@navy.mil", "phone": "+1 555 0100", "title": "Captain"},
    )
    result = _run(owner.api, oid, duplicate_policy="update").json()
    assert result["updated_count"] == 1
    lead = owner.api.get(f"/organizations/{oid}/leads", params={"q": "grace"}).json()["items"][0]
    assert lead["title"] == "Admiral"
    assert lead["phone"] == "+1 555 0100", "blank CSV cells must not erase data"


def test_unmapped_columns_become_custom_fields(org: tuple[Any, str]) -> None:
    owner, oid = org
    _run(owner.api, oid, unmapped_as_custom_fields=True)
    lead = owner.api.get(f"/organizations/{oid}/leads", params={"q": "ada@"}).json()["items"][0]
    assert lead["custom_fields"] == {"Notes": "met at expo"}


def test_import_is_traceable(org: tuple[Any, str]) -> None:
    owner, oid = org
    result = _run(owner.api, oid).json()
    leads = owner.api.get(f"/organizations/{oid}/leads", params={"import_id": result["id"]}).json()
    assert leads["total"] == 3
    detail = owner.api.get(f"/organizations/{oid}/leads/{leads['items'][0]['id']}").json()
    assert detail["activities"][0]["type"] == "imported"
    assert owner.api.get(f"/organizations/{oid}/lead-imports/{result['id']}").status_code == 200


@pytest.mark.parametrize(
    ("content", "mapping"),
    [
        ("", {"Email": "email"}),
        ("Email\n", {"Missing": "email"}),
        ("a,a\n1,2\n", {"a": "email"}),
    ],
)
def test_invalid_files_rejected(
    org: tuple[Any, str], content: str, mapping: dict[str, str]
) -> None:
    owner, oid = org
    r = owner.api.post(
        f"/organizations/{oid}/lead-imports",
        {"filename": "x.csv", "content": content or " ", "mapping": mapping},
    )
    assert r.status_code == 422, r.text


def test_semicolon_delimited_file_and_bom(org: tuple[Any, str]) -> None:
    owner, oid = org
    content = "﻿Email;Tags\nx@corp.example.com;a;b\n"
    r = owner.api.post(
        f"/organizations/{oid}/lead-imports",
        {"filename": "x.csv", "content": content, "mapping": {"Email": "email", "Tags": "tags"}},
    )
    assert r.status_code == 201, r.text
    assert r.json()["created_count"] == 1
