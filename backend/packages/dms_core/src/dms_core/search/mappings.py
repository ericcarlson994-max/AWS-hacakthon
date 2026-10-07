from typing import Any

CHUNKS_INDEX = "dms_chunks"
TITLES_INDEX = "dms_titles"


def chunks_index_body(dim: int = 1024) -> dict[str, Any]:
    return {
        "settings": {
            "index": {"knn": True, "number_of_shards": 1, "number_of_replicas": 0},
        },
        "mappings": {
            "properties": {
                "chunk_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "version_id": {"type": "keyword"},
                "level": {"type": "integer"},
                "allowed_groups": {"type": "keyword"},
                "department_id": {"type": "keyword"},
                "doctype": {"type": "keyword"},
                "tags": {"type": "keyword"},
                "title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
                "text": {
                    "type": "text",
                    "analyzer": "standard",
                    "fields": {"cjk": {"type": "text", "analyzer": "cjk"}},
                },
                "heading_path": {"type": "text"},
                "page_from": {"type": "integer"},
                "effective_date": {"type": "date", "ignore_malformed": True},
                "superseded": {"type": "boolean"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": dim,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                        "parameters": {"ef_construction": 128, "m": 16},
                    },
                },
            }
        },
    }


def titles_index_body() -> dict[str, Any]:
    return {
        "settings": {
            "index": {"number_of_shards": 1, "number_of_replicas": 0, "max_ngram_diff": 18},
            "analysis": {
                "tokenizer": {
                    "edge_tok": {
                        "type": "edge_ngram",
                        "min_gram": 2,
                        "max_gram": 20,
                        "token_chars": ["letter", "digit"],
                    },
                    "tri_tok": {
                        "type": "ngram",
                        "min_gram": 3,
                        "max_gram": 3,
                        "token_chars": ["letter", "digit"],
                    },
                },
                "filter": {
                    "shingle_filter": {
                        "type": "shingle",
                        "min_shingle_size": 2,
                        "max_shingle_size": 3,
                    }
                },
                "analyzer": {
                    "plain": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "asciifolding"]},
                    "edge": {"type": "custom", "tokenizer": "edge_tok", "filter": ["lowercase", "asciifolding"]},
                    "tri": {"type": "custom", "tokenizer": "tri_tok", "filter": ["lowercase", "asciifolding"]},
                    "shingle": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "asciifolding", "shingle_filter"],
                    },
                },
            },
        },
        "mappings": {
            "properties": {
                "document_id": {"type": "keyword"},
                "title": {
                    "type": "text",
                    "analyzer": "plain",
                    "fields": {
                        "raw": {"type": "keyword"},
                        "edge": {"type": "text", "analyzer": "edge", "search_analyzer": "plain"},
                        "tri": {"type": "text", "analyzer": "tri", "search_analyzer": "tri"},
                        "cjk": {"type": "text", "analyzer": "cjk"},
                        "shingle": {"type": "text", "analyzer": "shingle"},
                    },
                },
                "filename": {"type": "text", "analyzer": "plain"},
                "tags": {"type": "keyword"},
                "doctype": {"type": "keyword"},
                "department_id": {"type": "keyword"},
                "allowed_groups": {"type": "keyword"},
                "superseded": {"type": "boolean"},
            }
        },
    }
