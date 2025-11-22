import logging

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingUtils:
    """Utility class for generating text embeddings."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", use_onnx: bool = True):
        """
        Initialize the embedding utility.

        Args:
            model_name (str): Name of the sentence transformer model to use.
            use_onnx (bool): Whether to use ONNX backend for faster inference.
        """
        self.model_name = model_name
        self.use_onnx = use_onnx

        try:
            # Initialize model with ONNX backend if requested and available
            if use_onnx:
                logger.info(
                    f"Loading {model_name} with ONNX backend for optimized performance"
                )
                self.model = SentenceTransformer(model_name, backend="onnx")
            else:
                logger.info(f"Loading {model_name} with default PyTorch backend")
                self.model = SentenceTransformer(model_name)

        except Exception as e:
            # Fallback to PyTorch backend if ONNX fails
            logger.warning(
                f"Failed to load with ONNX backend, falling back to PyTorch: {e}"
            )
            self.model = SentenceTransformer(model_name)
            self.use_onnx = False

    def generate_embedding(self, text: str) -> list[float]:
        """
        Generate embedding for a single text string.

        Args:
            text (str): Text to embed.

        Returns:
            List[float]: Embedding vector.
        """
        embedding = self.model.encode(text)
        return embedding.tolist()

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for a list of text strings.

        Args:
            texts (List[str]): List of texts to embed.

        Returns:
            List[List[float]]: List of embedding vectors.
        """
        embeddings = self.model.encode(texts)
        return [embedding.tolist() for embedding in embeddings]

    def get_similarity(self, embedding1: list[float], embedding2: list[float]) -> float:
        """
        Calculate cosine similarity between two embeddings.

        Args:
            embedding1 (List[float]): First embedding.
            embedding2 (List[float]): Second embedding.

        Returns:
            float: Cosine similarity score.
        """
        # Convert to numpy arrays
        vec1 = np.array(embedding1)
        vec2 = np.array(embedding2)

        # Calculate cosine similarity
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        similarity = dot_product / (norm1 * norm2)

        # Clamp to [-1, 1] to handle floating point precision issues
        similarity = np.clip(similarity, -1.0, 1.0)

        return float(similarity)
