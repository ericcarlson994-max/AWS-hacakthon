from dms_core.enrich.doctype import infer_doctype, resolve_doctype


def test_llm_doctype_wins_when_specific():
    assert resolve_doctype("policy", "Minit Mesyuarat", None, None) == "policy"


def test_malay_minutes_fallback():
    assert resolve_doctype("other", "Minit Mesyuarat Pengurusan Bil. 6/2026", "minutes.pdf", "") == "minutes"


def test_chinese_and_filename_fallbacks():
    assert infer_doctype("数据共享指南") == "guideline"
    assert infer_doctype(None, "pekeliling_2026.docx") == "circular"
    assert resolve_doctype("other", "Untitled document", "notes.docx", "random text") == "other"


def test_word_boundaries_avoid_false_hits():
    assert infer_doctype("Reporter handbook") is None
