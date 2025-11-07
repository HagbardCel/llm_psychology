import pytest
import sqlite3
import json
from datetime import datetime
from services.db_service import DatabaseService, UserStatus
from models.data_models import Session, Message, TherapyPlan, UserProfile, Topic

class TestDatabaseService:
    """Unit tests for DatabaseService."""
    
    def test_initialize_database(self, temp_db_path):
        """Test that database tables are created correctly."""
        db = DatabaseService(temp_db_path)
        
        # Check that tables exist
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        
        # Check sessions table
        cursor.execute("PRAGMA table_info(sessions)")
        session_columns = [column[1] for column in cursor.fetchall()]
        assert "session_id" in session_columns
        assert "user_id" in session_columns
        assert "timestamp" in session_columns
        assert "transcript" in session_columns
        assert "topics" in session_columns
        
        # Check therapy_plans table
        cursor.execute("PRAGMA table_info(therapy_plans)")
        plan_columns = [column[1] for column in cursor.fetchall()]
        assert "plan_id" in plan_columns
        assert "user_id" in plan_columns
        assert "created_at" in plan_columns
        assert "updated_at" in plan_columns
        assert "plan_details" in plan_columns
        assert "version" in plan_columns
        assert "selected_therapy_style" in plan_columns
        
        # Check user_profiles table
        cursor.execute("PRAGMA table_info(user_profiles)")
        profile_columns = [column[1] for column in cursor.fetchall()]
        assert "user_id" in profile_columns
        assert "name" in profile_columns
        assert "birthdate" in profile_columns
        assert "profession" in profile_columns
        assert "created_at" in profile_columns
        assert "updated_at" in profile_columns
        
        conn.close()
    
    def test_save_and_get_user_profile(self, db_service, sample_user_profile):
        """Test saving and retrieving a user profile."""
        # Save profile
        result = db_service.save_user_profile(sample_user_profile)
        assert result is True
        
        # Retrieve profile
        retrieved_profile = db_service.get_user_profile(sample_user_profile.user_id)
        assert retrieved_profile is not None
        assert retrieved_profile.user_id == sample_user_profile.user_id
        assert retrieved_profile.name == sample_user_profile.name
        assert retrieved_profile.birthdate == sample_user_profile.birthdate
        assert retrieved_profile.profession == sample_user_profile.profession
    
    def test_get_nonexistent_user_profile(self, db_service):
        """Test retrieving a non-existent user profile."""
        profile = db_service.get_user_profile("nonexistent_user")
        assert profile is None
    
    def test_save_and_get_session(self, db_service, sample_session):
        """Test saving and retrieving a session."""
        # Save session
        result = db_service.save_session(sample_session)
        assert result is True
        
        # Retrieve session
        retrieved_session = db_service.get_session(sample_session.session_id)
        assert retrieved_session is not None
        assert retrieved_session.session_id == sample_session.session_id
        assert retrieved_session.user_id == sample_session.user_id
        assert len(retrieved_session.transcript) == len(sample_session.transcript)
        
        # Check transcript content
        for i, msg in enumerate(retrieved_session.transcript):
            assert msg.role == sample_session.transcript[i].role
            assert msg.content == sample_session.transcript[i].content
    
    def test_get_nonexistent_session(self, db_service):
        """Test retrieving a non-existent session."""
        session = db_service.get_session("nonexistent_session")
        assert session is None
    
    def test_save_and_get_therapy_plan(self, db_service, sample_therapy_plan):
        """Test saving and retrieving a therapy plan."""
        # Save therapy plan
        result = db_service.save_therapy_plan(sample_therapy_plan)
        assert result is True
        
        # Retrieve therapy plan
        retrieved_plan = db_service.get_latest_therapy_plan(sample_therapy_plan.user_id)
        assert retrieved_plan is not None
        assert retrieved_plan.plan_id == sample_therapy_plan.plan_id
        assert retrieved_plan.user_id == sample_therapy_plan.user_id
        assert retrieved_plan.version == sample_therapy_plan.version
        assert retrieved_plan.selected_therapy_style == sample_therapy_plan.selected_therapy_style
        assert retrieved_plan.plan_details == sample_therapy_plan.plan_details
    
    def test_get_nonexistent_therapy_plan(self, db_service):
        """Test retrieving a non-existent therapy plan."""
        plan = db_service.get_latest_therapy_plan("nonexistent_user")
        assert plan is None
    
    def test_get_all_sessions_for_user(self, db_service, sample_session):
        """Test retrieving all sessions for a user."""
        # Save multiple sessions
        session1 = sample_session
        session2 = Session(
            session_id="test_session_456",
            user_id=sample_session.user_id,
            timestamp="2024-01-02T00:00:00",
            transcript=[
                Message(role="user", content="Hello again", timestamp="2024-01-02T00:00:00"),
                Message(role="assistant", content="Hello! Good to see you again.", timestamp="2024-01-02T00:00:01")
            ]
        )
        
        db_service.save_session(session1)
        db_service.save_session(session2)
        
        # Retrieve all sessions
        sessions = db_service.get_all_sessions_for_user(sample_session.user_id)
        assert len(sessions) == 2
        
        # Sessions should be ordered by timestamp
        assert sessions[0].session_id == session1.session_id
        assert sessions[1].session_id == session2.session_id
    
    def test_clear_all_data(self, db_service, sample_user_profile, sample_session, sample_therapy_plan):
        """Test clearing all data from the database."""
        # Save some data
        db_service.save_user_profile(sample_user_profile)
        db_service.save_session(sample_session)
        db_service.save_therapy_plan(sample_therapy_plan)
        
        # Verify data exists
        assert db_service.get_user_profile(sample_user_profile.user_id) is not None
        assert db_service.get_session(sample_session.session_id) is not None
        assert db_service.get_latest_therapy_plan(sample_therapy_plan.user_id) is not None
        
        # Clear all data
        result = db_service.clear_all_data()
        assert result is True
        
        # Verify data is cleared
        assert db_service.get_user_profile(sample_user_profile.user_id) is None
        assert db_service.get_session(sample_session.session_id) is None
        assert db_service.get_latest_therapy_plan(sample_therapy_plan.user_id) is None
    
    def test_get_user_status_no_data(self, db_service):
        """Test user status when no data exists."""
        status = db_service.get_user_status("test_user")
        assert status == UserStatus.NO_DATA
    
    def test_get_user_status_profile_only(self, db_service, sample_user_profile):
        """Test user status when only profile exists."""
        db_service.save_user_profile(sample_user_profile)
        status = db_service.get_user_status(sample_user_profile.user_id)
        assert status == UserStatus.PROFILE_ONLY
    
    def test_get_user_status_intake_complete(self, db_service, sample_user_profile, sample_session):
        """Test user status when sessions exist but no plan."""
        db_service.save_user_profile(sample_user_profile)
        db_service.save_session(sample_session)
        status = db_service.get_user_status(sample_user_profile.user_id)
        assert status == UserStatus.INTAKE_COMPLETE
    
    def test_get_user_status_plan_complete(self, db_service, sample_user_profile, sample_session, sample_therapy_plan):
        """Test user status when therapy plan exists."""
        db_service.save_user_profile(sample_user_profile)
        db_service.save_session(sample_session)
        db_service.save_therapy_plan(sample_therapy_plan)
        status = db_service.get_user_status(sample_user_profile.user_id)
        assert status == UserStatus.PLAN_COMPLETE
    
    def test_save_session_with_topics(self, db_service):
        """Test saving and retrieving a session with topics."""
        session_with_topics = Session(
            session_id="test_session_topics",
            user_id="test_user_123",
            timestamp="2024-01-01T00:00:00",
            transcript=[
                Message(role="user", content="I want to discuss work stress", timestamp="2024-01-01T00:00:00")
            ],
            topics=[
                Topic(name="work_stress", status="active"),
                Topic(name="anxiety", status="pending")
            ]
        )
        
        # Save session
        result = db_service.save_session(session_with_topics)
        assert result is True
        
        # Retrieve session
        retrieved_session = db_service.get_session(session_with_topics.session_id)
        assert retrieved_session is not None
        assert len(retrieved_session.topics) == 2
        assert retrieved_session.topics[0].name == "work_stress"
        assert retrieved_session.topics[0].status == "active"
        assert retrieved_session.topics[1].name == "anxiety"
        assert retrieved_session.topics[1].status == "pending"
