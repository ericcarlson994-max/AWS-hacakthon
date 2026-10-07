import io

import openpyxl
from dms_core.enrich.titles import suggest_title
from dms_core.extract.router import extract
from dms_core.models import Block


def test_good_metadata_title_wins():
    blocks = [Block(type="heading", text="Some Heading", page=1)]
    result = suggest_title("Public Procurement Policy 2026", blocks, "proc_policy.pdf")
    assert result.source == "metadata"
    assert result.title == "Public Procurement Policy 2026"
    assert result.confidence == 0.9


def test_junk_metadata_falls_back_to_heading():
    blocks = [
        Block(type="paragraph", text="12/03/2026", page=1, order=0),
        Block(type="heading", text="Garis Panduan Kerja Dari Rumah", page=1, order=1),
        Block(type="paragraph", text="Body text.", page=1, order=2),
    ]
    result = suggest_title("Microsoft Word - doc1.docx", blocks, "doc1.docx")
    assert result.source == "heading"
    assert result.title == "Garis Panduan Kerja Dari Rumah"
    assert result.confidence == 0.75


def test_metadata_equal_to_filename_stem_is_rejected():
    blocks = [Block(type="heading", text="Annual Report", page=1)]
    result = suggest_title("annual-report_2025", blocks, "Annual Report 2025.pdf")
    assert result.source == "heading"


def test_largest_font_in_top_third_used_when_no_heading():
    blocks = [
        Block(type="paragraph", text="Ministry of Finance", page=1, order=0, font_size=10),
        Block(type="paragraph", text="Treasury Circular on Travel Claims", page=1, order=1, font_size=20),
        Block(type="paragraph", text="Body text one", page=1, order=2, font_size=10),
        Block(type="paragraph", text="Huge footer text", page=1, order=3, font_size=40),
        Block(type="paragraph", text="Body two", page=1, order=4, font_size=10),
        Block(type="paragraph", text="Body three", page=1, order=5, font_size=10),
    ]
    result = suggest_title(None, blocks, "x.pdf")
    assert result.source == "heading"
    assert result.title == "Treasury Circular on Travel Claims"


def test_no_heading_uses_cleaned_filename():
    blocks = [Block(type="paragraph", text="just some body text that is not a heading", page=1)]
    result = suggest_title(None, blocks, "work_from-home.guideline.pdf")
    assert result.source == "filename"
    assert result.title == "Work From Home Guideline"
    assert result.confidence == 0.4


def test_date_and_digit_headings_rejected():
    blocks = [
        Block(type="heading", text="1 Mac 2026", page=1, order=0),
        Block(type="heading", text="2026", page=1, order=1),
    ]
    result = suggest_title(None, blocks, "hr_leave_policy.pdf")
    assert result.source == "filename"


def test_nothing_gives_default():
    result = suggest_title(None, [], "")
    assert result.source == "default"
    assert result.title == "Untitled document"
    assert result.confidence == 0.0


def test_human_metadata_title_matching_filename_words_is_kept():
    blocks = [Block(type="heading", text="Q3 2026 Summary", page=1, order=0, level=1)]
    result = suggest_title("Quarterly Budget Q3 2026", blocks, "quarterly_budget_q3_2026.xlsx")
    assert result.source == "metadata"
    assert result.title == "Quarterly Budget Q3 2026"
    assert result.confidence == 0.9


def test_pdf_title_with_punctuation_is_kept():
    result = suggest_title("SOP: Claims Submission", [], "sop_claims_submission.pdf")
    assert result.source == "metadata"
    assert result.title == "SOP: Claims Submission"


def test_metadata_equal_to_filename_verbatim_is_rejected():
    blocks = [Block(type="heading", text="Leave Policy", page=1)]
    assert suggest_title("leave_policy", blocks, "leave_policy.docx").source == "heading"
    assert suggest_title("Leave_Policy.docx", blocks, "leave_policy.docx").source == "heading"
    assert suggest_title("leavepolicy", blocks, "leavepolicy.pdf").source == "heading"


def test_budget_workbook_cascade_gives_workbook_title():
    workbook = openpyxl.Workbook()
    workbook.properties.title = "Quarterly Budget Q3 2026"
    sheet = workbook.active
    sheet.title = "Q3 2026 Summary"
    sheet["A1"] = "Quarterly Budget Q3 2026"
    sheet["A2"] = "Finance Division - July to September 2026"
    sheet.append([])
    sheet.append(["Code", "Item", "Allocated"])
    sheet.append(["FIN-100", "Salaries", 1000])
    buffer = io.BytesIO()
    workbook.save(buffer)
    extracted = extract(buffer.getvalue(), "quarterly_budget_q3_2026.xlsx", None)
    result = suggest_title(extracted.embedded_title, extracted.blocks, "quarterly_budget_q3_2026.xlsx")
    assert result.title == "Quarterly Budget Q3 2026"
    no_metadata = suggest_title(None, extracted.blocks, "quarterly_budget_q3_2026.xlsx")
    assert no_metadata.source == "heading"
    assert no_metadata.title == "Quarterly Budget Q3 2026"
