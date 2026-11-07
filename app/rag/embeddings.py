from sentence_transformers import SentenceTransformer


class EmbeddingService:

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model = SentenceTransformer(
            model_name,
        )

    def embed(
        self,
        text: str,
    ) -> list[float]:

        return self.model.encode(
            text,
            normalize_embeddings=True,
        ).tolist()

    def embed_many(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        if not texts:
            return []
        vectors = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]
