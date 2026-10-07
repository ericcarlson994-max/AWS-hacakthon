import json

from dms_adapters.fakes.ai import FakeLlm
from dms_core.enrich.metadata import normalize_date, parse_enrichment, to_document_meta
from dms_core.enrich.prompts import (
    cluster_summary_messages,
    enrichment_messages,
    root_summary_messages,
    single_summary_messages,
)


def test_parse_fenced_json_with_malay_date_and_trailing_text():
    raw = (
        "Here you go:\n```json\n"
        + json.dumps(
            {
                "title": "  Pekeliling Perbendaharaan  ",
                "doctype": "Circular",
                "agency": "",
                "reference_no": "PK/1/2026",
                "effective_date": "1 Mac 2026",
                "supersedes_ref": None,
                "language": "ms",
                "tags": ["Finance", "finance", "Travel"],
            }
        )
        + "\n```\nHope this helps."
    )
    result = parse_enrichment(raw)
    assert result.title == "Pekeliling Perbendaharaan"
    assert result.doctype == "circular"
    assert result.agency is None
    assert result.reference_no == "PK/1/2026"
    assert result.effective_date == "2026-03-01"
    assert result.language == "ms"
    assert result.tags == ["Finance", "Travel"]
    meta = to_document_meta(result)
    assert meta.reference_no == "PK/1/2026"
    assert meta.effective_date == "2026-03-01"


def test_unknown_doctype_and_garbage():
    assert parse_enrichment('{"doctype": "memo"}').doctype == "other"
    empty = parse_enrichment("not json at all")
    assert empty.doctype == "other"
    assert empty.title is None


def test_date_formats():
    assert normalize_date("2026-03-01") == "2026-03-01"
    assert normalize_date("1/3/2026") == "2026-03-01"
    assert normalize_date("1 March 2026") == "2026-03-01"
    assert normalize_date("15 Disember 2025") == "2025-12-15"
    assert normalize_date("March 5, 2026") == "2026-03-05"
    assert normalize_date("31/2/2026") is None
    assert normalize_date("soon") is None


def test_prompts_roundtrip_with_fake_llm():
    llm = FakeLlm()
    messages = enrichment_messages("CIRCULAR\nRef: MOF/CIR/2026/01\nEffective 2026-03-01\n" + "x" * 10000, "c.pdf", ["Finance"])
    assert len(messages[-1]["content"]) < 6500
    result = parse_enrichment(llm.complete(messages, json_mode=True))
    assert result.doctype in ("policy", "sop", "circular", "guideline", "report", "minutes", "other")
    assert result.reference_no == "MOF/CIR/2026/01"
    assert result.effective_date == "2026-03-01"
    for builder in (cluster_summary_messages, root_summary_messages):
        assert builder(["a", "b"])[-1]["role"] == "user"
    assert "150 words" in single_summary_messages("abc")[-1]["content"]
