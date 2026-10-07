from uuid import uuid4

from dms_adapters.fakes.ai import FakeEmbedder, FakeLlm
from dms_core.models import Chunk
from dms_core.raptor.build import build_tree, node_id, refresh_tree, root_of
from dms_core.raptor.cluster import cluster_vectors

TOPICS = [
    "annual leave entitlement days carry forward approval head of department",
    "travel claims mileage allowance hotel receipts reimbursement treasury",
    "procurement tender quotation vendor evaluation committee award",
    "information security password encryption access control incident",
    "work from home eligibility equipment attendance supervisor",
]


def make_chunks(document_id, count, embedder):
    chunks = []
    for index in range(count):
        topic = TOPICS[index % len(TOPICS)]
        text = f"Section {index}. {topic}. Clause {index} details {topic.split()[0]} rule number {index}."
        chunks.append(Chunk(id=f"c{index}", document_id=document_id, order=index, text=text))
    vectors = embedder.embed([chunk.text for chunk in chunks])
    return [chunk.model_copy(update={"embedding": vector}) for chunk, vector in zip(chunks, vectors)]


def test_cluster_small_and_large():
    assert cluster_vectors([[1.0, 0.0], [0.0, 1.0]]) == [[0, 1]]
    embedder = FakeEmbedder(dim=64)
    vectors = embedder.embed([TOPICS[i % 5] + f" {i}" for i in range(20)])
    groups = cluster_vectors(vectors)
    assert sorted(index for group in groups for index in group) == list(range(20))
    assert all(groups)


def test_small_document_single_root_level_one():
    document_id = uuid4()
    embedder = FakeEmbedder(dim=64)
    llm = FakeLlm()
    chunks = make_chunks(document_id, 6, embedder)
    nodes = build_tree(document_id, 1, chunks, llm, embedder, model="m1")
    assert len(nodes) == 1
    root = nodes[0]
    assert root.level == 1
    assert root.children == [f"c{i}" for i in range(6)]
    assert root.embedding is not None
    assert root.id == node_id(document_id, 1, root.children)
    assert all(call["model"] == "m1" for call in llm.calls)


def test_thirty_chunks_depth_and_single_root():
    document_id = uuid4()
    embedder = FakeEmbedder(dim=64)
    llm = FakeLlm()
    chunks = make_chunks(document_id, 30, embedder)
    nodes = build_tree(document_id, 2, chunks, llm, embedder)
    levels = [node.level for node in nodes]
    assert max(levels) <= 3
    root = root_of(nodes)
    assert root is not None
    assert levels.count(max(levels)) == 1
    leaf_children = sorted(child for node in nodes if node.level == 1 for child in node.children)
    assert leaf_children == sorted(chunk.id for chunk in chunks)
    ids = {node.id for node in nodes}
    for node in nodes:
        if node.level > 1:
            assert all(child in ids for child in node.children)
    assert all(node.embedding for node in nodes)
    assert all(node.version_no == 2 for node in nodes)


def test_chunks_without_embeddings_are_embedded():
    document_id = uuid4()
    embedder = FakeEmbedder(dim=64)
    chunks = [chunk.model_copy(update={"embedding": None}) for chunk in make_chunks(document_id, 12, embedder)]
    nodes = build_tree(document_id, 1, chunks, FakeLlm(), embedder)
    assert root_of(nodes) is not None


def test_refresh_one_changed_leaf_touches_few_nodes():
    document_id = uuid4()
    embedder = FakeEmbedder(dim=64)
    chunks = make_chunks(document_id, 30, embedder)
    full_llm = FakeLlm()
    nodes = build_tree(document_id, 1, chunks, full_llm, embedder)
    full_count = len(full_llm.calls)

    replaced = chunks[7]
    new_text = replaced.text + " amended with new rule"
    new_chunk = Chunk(
        id="c7b", document_id=document_id, order=7, text=new_text, embedding=embedder.embed([new_text])[0]
    )
    new_chunks = [new_chunk if chunk.id == "c7" else chunk for chunk in chunks]
    refresh_llm = FakeLlm()
    refreshed, count = refresh_tree(
        nodes, new_chunks, [], ["c7b"], ["c7"], refresh_llm, embedder, version_no=2
    )
    assert count == len(refresh_llm.calls)
    assert count < full_count
    assert count <= max(node.level for node in nodes) + 1
    root = root_of(refreshed)
    assert root is not None
    leaf_children = {child for node in refreshed if node.level == 1 for child in node.children}
    assert "c7b" in leaf_children and "c7" not in leaf_children
    assert {node.id for node in refreshed} == {node.id for node in nodes}
    assert all(node.version_no == 2 for node in refreshed)


def test_refresh_dirty_node_resummarizes_ancestors():
    document_id = uuid4()
    embedder = FakeEmbedder(dim=64)
    chunks = make_chunks(document_id, 30, embedder)
    nodes = build_tree(document_id, 1, chunks, FakeLlm(), embedder)
    leaf_node = next(node for node in nodes if node.level == 1)
    _, count = refresh_tree(nodes, chunks, [leaf_node.id], [], [], FakeLlm(), embedder)
    assert count == root_of(nodes).level


def test_refresh_small_doc_rebuilds():
    document_id = uuid4()
    embedder = FakeEmbedder(dim=64)
    chunks = make_chunks(document_id, 5, embedder)
    refreshed, count = refresh_tree([], chunks, [], [], [], FakeLlm(), embedder)
    assert count == len(refreshed) == 1
