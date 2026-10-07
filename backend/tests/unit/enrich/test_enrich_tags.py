import math

from dms_core.enrich.tags import match_llm_tags, recompute_centroid, suggest_tags
from dms_core.models import TagRow


def test_suggest_tags_respects_threshold_and_skips_missing_centroid():
    tags = [
        TagRow(id=1, name="Finance", centroid=[1.0, 0.0]),
        TagRow(id=2, name="HR", centroid=[0.0, 1.0]),
        TagRow(id=3, name="Mixed", centroid=[0.6, 0.8]),
        TagRow(id=4, name="Empty", centroid=None),
    ]
    result = suggest_tags([1.0, 0.0], tags)
    names = [(tag.name, round(score, 2)) for tag, score in result]
    assert names == [("Finance", 1.0), ("Mixed", 0.6)]
    assert [tag.name for tag, _ in suggest_tags([1.0, 0.0], tags, threshold=0.7)] == ["Finance"]


def test_match_llm_tags_case_insensitive():
    tags = [TagRow(id=1, name="Finance"), TagRow(id=2, name="Human Resources")]
    matched = match_llm_tags(["finance", "HUMAN  resources", "unknown", "Finance"], tags)
    assert [tag.id for tag in matched] == [1, 2]


def test_recompute_centroid_normalized_mean():
    centroid = recompute_centroid([[1.0, 0.0], [0.0, 1.0]])
    assert centroid is not None
    assert math.isclose(centroid[0], math.sqrt(0.5))
    assert math.isclose(sum(x * x for x in centroid), 1.0)
    assert recompute_centroid([]) is None
