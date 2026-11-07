import chromadb

from app.rag.chroma_store import get_runbooks_collection


def test_new_collection_uses_cosine(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path / "new"))

    collection = get_runbooks_collection(client)

    assert collection.metadata.get("hnsw:space") == "cosine"


def test_legacy_collection_is_recreated_for_reindex(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path / "legacy"))
    legacy = client.create_collection("runbooks")
    assert (legacy.metadata or {}).get("hnsw:space") != "cosine"

    rebuilt = get_runbooks_collection(client, recreate_if_incompatible=True)

    assert rebuilt.metadata.get("hnsw:space") == "cosine"
    assert rebuilt.count() == 0
