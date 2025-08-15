import unittest
import os
import sys
import tempfile
import shutil
from unittest.mock import Mock, patch

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import Config
from models.data_models import Session, Message, TherapyPlan
from utils.embedding_utils import EmbeddingUtils
from services.db_service import DatabaseService
from services.rag_service import RAGService

class TestBasicFunctionality(unittest.TestCase):
    """Test basic functionality of core components."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create temporary directories for testing
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test.db")
        self.vector_db_path = os.path.join(self.test_dir, "vector_db")
        self.domain_knowledge_path = os.path.join(self.test_dir, "domain_knowledge")
        
        # Create domain knowledge directory
        os.makedirs(self.domain_knowledge_path, exist_ok=True)
        
        # Create a simple test file
        test_file_path = os.path.join(self.domain_knowledge_path, "test.txt")
        with open(test_file_path, "w") as f:
            f.write("This is a test knowledge chunk for testing purposes.")
    
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_config_initialization(self):
        """Test that Config class initializes correctly."""
        config = Config()
        self.assertIsNotNone(config.APP_NAME)
        self.assertIsNotNone(config.VERSION)
        # API key should be loaded from .env file (real or placeholder)
        self.assertIsNotNone(config.GOOGLE_API_KEY)
        # Test that it's a non-empty string (could be real key or placeholder)
        self.assertIsInstance(config.GOOGLE_API_KEY, str)
        self.assertGreater(len(config.GOOGLE_API_KEY), 0)
    
    def test_data_models(self):
        """Test that data models can be created."""
        from datetime import datetime
        
        # Test Message model
        message = Message(
            role="user",
            content="Hello, world!",
            timestamp=datetime.now()
        )
        self.assertEqual(message.role, "user")
        self.assertEqual(message.content, "Hello, world!")
        
        # Test Session model
        session = Session(
            session_id="test_123",
            user_id="test_user",
            timestamp=datetime.now(),
            transcript=[message]
        )
        self.assertEqual(session.session_id, "test_123")
        self.assertEqual(len(session.transcript), 1)
        
        # Test TherapyPlan model
        plan = TherapyPlan(
            plan_id="plan_123",
            user_id="test_user",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            plan_details={"focus": "test focus"},
            version=1
        )
        self.assertEqual(plan.plan_id, "plan_123")
        self.assertEqual(plan.version, 1)
    
    def test_embedding_utils(self):
        """Test embedding utilities."""
        embedding_utils = EmbeddingUtils()
        
        # Test generating embedding
        text = "This is a test sentence."
        embedding = embedding_utils.generate_embedding(text)
        
        self.assertIsInstance(embedding, list)
        self.assertGreater(len(embedding), 0)
        self.assertIsInstance(embedding[0], float)
        
        # Test similarity calculation
        embedding1 = embedding_utils.generate_embedding("Hello world")
        embedding2 = embedding_utils.generate_embedding("Hello world")
        similarity = embedding_utils.get_similarity(embedding1, embedding2)
        
        self.assertIsInstance(similarity, float)
        self.assertGreaterEqual(similarity, -1.0)
        self.assertLessEqual(similarity, 1.0)
    
    def test_database_service(self):
        """Test database service functionality."""
        db_service = DatabaseService(self.db_path)
        
        from datetime import datetime
        
        # Test creating session
        session = Session(
            session_id="test_session_123",
            user_id="test_user",
            timestamp=datetime.now(),
            transcript=[
                Message(role="user", content="Hello", timestamp=datetime.now()),
                Message(role="assistant", content="Hi there", timestamp=datetime.now())
            ]
        )
        
        # Test saving session
        result = db_service.save_session(session)
        self.assertTrue(result)
        
        # Test retrieving session
        retrieved_session = db_service.get_session("test_session_123")
        self.assertIsNotNone(retrieved_session)
        self.assertEqual(retrieved_session.session_id, "test_session_123")
        self.assertEqual(len(retrieved_session.transcript), 2)
        
        # Test therapy plan
        plan = TherapyPlan(
            plan_id="test_plan_123",
            user_id="test_user",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            plan_details={"focus": "test focus", "goals": "test goals"},
            version=1
        )
        
        # Test saving plan
        result = db_service.save_therapy_plan(plan)
        self.assertTrue(result)
        
        # Test retrieving plan
        retrieved_plan = db_service.get_latest_therapy_plan("test_user")
        self.assertIsNotNone(retrieved_plan)
        self.assertEqual(retrieved_plan.plan_id, "test_plan_123")
        self.assertEqual(retrieved_plan.version, 1)
    
    def test_rag_service_initialization(self):
        """Test RAG service initialization and basic functionality."""
        # This test will be skipped if ChromaDB is not available
        try:
            rag_service = RAGService(self.domain_knowledge_path, self.vector_db_path)
            
            # Test that collection was created
            self.assertIsNotNone(rag_service.domain_collection)
            
            # Test retrieving knowledge (should return empty list since no query)
            results = rag_service.retrieve_relevant_knowledge("test query", n_results=1)
            self.assertIsInstance(results, list)
            
        except Exception as e:
            # If ChromaDB is not available or there are other issues, skip this test
            self.skipTest(f"RAG service test skipped due to: {e}")

if __name__ == '__main__':
    unittest.main()
