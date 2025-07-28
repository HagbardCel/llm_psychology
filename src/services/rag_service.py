import os
import uuid
from typing import List, Dict, Optional
import chromadb
from chromadb import Collection
from utils.data_models import DomainKnowledgeChunk
from utils.embedding_utils import EmbeddingUtils

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
        print("Loading domain knowledge into vector database...")
        
        documents = []
        metadatas = []
        ids = []
        
        chunk_id = 0
        
        # Iterate through domain knowledge files
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
        
        # Add chunks to vector database
        if documents:
            self.domain_collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            
            print(f"Loaded {len(documents)} chunks into vector database.")
    
    def retrieve_relevant_knowledge(self, query: str, n_results: int = 3) -> List[Dict[str, any]]:
        """
        Retrieve relevant domain knowledge based on a query.
        
        Args:
            query (str): The query to search for relevant knowledge.
            n_results (int): Number of results to return.
            
        Returns:
            List[Dict[str, any]]: List of relevant knowledge chunks with their metadata.
        """
        try:
            # Search the vector database
            results = self.domain_collection.query(
                query_texts=[query],
                n_results=n_results
            )
            
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
            print(f"Error retrieving relevant knowledge: {e}")
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
            print(f"Error retrieving knowledge by source: {e}")
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
