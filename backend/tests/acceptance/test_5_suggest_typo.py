from __future__ import annotations

TYPO_QUERY = "quartely bud"
EXPECTED_TITLE = "quarterly budget"


def budget_titles(response: dict) -> list[str]:
    return [item["title"] for item in response["documents"] if EXPECTED_TITLE in item["title"].lower()]


def test_typo_suggests_quarterly_budget_for_finance(login, suggest):
    response = suggest(login("alice"), TYPO_QUERY)
    assert budget_titles(response), response


def test_typo_does_not_leak_budget_to_hr(login, suggest):
    response = suggest(login("ben"), TYPO_QUERY)
    assert not budget_titles(response), response
    assert all(item["department_id"] != "finance" for item in response["documents"])
