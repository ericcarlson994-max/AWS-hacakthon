from __future__ import annotations

import json

QUESTION = "How many days can staff work from home?"


def test_ask_streams_tokens_citations_and_done(login, ask):
    events = ask(login("ben"), QUESTION)
    names = [name for name, _ in events]
    assert "error" not in names, events
    assert "token" in names
    assert "citations" in names
    assert names[-1] == "done"
    assert names.index("citations") > names.index("token")

    answer_text = "".join(json.loads(data).get("text", "") for name, data in events if name == "token")
    assert answer_text.strip()

    citations = next(json.loads(data) for name, data in events if name == "citations")["citations"]
    assert citations
    for citation in citations:
        assert {"n", "document_id", "title", "chunk_id", "quote"} <= set(citation)
