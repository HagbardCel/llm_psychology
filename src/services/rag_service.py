import os
import uuid
import logging
from typing import List, Dict, Optional
import chromadb
from chromadb import Collection
from models.data_models import DomainKnowledgeChunk
from utils.embedding_utils import EmbeddingUtils
from exceptions import RAGServiceError

logger = logging.getLogger(__name__)

class RAGService:
    """Service for handling the Retrieval-Augmented Generation system."""
    
    def __init__(self, domain_knowledge_path: str, vector_db_path: str):
        """
        Initialize the RAG service.
        
        Args:
            domain_knowledge_path (str): Path to the domain knowledge files.
            vector_db_path (str): Path to the vector database.
        """
        self.domain_knowledge_path = domain_knowledge_path
        self.vector_db_path = vector_db_path
        self.embedding_utils = EmbeddingUtils()
        
        # Initialize ChromaDB client with new configuration
        self.chroma_client = chromadb.PersistentClient(path=vector_db_path)
        
        # Get or create the domain knowledge collection
        self.domain_collection = self.chroma_client.get_or_create_collection("domain_knowledge")
        
        # Load domain knowledge if collection is empty
        if self.domain_collection.count() == 0:
            self._load_domain_knowledge()
    
    def _load_domain_knowledge(self):
        """Load domain knowledge from text files into the vector database."""
        logger.info("Loading domain knowledge into vector database...")
        
        documents = []
        metadatas = []
        ids = []
        
        chunk_id = 0
        
        # First, load from the old domain_knowledge_path for backward compatibility
        if os.path.exists(self.domain_knowledge_path):
            for filename in os.listdir(self.domain_knowledge_path):
                if filename.endswith(".md"):
                    file_path = os.path.join(self.domain_knowledge_path, filename)
                    
                    with open(file_path, "r", encoding="utf-8") as file:
                        content = file.read()
                        
                        # Split content into chunks (simple splitting for now)
                        # In a real implementation, you'd use a more sophisticated chunking strategy
                        paragraphs = content.split("\n\n")
                        
                        for paragraph in paragraphs:
                            paragraph = paragraph.strip()
                            if paragraph:
                                documents.append(paragraph)
                                metadatas.append({"source": filename})
                                ids.append(f"chunk_{chunk_id}")
                                chunk_id += 1
        
        # Then, load from the new styles directory
        styles_dir = "src/styles"
        if os.path.exists(styles_dir):
            for style_dir in os.listdir(styles_dir):
                style_path = os.path.join(styles_dir, style_dir)
                if os.path.isdir(style_path):
                    knowledge_file = os.path.join(style_path, "knowledge.md")
                    if os.path.exists(knowledge_file):
                        with open(knowledge_file, "r", encoding="utf-8") as file:
                            content = file.read()
                            
                            # Split content into chunks
                            paragraphs = content.split("\n\n")
                            
                            for paragraph in paragraphs:
                                paragraph = paragraph.strip()
                                if paragraph:
                                    documents.append(paragraph)
                                    metadatas.append({"source": f"{style_dir}.md"})  # Use style_dir.md as source for consistency
                                    ids.append(f"chunk_{chunk_id}")
                                    chunk_id += 1
        
        # Add chunks to vector database
        if documents:
            self.domain_collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            
            logger.info(f"Loaded {len(documents)} chunks into vector database.")
    
    def retrieve_relevant_knowledge(self, query: str, n_results: int = 3, filter_source: Optional[str] = None) -> List[Dict[str, any]]:
        """
        Retrieve relevant domain knowledge based on a query.
        
        Args:
            query (str): The query to search for relevant knowledge.
            n_results (int): Number of results to return.
            filter_source (Optional[str]): Optional source filter (e.g., "freud.md").
            
        Returns:
            List[Dict[str, any]]: List of relevant knowledge chunks with their metadata.
        """
        try:
            # Prepare query parameters
            query_params = {
                "query_texts": [query],
                "n_results": n_results
            }
            
            # Add source filter if specified
            if filter_source:
                query_params["where"] = {"source": filter_source}
            
            # Search the vector database
            results = self.domain_collection.query(**query_params)
            
            # Format results
            relevant_knowledge = []
            for i in range(len(results["ids"][0])):
                knowledge_chunk = {
                    "id": results["ids"][0][i],
                    "content": results["documents"][0][i],
                    "source": results["metadatas"][0][i]["source"],
                    "distance": results["distances"][0][i] if "distances" in results and results["distances"][0][i] is not None else None
                }
                relevant_knowledge.append(knowledge_chunk)
            
            return relevant_knowledge
        except Exception as e:
            logger.error(f"Error retrieving relevant knowledge: {e}", exc_info=True)
            return []
    
    def get_knowledge_by_source(self, source: str) -> List[Dict[str, any]]:
        """
        Retrieve all knowledge chunks from a specific source.
        
        Args:
            source (str): The source file name.
            
        Returns:
            List[Dict[str, any]]: List of knowledge chunks from the specified source.
        """
        try:
            results = self.domain_collection.get(
                where={"source": source}
            )
            
            knowledge_chunks = []
            for i in range(len(results["ids"])):
                knowledge_chunk = {
                    "id": results["ids"][i],
                    "content": results["documents"][i],
                    "source": results["metadatas"][i]["source"]
                }
                knowledge_chunks.append(knowledge_chunk)
            
            return knowledge_chunks
        except Exception as e:
            logger.error(f"Error retrieving knowledge by source: {e}", exc_info=True)
            return []
    
    def add_user_session_to_rag(self, session_summary: str, keywords: List[str], session_id: str):
        """
        Add a user session summary to the RAG system for future retrieval.
        This would be used for user record RAG (future feature).
        
        Args:
            session_summary (str): Summary of the session.
            keywords (List[str]): Keywords from the session.
            session_id (str): ID of the session.
        """
        # This is a placeholder for future implementation
        # It would involve creating a separate collection for user records
        pass
    
    def retrieve_relevant_user_history(self, query: str, user_id: str, n_results: int = 2) -> List[Dict[str, any]]:
        """
        Retrieve relevant user history based on a query.
        This would be used for user record RAG (future feature).
        
        Args:
            query (str): The query to search for relevant history.
            user_id (str): The ID of the user.
            n_results (int): Number of results to return.
            
        Returns:
            List[Dict[str, any]]: List of relevant user history chunks.
        """
        # This is a placeholder for future implementation
        return []
