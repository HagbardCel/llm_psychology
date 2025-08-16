"""
MemoryAgent: Specialized agent for managing session context and therapeutic memory.

This agent is responsible for:
- Retrieving and organizing session history
- Maintaining context across therapy sessions
- Providing session-based insights and patterns
- Managing therapeutic relationship continuity
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict

from services.llm_service import LLMService
from services.db_service import DatabaseService
from services.rag_service import RAGService
from context.user_context import UserContext
from models.data_models import Session, Message, Topic
from exceptions import MemoryError

logger = logging.getLogger(__name__)


class SessionContext:
    """Structured context from session analysis."""
    
    def __init__(self, session_id: str, key_themes: List[str], 
                 emotional_state: str, insights: List[str], 
                 progress_indicators: List[str]):
        self.session_id = session_id
        self.key_themes = key_themes
        self.emotional_state = emotional_state
        self.insights = insights
        self.progress_indicators = progress_indicators
        self.timestamp = datetime.now()


class TherapeuticMemory:
    """Aggregated memory across multiple sessions."""
    
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.session_contexts: List[SessionContext] = []
        self.recurring_themes: Dict[str, int] = defaultdict(int)
        self.emotional_patterns: List[str] = []
        self.progress_timeline: List[Dict[str, Any]] = []
        self.relationship_quality: str = "building"
        
    def add_session_context(self, context: SessionContext) -> None:
        """Add new session context to memory."""
        self.session_contexts.append(context)
        
        # Update recurring themes
        for theme in context.key_themes:
            self.recurring_themes[theme] += 1
        
        # Update emotional patterns
        if context.emotional_state:
            self.emotional_patterns.append(context.emotional_state)
        
        # Update progress timeline
        self.progress_timeline.append({
            'session_id': context.session_id,
            'timestamp': context.timestamp.isoformat(),
            'indicators': context.progress_indicators
        })


class MemoryAgent:
    """
    Agent specialized in managing therapeutic memory and session context.
    
    This agent maintains continuity across therapy sessions by:
    - Analyzing session content for key themes and patterns
    - Tracking emotional states and progress over time
    - Providing contextual insights for therapy planning
    - Managing therapeutic relationship development
    """
    
    def __init__(self, llm_service: LLMService, db_service: DatabaseService, 
                 rag_service: RAGService, user_context: UserContext):
        """
        Initialize the Memory Agent.
        
        Args:
            llm_service: LLM service for content analysis
            db_service: Database service for session retrieval
            rag_service: RAG service for domain knowledge
            user_context: User context for this memory session
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
        
        # Cache for therapeutic memory
        self._memory_cache: Optional[TherapeuticMemory] = None
        self._cache_timestamp: Optional[datetime] = None
        
        logger.info(f"MemoryAgent initialized for user {user_context.user_id}")
    
    def analyze_session_context(self, session: Session) -> SessionContext:
        """
        Analyze a session to extract key contextual information.
        
        Args:
            session: The session to analyze
            
        Returns:
            SessionContext: Structured context from the session
            
        Raises:
            MemoryError: If session analysis fails
        """
        logger.debug(f"Analyzing session context for {session.session_id}")
        
        try:
            # Prepare session transcript
            session_text = "\n".join([
                f"{msg.role}: {msg.content}" 
                for msg in session.transcript
            ])
            
            # Get relevant psychological knowledge for context
            relevant_knowledge = self.rag_service.retrieve_relevant_knowledge(
                session_text, n_results=2
            )
            
            # Create analysis prompt
            analysis_prompt = f"""
            Analyze this therapy session transcript and extract key contextual information:

            Session Transcript:
            {session_text}

            Relevant Knowledge Context:
            {self._format_knowledge(relevant_knowledge)}

            Please provide a structured analysis including:
            1. Key themes discussed (3-5 main topics)
            2. Client's emotional state (one primary emotion)
            3. Important insights or breakthroughs
            4. Progress indicators (positive changes or developments)

            Respond in JSON format:
            {{
                "key_themes": ["theme1", "theme2", "theme3"],
                "emotional_state": "primary_emotion",
                "insights": ["insight1", "insight2"],
                "progress_indicators": ["indicator1", "indicator2"]
            }}
            """
            
            # Get structured response from LLM
            response = self.llm_service.generate_structured_response(
                analysis_prompt,
                '{"key_themes": ["string"], "emotional_state": "string", "insights": ["string"], "progress_indicators": ["string"]}'
            )
            
            # Parse response
            analysis = self._parse_session_analysis(response)
            
            # Create session context
            context = SessionContext(
                session_id=session.session_id,
                key_themes=analysis.get('key_themes', []),
                emotional_state=analysis.get('emotional_state', 'neutral'),
                insights=analysis.get('insights', []),
                progress_indicators=analysis.get('progress_indicators', [])
            )
            
            logger.info(f"Session context analyzed for {session.session_id}")
            return context
            
        except Exception as e:
            logger.error(f"Failed to analyze session context: {e}", exc_info=True)
            raise MemoryError(f"Session context analysis failed: {e}")
    
    def get_therapeutic_memory(self, refresh: bool = False) -> TherapeuticMemory:
        """
        Get comprehensive therapeutic memory for the user.
        
        Args:
            refresh: Whether to refresh the cache
            
        Returns:
            TherapeuticMemory: Aggregated memory across sessions
        """
        # Check cache validity (refresh every hour or on demand)
        cache_valid = (
            self._memory_cache is not None and
            self._cache_timestamp is not None and
            not refresh and
            (datetime.now() - self._cache_timestamp) < timedelta(hours=1)
        )
        
        if cache_valid:
            logger.debug("Returning cached therapeutic memory")
            return self._memory_cache
        
        logger.debug("Building therapeutic memory from sessions")
        
        try:
            # Get all sessions for the user
            sessions = self.db_service.get_all_sessions_for_user(self.user_context.user_id)
            
            # Create therapeutic memory
            memory = TherapeuticMemory(self.user_context.user_id)
            
            # Analyze each session for context
            for session in sessions:
                try:
                    context = self.analyze_session_context(session)
                    memory.add_session_context(context)
                except Exception as e:
                    logger.warning(f"Failed to analyze session {session.session_id}: {e}")
                    continue
            
            # Analyze relationship quality based on sessions
            memory.relationship_quality = self._assess_relationship_quality(sessions)
            
            # Cache the result
            self._memory_cache = memory
            self._cache_timestamp = datetime.now()
            
            logger.info(f"Therapeutic memory built with {len(memory.session_contexts)} sessions")
            return memory
            
        except Exception as e:
            logger.error(f"Failed to build therapeutic memory: {e}", exc_info=True)
            raise MemoryError(f"Therapeutic memory building failed: {e}")
    
    def get_recent_context(self, num_sessions: int = 3) -> Dict[str, Any]:
        """
        Get context from recent sessions for immediate therapy planning.
        
        Args:
            num_sessions: Number of recent sessions to include
            
        Returns:
            Dict containing recent session context
        """
        logger.debug(f"Getting context from {num_sessions} recent sessions")
        
        try:
            # Get recent sessions
            all_sessions = self.db_service.get_all_sessions_for_user(self.user_context.user_id)
            recent_sessions = all_sessions[-num_sessions:] if all_sessions else []
            
            if not recent_sessions:
                return {
                    'sessions': [],
                    'themes': [],
                    'emotional_progression': [],
                    'insights': [],
                    'context_summary': 'No recent sessions available'
                }
            
            # Analyze recent sessions
            contexts = []
            all_themes = []
            emotional_states = []
            all_insights = []
            
            for session in recent_sessions:
                try:
                    context = self.analyze_session_context(session)
                    contexts.append({
                        'session_id': context.session_id,
                        'themes': context.key_themes,
                        'emotional_state': context.emotional_state,
                        'insights': context.insights
                    })
                    all_themes.extend(context.key_themes)
                    emotional_states.append(context.emotional_state)
                    all_insights.extend(context.insights)
                    
                except Exception as e:
                    logger.warning(f"Failed to analyze recent session {session.session_id}: {e}")
                    continue
            
            # Generate context summary
            summary = self._generate_context_summary(all_themes, emotional_states, all_insights)
            
            return {
                'sessions': contexts,
                'themes': list(set(all_themes)),  # Unique themes
                'emotional_progression': emotional_states,
                'insights': all_insights,
                'context_summary': summary
            }
            
        except Exception as e:
            logger.error(f"Failed to get recent context: {e}", exc_info=True)
            raise MemoryError(f"Recent context retrieval failed: {e}")
    
    def identify_patterns(self) -> Dict[str, Any]:
        """
        Identify patterns and trends across all sessions.
        
        Returns:
            Dict containing identified patterns
        """
        logger.debug("Identifying therapeutic patterns")
        
        try:
            memory = self.get_therapeutic_memory()
            
            # Analyze theme patterns
            theme_patterns = self._analyze_theme_patterns(memory.recurring_themes)
            
            # Analyze emotional patterns
            emotional_patterns = self._analyze_emotional_patterns(memory.emotional_patterns)
            
            # Analyze progress patterns
            progress_patterns = self._analyze_progress_patterns(memory.progress_timeline)
            
            return {
                'theme_patterns': theme_patterns,
                'emotional_patterns': emotional_patterns,
                'progress_patterns': progress_patterns,
                'relationship_quality': memory.relationship_quality,
                'total_sessions': len(memory.session_contexts)
            }
            
        except Exception as e:
            logger.error(f"Failed to identify patterns: {e}", exc_info=True)
            raise MemoryError(f"Pattern identification failed: {e}")
    
    def get_continuity_context(self, current_session_topics: List[str]) -> str:
        """
        Get context for maintaining continuity with current session.
        
        Args:
            current_session_topics: Topics being discussed in current session
            
        Returns:
            String context for therapeutic continuity
        """
        logger.debug("Getting continuity context")
        
        try:
            memory = self.get_therapeutic_memory()
            recent_context = self.get_recent_context(num_sessions=2)
            
            # Find related themes from memory
            related_themes = []
            for topic in current_session_topics:
                for theme, count in memory.recurring_themes.items():
                    if topic.lower() in theme.lower() or theme.lower() in topic.lower():
                        related_themes.append(f"{theme} (mentioned {count} times)")
            
            # Build continuity context
            context_parts = []
            
            if related_themes:
                context_parts.append(f"Related themes from previous sessions: {', '.join(related_themes)}")
            
            if recent_context['emotional_progression']:
                recent_emotions = recent_context['emotional_progression'][-2:]
                context_parts.append(f"Recent emotional states: {' → '.join(recent_emotions)}")
            
            if recent_context['insights']:
                recent_insights = recent_context['insights'][-2:]
                context_parts.append(f"Recent insights: {'; '.join(recent_insights)}")
            
            if memory.relationship_quality:
                context_parts.append(f"Therapeutic relationship: {memory.relationship_quality}")
            
            return " | ".join(context_parts) if context_parts else "Starting fresh session context"
            
        except Exception as e:
            logger.error(f"Failed to get continuity context: {e}", exc_info=True)
            return "Context unavailable due to error"
    
    def _format_knowledge(self, knowledge_list: List[Dict[str, Any]]) -> str:
        """Format knowledge list for prompts."""
        if not knowledge_list:
            return "No relevant knowledge available."
        
        formatted = []
        for i, knowledge in enumerate(knowledge_list, 1):
            formatted.append(f"{i}. From {knowledge['source']}: {knowledge['content']}")
        
        return "\n".join(formatted)
    
    def _parse_session_analysis(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse LLM response for session analysis."""
        try:
            if "raw_response" in response:
                import json
                raw_response = response["raw_response"].strip()
                
                # Remove markdown code block markers
                if raw_response.startswith("```json"):
                    raw_response = raw_response[7:]
                if raw_response.startswith("```"):
                    raw_response = raw_response[3:]
                if raw_response.endswith("```"):
                    raw_response = raw_response[:-3]
                
                return json.loads(raw_response.strip())
            
            # Fallback to default
            return {
                'key_themes': ['general_discussion'],
                'emotional_state': 'neutral',
                'insights': [],
                'progress_indicators': []
            }
            
        except Exception as e:
            logger.warning(f"Failed to parse session analysis: {e}")
            return {
                'key_themes': ['general_discussion'],
                'emotional_state': 'neutral', 
                'insights': [],
                'progress_indicators': []
            }
    
    def _assess_relationship_quality(self, sessions: List[Session]) -> str:
        """Assess therapeutic relationship quality based on sessions."""
        if not sessions:
            return "new"
        
        session_count = len(sessions)
        
        if session_count == 1:
            return "building"
        elif session_count <= 3:
            return "developing"
        elif session_count <= 6:
            return "established"
        else:
            return "strong"
    
    def _analyze_theme_patterns(self, themes: Dict[str, int]) -> Dict[str, Any]:
        """Analyze patterns in recurring themes."""
        if not themes:
            return {'dominant_themes': [], 'emerging_themes': [], 'stable_themes': []}
        
        # Sort themes by frequency
        sorted_themes = sorted(themes.items(), key=lambda x: x[1], reverse=True)
        
        total_mentions = sum(themes.values())
        
        return {
            'dominant_themes': [theme for theme, count in sorted_themes[:3]],
            'theme_frequency': dict(sorted_themes),
            'total_theme_mentions': total_mentions
        }
    
    def _analyze_emotional_patterns(self, emotions: List[str]) -> Dict[str, Any]:
        """Analyze patterns in emotional states."""
        if not emotions:
            return {'progression': [], 'common_states': [], 'recent_trend': 'stable'}
        
        # Count emotional states
        emotion_counts = defaultdict(int)
        for emotion in emotions:
            emotion_counts[emotion] += 1
        
        # Analyze recent trend (last 3 emotions)
        recent_emotions = emotions[-3:] if len(emotions) >= 3 else emotions
        recent_trend = "improving" if any(pos in recent_emotions for pos in ['happy', 'hopeful', 'confident']) else "stable"
        
        return {
            'progression': emotions,
            'common_states': list(emotion_counts.keys()),
            'recent_trend': recent_trend,
            'emotion_distribution': dict(emotion_counts)
        }
    
    def _analyze_progress_patterns(self, timeline: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze patterns in progress indicators."""
        if not timeline:
            return {'total_indicators': 0, 'recent_progress': [], 'progress_trend': 'stable'}
        
        all_indicators = []
        for entry in timeline:
            all_indicators.extend(entry.get('indicators', []))
        
        recent_indicators = []
        for entry in timeline[-2:]:  # Last 2 sessions
            recent_indicators.extend(entry.get('indicators', []))
        
        return {
            'total_indicators': len(all_indicators),
            'recent_progress': recent_indicators,
            'progress_trend': 'improving' if recent_indicators else 'stable'
        }
    
    def _generate_context_summary(self, themes: List[str], emotions: List[str], insights: List[str]) -> str:
        """Generate a summary of recent context."""
        summary_parts = []
        
        if themes:
            unique_themes = list(set(themes))
            summary_parts.append(f"Recent themes: {', '.join(unique_themes[:3])}")
        
        if emotions:
            recent_emotion = emotions[-1] if emotions else "neutral"
            summary_parts.append(f"Current emotional state: {recent_emotion}")
        
        if insights:
            summary_parts.append(f"Recent insights: {len(insights)} new insights gained")
        
        return " | ".join(summary_parts) if summary_parts else "Limited recent context available"
    
    def health_check(self) -> bool:
        """
        Perform health check on the memory agent.
        
        Returns:
            bool: True if healthy, False otherwise
        """
        try:
            # Test database connectivity
            sessions = self.db_service.get_all_sessions_for_user(self.user_context.user_id)
            
            # Test LLM service if sessions exist
            if sessions:
                test_prompt = "Respond with 'OK' if you can process this request."
                response = self.llm_service.generate_response(test_prompt)
                return 'OK' in response or 'ok' in response.lower()
            
            return True
            
        except Exception as e:
            logger.error(f"MemoryAgent health check failed: {e}")
            return False
    
    def __str__(self) -> str:
        """String representation of memory agent."""
        return f"MemoryAgent(user={self.user_context.user_id})"
    
    def __repr__(self) -> str:
        """Detailed representation of memory agent."""
        cache_status = "cached" if self._memory_cache else "not_cached"
        return f"MemoryAgent(user='{self.user_context.user_id}', cache={cache_status})"