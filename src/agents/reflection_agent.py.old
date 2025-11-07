from datetime import datetime
import logging
from typing import Dict, Any, Optional, List

from services.llm_service import LLMService
from services.db_service import DatabaseService
from services.rag_service import RAGService
from models.data_models import Session, TherapyPlan
from context.user_context import UserContext
from agents.memory_agent import MemoryAgent
from agents.planning_agent import PlanningAgent
from prompts.reflection_prompts import SESSION_SUMMARY_PROMPT
from exceptions import ReflectionError

logger = logging.getLogger(__name__)


class ReflectionAgent:
    """
    Coordination agent for therapeutic reflection and planning.
    
    This agent coordinates memory and planning functionality to provide
    comprehensive therapy session analysis and plan management. It serves
    as the orchestrator between specialized agents rather than duplicating
    their functionality.
    """
    
    def __init__(self, llm_service: LLMService, db_service: DatabaseService, 
                 rag_service: RAGService, user_context: UserContext,
                 memory_agent: MemoryAgent, planning_agent: PlanningAgent):
        """
        Initialize the Reflection Agent.
        
        Args:
            llm_service: The LLM service for generating responses
            db_service: The database service for storing plans
            rag_service: The RAG service for retrieving domain knowledge
            user_context: User context for this reflection session
            memory_agent: Memory agent for session context analysis
            planning_agent: Planning agent for therapy plan management
        """
        self.llm_service = llm_service
        self.db_service = db_service
        self.rag_service = rag_service
        self.user_context = user_context
        self.memory_agent = memory_agent
        self.planning_agent = planning_agent
        
        logger.info(f"ReflectionAgent initialized for user {user_context.user_id}")
    
    def create_initial_plan(self, intake_session: Session, 
                          selected_style: Optional[str] = None) -> TherapyPlan:
        """
        Coordinate initial therapy plan creation using specialized agents.
        
        Args:
            intake_session: The completed intake session
            selected_style: Optional therapy style preference
            
        Returns:
            TherapyPlan: The initial therapy plan
            
        Raises:
            ReflectionError: If plan creation fails
        """
        logger.info(f"ReflectionAgent: Coordinating initial plan creation for user {self.user_context.user_id}")
        
        try:
            # Use planning agent to create comprehensive initial plan
            therapy_plan = self.planning_agent.create_initial_plan(
                intake_session, selected_style
            )
            
            logger.info(f"Initial therapy plan created with ID: {therapy_plan.plan_id}")
            return therapy_plan
            
        except Exception as e:
            logger.error(f"Failed to coordinate initial plan creation: {e}", exc_info=True)
            raise ReflectionError(f"Initial plan creation failed: {e}")
    
    def create_initial_plan_with_style(self, intake_session: Session, selected_style: str) -> TherapyPlan:
        """
        Create initial therapy plan with specific style (delegates to create_initial_plan).
        
        Args:
            intake_session: The completed intake session
            selected_style: The selected therapy style
            
        Returns:
            TherapyPlan: The initial therapy plan with selected style
        """
        logger.info(f"ReflectionAgent: Creating initial {selected_style.upper()} therapy plan")
        return self.create_initial_plan(intake_session, selected_style)
    
    def update_plan(self, session: Session, current_plan: Optional[TherapyPlan] = None) -> TherapyPlan:
        """
        Coordinate therapy plan updates using specialized agents.
        
        Args:
            session: The completed therapy session
            current_plan: The current therapy plan (if None, retrieves latest)
            
        Returns:
            TherapyPlan: The updated therapy plan
            
        Raises:
            ReflectionError: If plan update fails
        """
        logger.info(f"ReflectionAgent: Coordinating plan update for user {self.user_context.user_id}")
        
        try:
            # Get current plan if not provided
            if current_plan is None:
                current_plan = self.db_service.get_latest_therapy_plan(self.user_context.user_id)
                
                if current_plan is None:
                    logger.warning("No existing plan found. Creating initial plan based on session.")
                    return self.planning_agent.create_initial_plan(session)
            
            # Use planning agent to update plan
            updated_plan = self.planning_agent.update_plan(session, current_plan)
            
            logger.info(f"Therapy plan updated to version {updated_plan.version}")
            return updated_plan
            
        except Exception as e:
            logger.error(f"Failed to coordinate plan update: {e}", exc_info=True)
            raise ReflectionError(f"Plan update failed: {e}")
    
    def generate_comprehensive_reflection(self, session: Session, 
                                        current_plan: Optional[TherapyPlan] = None) -> Dict[str, Any]:
        """
        Generate comprehensive reflection combining memory analysis and planning insights.
        
        Args:
            session: The session to reflect on
            current_plan: Optional current therapy plan
            
        Returns:
            Dict containing comprehensive reflection analysis
            
        Raises:
            ReflectionError: If reflection generation fails
        """
        logger.info(f"ReflectionAgent: Generating comprehensive reflection for session {session.session_id}")
        
        try:
            # Analyze session context using memory agent
            session_context = self.memory_agent.analyze_session_context(session)
            
            # Get therapeutic memory and patterns
            memory = self.memory_agent.get_therapeutic_memory()
            patterns = self.memory_agent.identify_patterns()
            
            # Get continuity context
            continuity_context = self.memory_agent.get_continuity_context(
                [topic.name for topic in session.topics]
            )
            
            # Assess plan effectiveness if plan exists
            plan_assessment = None
            plan_recommendations = []
            
            if current_plan:
                plan_assessment = self.planning_agent.assess_plan_effectiveness(current_plan)
                plan_recommendations = self.planning_agent.recommend_plan_adjustments(current_plan)
            
            # Generate traditional session summary
            session_summary = self._generate_session_summary(session)
            
            # Compile comprehensive reflection
            reflection = {
                "session_id": session.session_id,
                "timestamp": session.timestamp.isoformat(),
                "user_id": self.user_context.user_id,
                
                # Memory analysis
                "session_context": {
                    "key_themes": session_context.key_themes,
                    "emotional_state": session_context.emotional_state,
                    "insights": session_context.insights,
                    "progress_indicators": session_context.progress_indicators
                },
                
                "therapeutic_memory": {
                    "total_sessions": len(memory.session_contexts),
                    "relationship_quality": memory.relationship_quality,
                    "dominant_themes": list(memory.recurring_themes.keys())[:5],
                    "emotional_progression": memory.emotional_patterns[-5:] if memory.emotional_patterns else []
                },
                
                "patterns": patterns,
                "continuity_context": continuity_context,
                
                # Planning analysis
                "plan_assessment": plan_assessment,
                "plan_recommendations": plan_recommendations,
                
                # Traditional summary
                "session_summary": session_summary,
                
                # Metadata
                "reflection_generated_at": datetime.now().isoformat(),
                "agents_used": ["MemoryAgent", "PlanningAgent", "ReflectionAgent"]
            }
            
            logger.info(f"Comprehensive reflection generated for session {session.session_id}")
            return reflection
            
        except Exception as e:
            logger.error(f"Failed to generate comprehensive reflection: {e}", exc_info=True)
            raise ReflectionError(f"Reflection generation failed: {e}")
    
    def _generate_session_summary(self, session: Session) -> str:
        """
        Generate traditional session summary using LLM.
        
        Args:
            session: The session to summarize
            
        Returns:
            String summary of the session
        """
        session_text = "\n".join([f"{msg.role}: {msg.content}" for msg in session.transcript])
        summary_prompt = SESSION_SUMMARY_PROMPT.format(session_text=session_text)
        return self.llm_service.generate_response(summary_prompt)
    
    def generate_session_summary(self, session: Session) -> Dict[str, Any]:
        """
        Generate a simple session summary (backwards compatibility).
        
        Args:
            session: The session to summarize
            
        Returns:
            Dict containing session summary
        """
        summary = self._generate_session_summary(session)
        
        return {
            "session_id": session.session_id,
            "summary": summary,
            "timestamp": session.timestamp.isoformat()
        }
    
    def get_therapeutic_insights(self) -> Dict[str, Any]:
        """
        Get comprehensive therapeutic insights across all sessions.
        
        Returns:
            Dict containing therapeutic insights
        """
        logger.info(f"ReflectionAgent: Gathering therapeutic insights for user {self.user_context.user_id}")
        
        try:
            # Get memory insights
            memory = self.memory_agent.get_therapeutic_memory()
            patterns = self.memory_agent.identify_patterns()
            recent_context = self.memory_agent.get_recent_context(num_sessions=5)
            
            # Get planning insights
            current_plan = self.db_service.get_latest_therapy_plan(self.user_context.user_id)
            plan_evolution = self.planning_agent.get_plan_evolution_summary()
            
            plan_assessment = None
            if current_plan:
                plan_assessment = self.planning_agent.assess_plan_effectiveness(current_plan)
            
            return {
                "user_id": self.user_context.user_id,
                "insights_generated_at": datetime.now().isoformat(),
                
                # Memory insights
                "memory_insights": {
                    "total_sessions": len(memory.session_contexts),
                    "relationship_quality": memory.relationship_quality,
                    "recurring_themes": dict(memory.recurring_themes),
                    "emotional_patterns": memory.emotional_patterns,
                    "recent_progress": recent_context.get('insights', []),
                    "patterns": patterns
                },
                
                # Planning insights
                "planning_insights": {
                    "current_plan_id": current_plan.plan_id if current_plan else None,
                    "current_plan_version": current_plan.version if current_plan else None,
                    "plan_effectiveness": plan_assessment,
                    "plan_evolution": plan_evolution
                },
                
                # Combined recommendations
                "recommendations": self._generate_combined_recommendations(memory, patterns, current_plan)
            }
            
        except Exception as e:
            logger.error(f"Failed to gather therapeutic insights: {e}", exc_info=True)
            return {
                "user_id": self.user_context.user_id,
                "error": str(e),
                "insights_generated_at": datetime.now().isoformat()
            }
    
    def _generate_combined_recommendations(self, memory, patterns: Dict[str, Any], 
                                         current_plan: Optional[TherapyPlan]) -> List[Dict[str, Any]]:
        """
        Generate combined recommendations based on memory and planning insights.
        
        Args:
            memory: Therapeutic memory object
            patterns: Identified patterns
            current_plan: Current therapy plan
            
        Returns:
            List of combined recommendations
        """
        recommendations = []
        
        # Memory-based recommendations
        if memory.relationship_quality in ['established', 'strong']:
            recommendations.append({
                'type': 'relationship',
                'description': 'Strong therapeutic relationship established - consider deeper therapeutic work',
                'source': 'memory_analysis',
                'priority': 'medium'
            })
        
        # Pattern-based recommendations
        emotional_trend = patterns.get('emotional_patterns', {}).get('recent_trend', 'stable')
        if emotional_trend == 'improving':
            recommendations.append({
                'type': 'progress',
                'description': 'Positive emotional trend - maintain current approach and build on progress',
                'source': 'pattern_analysis',
                'priority': 'high'
            })
        elif emotional_trend == 'declining':
            recommendations.append({
                'type': 'intervention',
                'description': 'Declining emotional trend - consider plan adjustment or additional support',
                'source': 'pattern_analysis',
                'priority': 'high'
            })
        
        # Planning-based recommendations
        if current_plan:
            plan_recommendations = self.planning_agent.recommend_plan_adjustments(current_plan)
            for rec in plan_recommendations[:3]:  # Top 3 recommendations
                rec['source'] = 'planning_analysis'
                recommendations.append(rec)
        
        return recommendations
    
    def health_check(self) -> bool:
        """
        Perform health check on the reflection agent and its dependencies.
        
        Returns:
            bool: True if healthy, False otherwise
        """
        try:
            # Check memory agent health
            if not self.memory_agent.health_check():
                logger.error("MemoryAgent health check failed")
                return False
            
            # Check planning agent health
            if not self.planning_agent.health_check():
                logger.error("PlanningAgent health check failed")
                return False
            
            # Check LLM service
            test_prompt = "Respond with 'OK' if you can process this request."
            response = self.llm_service.generate_response(test_prompt)
            if 'OK' not in response and 'ok' not in response.lower():
                logger.error("LLM service health check failed")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"ReflectionAgent health check failed: {e}")
            return False
    
    def __str__(self) -> str:
        """String representation of reflection agent."""
        return f"ReflectionAgent(user={self.user_context.user_id}, coordinator)"
    
    def __repr__(self) -> str:
        """Detailed representation of reflection agent."""
        return f"ReflectionAgent(user='{self.user_context.user_id}', memory_agent={type(self.memory_agent).__name__}, planning_agent={type(self.planning_agent).__name__})"
