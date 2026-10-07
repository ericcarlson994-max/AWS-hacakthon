import json

from dms_adapters.fakes.ai import FakeLlm
from dms_core.enrich.prompts import enrichment_messages

TAXONOMY = ["Budget", "Meetings", "Procurement"]


def enrich(text: str, filename: str) -> dict:
    return json.loads(FakeLlm().complete(enrichment_messages(text, filename, TAXONOMY), json_mode=True))


def test_system_prompt_does_not_drive_doctype():
    result = enrich("Quarterly Budget Q3 2026\nItem: Salaries | Allocated: 1000", "quarterly_budget_q3_2026.xlsx")
    assert result["doctype"] == "other"
    assert result["title"] == "Quarterly Budget Q3 2026"


def test_doctype_follows_filename_then_text():
    assert enrich("Body text", "circular_2024_07_remote_work.pdf")["doctype"] == "circular"
    assert enrich("Body text", "sop_claims_submission.pdf")["doctype"] == "sop"
    assert enrich("Body text", "policy_procurement.docx")["doctype"] == "policy"
    assert enrich("Minit Mesyuarat Jawatankuasa", "scan.pdf")["doctype"] == "minutes"
    assert enrich("Annual report on digital services. The meeting noted progress.", "scan.pdf")["doctype"] == "report"
