from dms_core.models import DeltaPlan, RaptorNode
from dms_core.versioning.diff import diff_manifests
from dms_core.versioning.merkle import merkle_root


def find_dirty_raptor_nodes(raptor_nodes: list[RaptorNode], changed_ids: set[str]) -> list[str]:
    dirty: set[str] = set()
    frontier = set(changed_ids)
    while frontier:
        newly_dirty = {
            node.id
            for node in raptor_nodes
            if node.id not in dirty and frontier.intersection(node.children)
        }
        dirty |= newly_dirty
        frontier = newly_dirty
    return [node.id for node in raptor_nodes if node.id in dirty]


def plan_delta(
    old_ids: list[str] | None,
    new_ids: list[str],
    raptor_nodes: list[RaptorNode] | None = None,
) -> DeltaPlan:
    new_root = merkle_root(new_ids)
    if old_ids is None:
        return DeltaPlan(unchanged=False, old_root=None, new_root=new_root, added=list(new_ids))
    old_root = merkle_root(old_ids)
    if old_root == new_root:
        return DeltaPlan(
            unchanged=True, old_root=old_root, new_root=new_root, reused=list(new_ids)
        )
    added, removed, reused = diff_manifests(old_ids, new_ids)
    dirty = find_dirty_raptor_nodes(raptor_nodes or [], set(added) | set(removed))
    return DeltaPlan(
        unchanged=False,
        old_root=old_root,
        new_root=new_root,
        added=added,
        removed=removed,
        reused=reused,
        dirty_raptor_nodes=dirty,
    )
