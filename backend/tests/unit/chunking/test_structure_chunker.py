import random
from uuid import uuid4

from dms_core.chunking.chunk_id import make_chunk_id
from dms_core.chunking.structure_chunker import chunk_blocks
from dms_core.chunking.tokens import estimate_tokens, normalize_text
from dms_core.models import Block
from dms_core.versioning.delta_plan import plan_delta

WORDS = "policy officer shall submit report review approve budget agency circular procedure record retention public service data access request".split()


def make_sentence(rng: random.Random, index: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(12)).capitalize() + f" item {index}."


def make_document(sections: int = 10, paragraphs: int = 6, sentences: int = 6, seed: int = 7) -> list[Block]:
    rng = random.Random(seed)
    blocks: list[Block] = []
    counter = 0
    for section in range(sections):
        blocks.append(Block(type="heading", text=f"Section {section + 1}", level=1, page=section + 1, order=len(blocks)))
        for _ in range(paragraphs):
            text = " ".join(make_sentence(rng, counter + offset) for offset in range(sentences))
            counter += sentences
            blocks.append(Block(type="paragraph", text=text, page=section + 1, order=len(blocks)))
    return blocks


def test_tokens_and_normalization():
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 40) == 10
    assert normalize_text("  Hello \n  World\t") == "hello world"


def test_chunk_id_ignores_whitespace_and_case():
    document_id = uuid4()
    assert make_chunk_id(document_id, "Hello  World") == make_chunk_id(document_id, "hello world")
    assert make_chunk_id(document_id, "a").startswith(f"{document_id}:")


def test_chunks_respect_sizes_and_metadata():
    document_id = uuid4()
    chunks = chunk_blocks(document_id, make_document())
    assert len(chunks) >= 10
    assert [chunk.order for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert chunk.token_count <= 500
        assert chunk.heading_path and chunk.heading_path[0].startswith("Section ")
        assert chunk.page_from is not None and chunk.page_to is not None
        assert chunk.id.startswith(str(document_id))
    first_of_section = {}
    for chunk in chunks:
        first_of_section.setdefault(chunk.heading_path[0], chunk)
    for heading, chunk in first_of_section.items():
        assert chunk.text.startswith(heading)


def test_editing_one_section_changes_few_chunk_ids():
    document_id = uuid4()
    original = make_document()
    edited = [block.model_copy() for block in original]
    section_five_paragraphs = [i for i, b in enumerate(edited) if b.type == "paragraph" and b.page == 5]
    target = edited[section_five_paragraphs[2]]
    edited[section_five_paragraphs[2]] = target.model_copy(update={"text": target.text.replace("item", "entry", 1)})
    old_ids = [chunk.id for chunk in chunk_blocks(document_id, original)]
    new_ids = [chunk.id for chunk in chunk_blocks(document_id, edited)]
    changed = set(new_ids) - set(old_ids)
    assert 1 <= len(changed) <= 2
    plan = plan_delta(old_ids, new_ids)
    assert not plan.unchanged
    assert plan.old_root != plan.new_root
    assert len(plan.reused) / len(new_ids) >= 0.8


def test_identical_input_is_unchanged():
    document_id = uuid4()
    blocks = make_document()
    old_ids = [chunk.id for chunk in chunk_blocks(document_id, blocks)]
    new_ids = [chunk.id for chunk in chunk_blocks(document_id, blocks)]
    assert plan_delta(old_ids, new_ids).unchanged


def test_nested_heading_path():
    blocks = [
        Block(type="heading", text="Chapter", level=1),
        Block(type="heading", text="Part A", level=2),
        Block(type="paragraph", text="Alpha text."),
        Block(type="heading", text="Part B", level=2),
        Block(type="paragraph", text="Beta text."),
        Block(type="heading", text="Next", level=1),
        Block(type="paragraph", text="Gamma text."),
    ]
    chunks = chunk_blocks(uuid4(), blocks)
    paths = [chunk.heading_path for chunk in chunks]
    assert ["Chapter", "Part A"] in paths
    assert ["Chapter", "Part B"] in paths
    assert ["Next"] in paths


def test_overlap_only_within_section():
    blocks = make_document(sections=2, paragraphs=8)
    chunks = chunk_blocks(uuid4(), blocks)
    section_two_first = next(chunk for chunk in chunks if chunk.heading_path == ["Section 2"])
    assert section_two_first.text.startswith("Section 2")
    section_one = [chunk for chunk in chunks if chunk.heading_path == ["Section 1"]]
    assert len(section_one) >= 2
    last_sentence_of_first = section_one[0].text.rsplit(". ", 1)[-1]
    assert last_sentence_of_first in section_one[1].text


def test_large_table_split_on_rows_only():
    rows = [f"name: person {i} | role: officer number {i} | dept: finance" for i in range(200)]
    blocks = [Block(type="heading", text="Staff", level=1), Block(type="table", text="\n".join(rows))]
    chunks = chunk_blocks(uuid4(), blocks)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= 500
        for line in chunk.text.split("\n"):
            if line.startswith("name:"):
                assert line in rows


def test_long_paragraph_split_on_sentences():
    text = " ".join(f"This is sentence number {i} about the policy." for i in range(300))
    chunks = chunk_blocks(uuid4(), [Block(type="paragraph", text=text)])
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= 500
        assert chunk.text.rstrip().endswith(".")


def test_duplicate_chunk_ids_are_suffixed():
    blocks = [
        Block(type="heading", text="Same", level=1),
        Block(type="paragraph", text="Repeated body."),
        Block(type="heading", text="Same", level=1),
        Block(type="paragraph", text="Repeated body."),
    ]
    chunks = chunk_blocks(uuid4(), blocks)
    assert len({chunk.id for chunk in chunks}) == len(chunks)
    assert chunks[1].id == f"{chunks[0].id}:2"
