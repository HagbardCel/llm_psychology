import logging
import os
import pickle

import faiss
import numpy as np

from utils.embedding_utils import EmbeddingUtils

logger = logging.getLogger(__name__)


class RAGService:
    """Lean FAISS-based service for Retrieval-Augmented Generation system."""

    def __init__(
        self,
        domain_knowledge_path: str,
        vector_db_path: str,
        use_onnx: bool = True,
        model_name: str = "all-MiniLM-L6-v2",
    ):
        """
        Initialize the RAG service with FAISS.

        Args:
            domain_knowledge_path (str): Path to the domain knowledge files.
            vector_db_path (str): Path to store FAISS index and metadata files.
            use_onnx (bool): Whether to use ONNX backend for embeddings.
            model_name (str): Name of the sentence transformer model to use.
        """
        self.domain_knowledge_path = domain_knowledge_path
        self.vector_db_path = vector_db_path
        self.embedding_utils = EmbeddingUtils(model_name=model_name, use_onnx=use_onnx)

        # Storage for documents and metadata
        self.documents = []
        self.metadatas = []
        self.ids = []
        self.index = None

        # Ensure vector DB directory exists
        os.makedirs(vector_db_path, exist_ok=True)

        # File paths for persistence
        self.index_path = os.path.join(vector_db_path, "faiss_index.bin")
        self.data_path = os.path.join(vector_db_path, "data.pkl")

        # Load existing index or create new one
        if self._index_exists():
            self._load_index()
        else:
            self._create_and_load_index()

    def _index_exists(self) -> bool:
        """Check if FAISS index files exist."""
        return os.path.exists(self.index_path) and os.path.exists(self.data_path)

    def _create_and_load_index(self):
        """Create new FAISS index and load domain knowledge."""
        logger.info("Creating new FAISS index and loading domain knowledge...")

        # Get embedding dimension from a sample text
        sample_embedding = self.embedding_utils.generate_embedding("sample text")
        embedding_dim = len(sample_embedding)

        # Create FAISS index (using inner product for cosine similarity with normalized vectors)
        self.index = faiss.IndexFlatIP(embedding_dim)

        # Load domain knowledge
        self._load_domain_knowledge()

        # Save index
        self._save_index()

    def _load_domain_knowledge(self):
        """Load domain knowledge from text files."""
        logger.info("Loading domain knowledge into FAISS index...")

        documents = []
        metadatas = []
        ids = []
        chunk_id = 0

        # Load from legacy domain_knowledge_path for backward compatibility
        if os.path.exists(self.domain_knowledge_path):
            for filename in os.listdir(self.domain_knowledge_path):
                if filename.endswith(".md"):
                    file_path = os.path.join(self.domain_knowledge_path, filename)
                    self._load_file(
                        file_path, filename, documents, metadatas, ids, chunk_id
                    )
                    chunk_id = len(documents)

        # Load from styles directory
        styles_dir = "src/styles"
        if os.path.exists(styles_dir):
            for style_dir in os.listdir(styles_dir):
                style_path = os.path.join(styles_dir, style_dir)
                if os.path.isdir(style_path):
                    knowledge_file = os.path.join(style_path, "knowledge.md")
                    if os.path.exists(knowledge_file):
                        self._load_file(
                            knowledge_file,
                            f"{style_dir}.md",
                            documents,
                            metadatas,
                            ids,
                            chunk_id,
                        )
                        chunk_id = len(documents)

        if documents:
            # Generate embeddings
            logger.info(f"Generating embeddings for {len(documents)} chunks...")
            embeddings = self.embedding_utils.generate_embeddings(documents)

            # Normalize embeddings for cosine similarity with inner product
            embeddings_array = np.array(embeddings, dtype=np.float32)
            faiss.normalize_L2(embeddings_array)

            # Add to FAISS index
            self.index.add(embeddings_array)

            # Store documents and metadata
            self.documents.extend(documents)
            self.metadatas.extend(metadatas)
            self.ids.extend(ids)

            logger.info(f"Loaded {len(documents)} chunks into FAISS index.")

    def _load_file(
        self,
        file_path: str,
        source_name: str,
        documents: list,
        metadatas: list,
        ids: list,
        start_chunk_id: int,
    ):
        """Load a single markdown file and split into chunks."""
        with open(file_path, encoding="utf-8") as file:
            content = file.read()

            # Split content into paragraphs
            paragraphs = content.split("\n\n")

            for i, paragraph in enumerate(paragraphs):
                paragraph = paragraph.strip()
                if paragraph:
                    documents.append(paragraph)
                    metadatas.append({"source": source_name})
                    ids.append(f"chunk_{start_chunk_id + i}")

    def _save_index(self):
        """Save FAISS index and metadata to disk."""
        if self.index is not None:
            # Save FAISS index
            faiss.write_index(self.index, self.index_path)

            # Save documents and metadata
            data = {
                "documents": self.documents,
                "metadatas": self.metadatas,
                "ids": self.ids,
            }
            with open(self.data_path, "wb") as f:
                pickle.dump(data, f)

            logger.info(f"FAISS index saved with {len(self.documents)} documents")

    def _load_index(self):
        """Load FAISS index and metadata from disk."""
        logger.info("Loading existing FAISS index...")

        # Load FAISS index
        self.index = faiss.read_index(self.index_path)

        # Load documents and metadata
        with open(self.data_path, "rb") as f:
            data = pickle.load(f)
            self.documents = data["documents"]
            self.metadatas = data["metadatas"]
            self.ids = data["ids"]

        logger.info(f"Loaded FAISS index with {len(self.documents)} documents")

    def retrieve_relevant_knowledge(
        self, query: str, n_results: int = 3, filter_source: str | None = None
    ) -> list[dict[str, any]]:
        """
        Retrieve relevant domain knowledge based on a query.

        Args:
            query (str): The query to search for relevant knowledge.
            n_results (int): Number of results to return.
            filter_source (Optional[str]): Optional source filter (e.g., "freud.md").

        Returns:
            List[Dict[str, any]]: List of relevant knowledge chunks with their metadata.
        """
        if self.index is None or len(self.documents) == 0:
            logger.warning("FAISS index is empty or not initialized")
            return []

        try:
            # Generate query embedding
            query_embedding = self.embedding_utils.generate_embedding(query)
            query_vector = np.array([query_embedding], dtype=np.float32)

            # Normalize for cosine similarity
            faiss.normalize_L2(query_vector)

            # Search FAISS index (get more results than needed for filtering)
            search_k = min(n_results * 3, len(self.documents))
            scores, indices = self.index.search(query_vector, search_k)

            # Format results
            relevant_knowledge = []
            for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
                if idx == -1:  # FAISS returns -1 for invalid indices
                    continue

                metadata = self.metadatas[idx]

                # Apply source filter if specified
                if filter_source and metadata.get("source") != filter_source:
                    continue

                knowledge_chunk = {
                    "id": self.ids[idx],
                    "content": self.documents[idx],
                    "source": metadata["source"],
                    "distance": float(1 - score),  # Convert similarity to distance
                }
                relevant_knowledge.append(knowledge_chunk)

                # Stop when we have enough results
                if len(relevant_knowledge) >= n_results:
                    break

            return relevant_knowledge

        except Exception as e:
            logger.error(f"Error retrieving relevant knowledge: {e}", exc_info=True)
            return []

    def get_knowledge_by_source(self, source: str) -> list[dict[str, any]]:
        """
        Retrieve all knowledge chunks from a specific source.

        Args:
            source (str): The source file name.

        Returns:
            List[Dict[str, any]]: List of knowledge chunks from the specified source.
        """
        try:
            knowledge_chunks = []
            for i, metadata in enumerate(self.metadatas):
                if metadata.get("source") == source:
                    knowledge_chunk = {
                        "id": self.ids[i],
                        "content": self.documents[i],
                        "source": metadata["source"],
                    }
                    knowledge_chunks.append(knowledge_chunk)

            return knowledge_chunks

        except Exception as e:
            logger.error(f"Error retrieving knowledge by source: {e}", exc_info=True)
            return []

    def add_user_session_to_rag(
        self, session_summary: str, keywords: list[str], session_id: str
    ):
        """
        Add a user session summary to the RAG system for future retrieval.
        This is a placeholder for future implementation.

        Args:
            session_summary (str): Summary of the session.
            keywords (List[str]): Keywords from the session.
            session_id (str): ID of the session.
        """
        # Placeholder for future implementation
        pass

    def retrieve_relevant_user_history(
        self, query: str, user_id: str, n_results: int = 2
    ) -> list[dict[str, any]]:
        """
        Retrieve relevant user history based on a query.
        This is a placeholder for future implementation.

        Args:
            query (str): The query to search for relevant history.
            user_id (str): The ID of the user.
            n_results (int): Number of results to return.

        Returns:
            List[Dict[str, any]]: List of relevant user history chunks.
        """
        # Placeholder for future implementation
        return []
