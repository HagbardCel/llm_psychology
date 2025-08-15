import sqlite3
import json
import uuid
import logging
from typing import Optional, List
from datetime import datetime
from models.data_models import Session, Message, TherapyPlan, UserProfile, Topic
from exceptions import DatabaseError, SessionNotFoundError, TherapyPlanCreationError

logger = logging.getLogger(__name__)

class UserStatus:
    """Represents the user's current status in the therapy process."""
    NO_DATA = "no_data"
    PROFILE_ONLY = "profile_only"
    INTAKE_COMPLETE = "intake_complete"
    PLAN_COMPLETE = "plan_complete"

class DatabaseService:
    """Service for handling all SQLite database operations."""
    
    def __init__(self, db_path: str):
        """
        Initialize the database service.
        
        Args:
            db_path (str): Path to the SQLite database file.
        """
        self.db_path = db_path
        self._initialize_database()
    
    def _initialize_database(self):
        """Create the necessary tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                transcript TEXT NOT NULL
            )
        ''')
        
        # Create therapy_plans table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS therapy_plans (
                plan_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                plan_details TEXT NOT NULL,
                version INTEGER NOT NULL
            )
        ''')
        
        # Add selected_therapy_style column if it doesn't exist
        try:
            cursor.execute("ALTER TABLE therapy_plans ADD COLUMN selected_therapy_style TEXT")
        except sqlite3.OperationalError:
            # Column already exists
            pass
        
        # Create user_profiles table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                birthdate TEXT,
                profession TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        
        # Add topics column to sessions table if it doesn't exist
        try:
            cursor.execute("ALTER TABLE sessions ADD COLUMN topics TEXT")
        except sqlite3.OperationalError:
            # Column already exists
            pass
        
        conn.commit()
        conn.close()
    
    def _datetime_to_iso(self, dt: datetime) -> str:
        """Convert datetime to ISO format string."""
        return dt.isoformat()
    
    def _iso_to_datetime(self, iso_str: str) -> datetime:
        """Convert ISO format string to datetime."""
        return datetime.fromisoformat(iso_str)
    
    def save_session(self, session: Session) -> bool:
        """
        Save a session to the database.
        
        Args:
            session (Session): The session to save.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Convert transcript to JSON string with proper datetime serialization
            transcript_data = []
            for msg in session.transcript:
                transcript_data.append({
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": self._datetime_to_iso(msg.timestamp)
                })
            
            transcript_json = json.dumps(transcript_data)
            
            # Convert topics to JSON string
            topics_data = []
            for topic in session.topics:
                topics_data.append({
                    "name": topic.name,
                    "status": topic.status
                })
            
            topics_json = json.dumps(topics_data)
            
            # Add topics column if it doesn't exist
            try:
                cursor.execute("ALTER TABLE sessions ADD COLUMN topics TEXT")
            except sqlite3.OperationalError:
                # Column already exists
                pass
            
            cursor.execute('''
                INSERT INTO sessions (session_id, user_id, timestamp, transcript, topics)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                session.session_id, 
                session.user_id, 
                self._datetime_to_iso(session.timestamp), 
                transcript_json,
                topics_json
            ))
            
            conn.commit()
            conn.close()
            logger.info(f"Session {session.session_id} saved successfully")
            return True
        except Exception as e:
            logger.error(f"Error saving session {session.session_id}: {e}")
            return False
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """
        Retrieve a session from the database.
        
        Args:
            session_id (str): The ID of the session to retrieve.
            
        Returns:
            Optional[Session]: The session if found, None otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Try to get topics column, fall back to old schema if it doesn't exist
            try:
                cursor.execute('''
                    SELECT session_id, user_id, timestamp, transcript, topics
                    FROM sessions
                    WHERE session_id = ?
                ''', (session_id,))
            except sqlite3.OperationalError:
                # Old schema without topics column
                cursor.execute('''
                    SELECT session_id, user_id, timestamp, transcript
                    FROM sessions
                    WHERE session_id = ?
                ''', (session_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                # Parse transcript JSON
                transcript_data = json.loads(row[3])
                transcript = []
                for msg_data in transcript_data:
                    transcript.append(Message(
                        role=msg_data["role"],
                        content=msg_data["content"],
                        timestamp=self._iso_to_datetime(msg_data["timestamp"])
                    ))
                
                # Parse topics JSON if available
                topics = []
                if len(row) > 4 and row[4]:  # topics column exists and has data
                    try:
                        topics_data = json.loads(row[4])
                        topics = [Topic(name=topic_data["name"], status=topic_data["status"]) 
                                 for topic_data in topics_data]
                    except (json.JSONDecodeError, KeyError):
                        # Handle malformed topics data
                        topics = []
                
                return Session(
                    session_id=row[0],
                    user_id=row[1],
                    timestamp=self._iso_to_datetime(row[2]),
                    transcript=transcript,
                    topics=topics
                )
            return None
        except Exception as e:
            logger.error(f"Error retrieving session: {e}", exc_info=True)
            return None
    
    def save_therapy_plan(self, plan: TherapyPlan) -> bool:
        """
        Save a therapy plan to the database.
        
        Args:
            plan (TherapyPlan): The therapy plan to save.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Convert plan_details to JSON string
            plan_details_json = json.dumps(plan.plan_details)
            
            cursor.execute('''
                INSERT INTO therapy_plans (plan_id, user_id, created_at, updated_at, plan_details, version, selected_therapy_style)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                plan.plan_id,
                plan.user_id,
                self._datetime_to_iso(plan.created_at),
                self._datetime_to_iso(plan.updated_at),
                plan_details_json,
                plan.version,
                plan.selected_therapy_style
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error saving therapy plan: {e}", exc_info=True)
            return False
    
    def get_latest_therapy_plan(self, user_id: str = "default_user") -> Optional[TherapyPlan]:
        """
        Retrieve the latest therapy plan for a user.
        
        Args:
            user_id (str): The ID of the user.
            
        Returns:
            Optional[TherapyPlan]: The latest therapy plan if found, None otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT plan_id, user_id, created_at, updated_at, plan_details, version, selected_therapy_style
                FROM therapy_plans
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
            ''', (user_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                plan_details_data = json.loads(row[4])
                
                return TherapyPlan(
                    plan_id=row[0],
                    user_id=row[1],
                    created_at=self._iso_to_datetime(row[2]),
                    updated_at=self._iso_to_datetime(row[3]),
                    plan_details=plan_details_data,
                    version=row[5],
                    selected_therapy_style=row[6]
                )
            return None
        except Exception as e:
            logger.error(f"Error retrieving therapy plan: {e}", exc_info=True)
            return None
    
    def get_all_sessions_for_user(self, user_id: str = "default_user") -> List[Session]:
        """
        Retrieve all sessions for a user.
        
        Args:
            user_id (str): The ID of the user.
            
        Returns:
            List[Session]: List of all sessions for the user.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Try to get topics column, fall back to old schema if it doesn't exist
            try:
                cursor.execute('''
                    SELECT session_id, user_id, timestamp, transcript, topics
                    FROM sessions
                    WHERE user_id = ?
                    ORDER BY timestamp ASC
                ''', (user_id,))
            except sqlite3.OperationalError:
                # Old schema without topics column
                cursor.execute('''
                    SELECT session_id, user_id, timestamp, transcript
                    FROM sessions
                    WHERE user_id = ?
                    ORDER BY timestamp ASC
                ''', (user_id,))
            
            rows = cursor.fetchall()
            conn.close()
            
            sessions = []
            for row in rows:
                # Parse transcript JSON
                transcript_data = json.loads(row[3])
                transcript = []
                for msg_data in transcript_data:
                    transcript.append(Message(
                        role=msg_data["role"],
                        content=msg_data["content"],
                        timestamp=self._iso_to_datetime(msg_data["timestamp"])
                    ))
                
                # Parse topics JSON if available
                topics = []
                if len(row) > 4 and row[4]:  # topics column exists and has data
                    try:
                        topics_data = json.loads(row[4])
                        topics = [Topic(name=topic_data["name"], status=topic_data["status"]) 
                                 for topic_data in topics_data]
                    except (json.JSONDecodeError, KeyError):
                        # Handle malformed topics data
                        topics = []
                
                sessions.append(Session(
                    session_id=row[0],
                    user_id=row[1],
                    timestamp=self._iso_to_datetime(row[2]),
                    transcript=transcript,
                    topics=topics
                ))
            
            return sessions
        except Exception as e:
            logger.error(f"Error retrieving sessions: {e}", exc_info=True)
            return []
    
    def save_user_profile(self, profile: UserProfile) -> bool:
        """
        Save a user profile to the database.
        
        Args:
            profile (UserProfile): The user profile to save.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO user_profiles 
                (user_id, name, birthdate, profession, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                profile.user_id,
                profile.name,
                self._datetime_to_iso(profile.birthdate) if profile.birthdate else None,
                profile.profession,
                self._datetime_to_iso(profile.created_at),
                self._datetime_to_iso(profile.updated_at)
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error saving user profile: {e}", exc_info=True)
            return False
    
    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """
        Retrieve a user profile from the database.
        
        Args:
            user_id (str): The ID of the user.
            
        Returns:
            Optional[UserProfile]: The user profile if found, None otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT user_id, name, birthdate, profession, created_at, updated_at
                FROM user_profiles
                WHERE user_id = ?
            ''', (user_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return UserProfile(
                    user_id=row[0],
                    name=row[1],
                    birthdate=self._iso_to_datetime(row[2]) if row[2] else None,
                    profession=row[3],
                    created_at=self._iso_to_datetime(row[4]),
                    updated_at=self._iso_to_datetime(row[5])
                )
            return None
        except Exception as e:
            logger.error(f"Error retrieving user profile: {e}", exc_info=True)
            return None
    
    def clear_all_data(self) -> bool:
        """
        Clear all data from all tables in the database.
        
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Clear all tables
            cursor.execute("DELETE FROM sessions")
            cursor.execute("DELETE FROM therapy_plans")
            cursor.execute("DELETE FROM user_profiles")
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error clearing database: {e}", exc_info=True)
            return False
    
    def get_user_status(self, user_id: str = "default_user") -> str:
        """
        Determine the user's current status in the therapy process.
        
        Args:
            user_id (str): The ID of the user.
            
        Returns:
            str: The user's status (NO_DATA, PROFILE_ONLY, INTAKE_COMPLETE, PLAN_COMPLETE).
        """
        # Check if user profile exists
        user_profile = self.get_user_profile(user_id)
        if not user_profile:
            return UserStatus.NO_DATA
        
        # Check if any sessions exist (indicating intake completion)
        sessions = self.get_all_sessions_for_user(user_id)
        if not sessions:
            return UserStatus.PROFILE_ONLY
        
        # Check if therapy plan exists
        therapy_plan = self.get_latest_therapy_plan(user_id)
        if not therapy_plan:
            return UserStatus.INTAKE_COMPLETE
        
        return UserStatus.PLAN_COMPLETE
