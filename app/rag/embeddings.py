from sentence_transformers import SentenceTransformer


class EmbeddingService:

    def __init__(self) -> None:
        self.model = SentenceTransformer(
            "all-MiniLM-L6-v2",
        )

    def embed(
        self,
        text: str,
    ) -> list[float]:

        return self.model.encode(
            text,
            normalize_embeddings=True,
        ).tolist()
