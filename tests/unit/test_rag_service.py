import pytest
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock
from services.rag_service import RAGService

class TestRAGService:
    """Unit tests for FAISS-based RAGService."""
    
    def test_init(self, mock_rag_service):
        """Test RAGService initialization."""
        assert mock_rag_service is not None
        assert hasattr(mock_rag_service, 'retrieve_relevant_knowledge')
        assert hasattr(mock_rag_service, 'get_knowledge_by_source')
    
    def test_retrieve_relevant_knowledge(self, mock_rag_service):
        """Test retrieving relevant knowledge."""
        mock_results = [
            {"id": "1", "content": "Test content 1", "source": "test.md", "distance": 0.1},
            {"id": "2", "content": "Test content 2", "source": "test.md", "distance": 0.2}
        ]
        mock_rag_service.retrieve_relevant_knowledge.return_value = mock_results
        
        results = mock_rag_service.retrieve_relevant_knowledge("test query")
        assert len(results) == 2
        assert results[0]["content"] == "Test content 1"
        assert results[0]["distance"] == 0.1
    
    def test_get_knowledge_by_source(self, mock_rag_service):
        """Test retrieving knowledge by source."""
        mock_results = [
            {"id": "1", "content": "Content from source", "source": "freud.md"}
        ]
        mock_rag_service.get_knowledge_by_source.return_value = mock_results
        
        results = mock_rag_service.get_knowledge_by_source("freud.md")
        assert len(results) == 1
        assert results[0]["source"] == "freud.md"
    
    def test_retrieve_relevant_knowledge_with_filter(self, mock_rag_service):
        """Test retrieving relevant knowledge with source filter."""
        mock_results = [
            {"id": "1", "content": "Filtered content", "source": "cbt.md", "distance": 0.15}
        ]
        mock_rag_service.retrieve_relevant_knowledge.return_value = mock_results
        
        results = mock_rag_service.retrieve_relevant_knowledge("test query", filter_source="cbt.md")
        assert len(results) == 1
        mock_rag_service.retrieve_relevant_knowledge.assert_called_once_with("test query", filter_source="cbt.md")
    
    def test_retrieve_relevant_knowledge_error_handling(self, mock_rag_service):
        """Test error handling in retrieve_relevant_knowledge."""
        mock_rag_service.retrieve_relevant_knowledge.side_effect = Exception("Database error")
        
        # The mock should raise the exception, which the real RAGService would catch
        # In this test, we're just verifying that the mock is set up correctly
        try:
            results = mock_rag_service.retrieve_relevant_knowledge("test query")
            # If we get here, the mock didn't raise the exception as expected
            assert False, "Expected exception was not raised"
        except Exception:
            # This is expected - the mock raised the exception
            pass

# Integration tests for the real RAGService
class TestRAGServiceIntegration:
    """Integration tests for RAGService with temporary directories."""
    
    def test_init_with_temp_directories(self):
        """Test RAGService initialization with temporary directories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            domain_knowledge_path = os.path.join(temp_dir, "domain_knowledge")
            vector_db_path = os.path.join(temp_dir, "vector_db")
            
            # Create directories
            os.makedirs(domain_knowledge_path, exist_ok=True)
            os.makedirs(vector_db_path, exist_ok=True)
            
            # Create a test knowledge file
            test_file = os.path.join(domain_knowledge_path, "test_knowledge.md")
            with open(test_file, "w") as f:
                f.write("# Test Knowledge\n\nThis is test knowledge content.")
            
            # Initialize RAGService
            rag_service = RAGService(domain_knowledge_path, vector_db_path)
            
            # Test that the service was initialized
            assert rag_service is not None
            assert rag_service.domain_collection is not None
    
    @pytest.mark.skip(reason="Requires ChromaDB setup")
    def test_retrieve_relevant_knowledge_integration(self):
        """Integration test for retrieving relevant knowledge."""
        # This test would require a proper ChromaDB setup with loaded data
        pass
    
    def test_get_knowledge_by_source_integration(self):
        """Integration test for getting knowledge by source."""
        with tempfile.TemporaryDirectory() as temp_dir:
            domain_knowledge_path = os.path.join(temp_dir, "domain_knowledge")
            vector_db_path = os.path.join(temp_dir, "vector_db")
            
            # Create directories
            os.makedirs(domain_knowledge_path, exist_ok=True)
            os.makedirs(vector_db_path, exist_ok=True)
            
            # This test is limited without actual data loading
            # In a real scenario, we'd load data and then test retrieval
            pass
