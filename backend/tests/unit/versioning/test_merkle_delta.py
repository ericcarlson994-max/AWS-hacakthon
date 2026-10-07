import hashlib
from uuid import uuid4

from dms_core.models import RaptorNode
from dms_core.versioning.delta_plan import plan_delta
from dms_core.versioning.diff import diff_manifests
from dms_core.versioning.merkle import merkle_root


def test_merkle_root_basics():
    assert merkle_root([]) == hashlib.sha256(b"").hexdigest()
    assert merkle_root(["a"]) == hashlib.sha256(b"a").hexdigest()
    leaf_a = hashlib.sha256(b"a").digest()
    leaf_b = hashlib.sha256(b"b").digest()
    assert merkle_root(["a", "b"]) == hashlib.sha256(leaf_a + leaf_b).hexdigest()
    leaf_c = hashlib.sha256(b"c").digest()
    assert merkle_root(["a", "b", "c"]) == hashlib.sha256(hashlib.sha256(leaf_a + leaf_b).digest() + leaf_c).hexdigest()
    assert merkle_root(["a", "b"]) != merkle_root(["b", "a"])


def test_diff_manifests_preserves_order():
    added, removed, reused = diff_manifests(["a", "b", "c"], ["c", "d", "a", "e"])
    assert added == ["d", "e"]
    assert removed == ["b"]
    assert reused == ["c", "a"]


def test_plan_unchanged_and_first_version():
    ids = ["x", "y"]
    plan = plan_delta(ids, list(ids))
    assert plan.unchanged and plan.old_root == plan.new_root
    first = plan_delta(None, ids)
    assert not first.unchanged and first.added == ids


def node(node_id: str, level: int, children: list[str], document_id) -> RaptorNode:
    return RaptorNode(id=node_id, document_id=document_id, version_no=1, level=level, summary_text="s", children=children)


def test_dirty_raptor_nodes_propagate_to_ancestors():
    document_id = uuid4()
    nodes = [
        node("n1", 1, ["c1", "c2"], document_id),
        node("n2", 1, ["c3", "c4"], document_id),
        node("n3", 1, ["c5"], document_id),
        node("m1", 2, ["n1", "n2"], document_id),
        node("m2", 2, ["n3"], document_id),
        node("root", 3, ["m1", "m2"], document_id),
    ]
    plan = plan_delta(["c1", "c2", "c3", "c4", "c5"], ["c1", "c2", "c3", "c4b", "c5"], nodes)
    assert plan.added == ["c4b"]
    assert plan.removed == ["c4"]
    assert set(plan.dirty_raptor_nodes) == {"n2", "m1", "root"}
