# Task 9: Session Analytics Engine Implementation

## Overview
Build comprehensive analytics engine for therapeutic insights, session analysis, and progress tracking with statistical analysis and pattern recognition.

## Objectives
- Develop session analysis and metrics extraction
- Implement progress calculation algorithms
- Create trend analysis and pattern recognition
- Generate statistical insights and reports

## Time Allocation
- **Duration**: 10 hours
- **Week**: 5
- **Priority**: High

## Technical Requirements

### Analytics Capabilities
- Natural language processing for therapy content
- Emotional content analysis and sentiment scoring
- Topic extraction and categorization
- Engagement metrics calculation
- Progress trend analysis
- Statistical pattern recognition

### Therapeutic Metrics
- Session quality assessment
- Therapeutic relationship indicators
- Goal progress measurement
- Behavioral pattern identification
- Mood tracking and analysis
- Communication effectiveness scoring

## Implementation Details

### Analytics Architecture
- **SessionAnalyticsEngine**: Core analysis orchestration
- **EmotionalAnalyzer**: Sentiment and emotion detection
- **TopicExtractor**: Theme and topic identification
- **EngagementCalculator**: User engagement scoring
- **TrendAnalyzer**: Progress and pattern analysis
- **ReportGenerator**: Insight compilation and reporting

### Analysis Algorithms
- Keyword frequency analysis
- Emotional polarity calculation
- Topic relevance scoring
- Engagement level assessment
- Trend slope calculation
- Statistical significance testing

## Deliverables

### Core Analytics Engine
- [ ] `src/analytics/session_analytics_engine.py`
- [ ] `src/analytics/emotional_analyzer.py`
- [ ] `src/analytics/topic_extractor.py`
- [ ] `src/analytics/engagement_calculator.py`
- [ ] `src/analytics/trend_analyzer.py`
- [ ] `src/analytics/pattern_recognizer.py`

### Processing Components
- [ ] `src/analytics/text_processor.py`
- [ ] `src/analytics/keyword_extractor.py`
- [ ] `src/analytics/sentiment_analyzer.py`
- [ ] `src/analytics/statistical_analyzer.py`
- [ ] `src/analytics/metrics_calculator.py`

### Data Models
- [ ] `src/models/analytics_models.py`
- [ ] `src/models/session_analytics.py`
- [ ] `src/models/progress_models.py`
- [ ] `src/models/trend_models.py`

### Reporting System
- [ ] `src/analytics/report_generator.py`
- [ ] `src/analytics/insight_generator.py`
- [ ] `src/analytics/recommendation_engine.py`
- [ ] `src/api/analytics_routes.py`

### Key Features
- [ ] Comprehensive session analytics engine
- [ ] Emotional content analysis
- [ ] Topic extraction and categorization
- [ ] Engagement and quality metrics
- [ ] Progress trend analysis
- [ ] Statistical insight generation
- [ ] Automated report generation

## Acceptance Criteria

### Analysis Accuracy
- [ ] Emotion detection accuracy > 80%
- [ ] Topic extraction relevance > 85%
- [ ] Engagement scoring consistency > 90%
- [ ] Trend analysis mathematical correctness 100%
- [ ] Statistical calculations verified accuracy
- [ ] Pattern recognition false positive rate < 10%

### Performance Requirements
- [ ] Session analysis completion < 2 seconds
- [ ] Batch processing efficiency for large datasets
- [ ] Real-time analysis capability
- [ ] Memory usage optimized for concurrent analysis
- [ ] Scalable processing for growing data volumes

### Insight Quality
- [ ] Generated insights actionable and relevant
- [ ] Recommendations based on evidence
- [ ] Progress reports accurate and meaningful
- [ ] Trend analysis provides predictive value
- [ ] Statistical significance properly calculated

### Integration Requirements
- [ ] Seamless integration with existing session data
- [ ] API endpoints provide structured analytics data
- [ ] Real-time analytics updates
- [ ] Export capabilities for analysis results
- [ ] Dashboard integration compatibility

## Data Models

### Session Analytics Schema
```python
@dataclass
class SessionAnalytics:
    session_id: str
    user_id: str
    timestamp: datetime
    duration: Optional[int]
    word_count: int
    message_count: int
    emotional_analysis: EmotionalAnalysis
    topic_analysis: TopicAnalysis
    engagement_metrics: EngagementMetrics
    quality_metrics: QualityMetrics
    mood_score: float
    therapy_style: str
    insights: List[str]
    recommendations: List[str]
```

### Emotional Analysis
```python
@dataclass
class EmotionalAnalysis:
    dominant_emotions: List[Tuple[str, float]]
    emotional_intensity: float
    polarity: float  # -1 (negative) to 1 (positive)
    positive_word_count: int
    negative_word_count: int
    emotion_distribution: Dict[str, int]
    mood_indicators: List[str]
    emotional_stability: float
```

### Topic Analysis
```python
@dataclass
class TopicAnalysis:
    primary_topics: List[Tuple[str, float]]
    all_topics: Dict[str, Dict[str, Any]]
    topic_diversity: int
    focus_areas: List[str]
    therapeutic_themes: List[str]
    discussion_depth: float
```

### Progress Metrics
```python
@dataclass
class ProgressReport:
    user_id: str
    time_range: timedelta
    session_count: int
    session_analytics: List[SessionAnalytics]
    trends: TrendAnalysis
    insights: List[Insight]
    recommendations: List[Recommendation]
    generated_at: datetime
    overall_progress_score: float
```

## Implementation Phases

### Phase 1: Core Analytics (4 hours)
1. Build session analysis framework
2. Implement emotional content analysis
3. Create topic extraction algorithms
4. Add basic metrics calculation

### Phase 2: Advanced Analysis (4 hours)
1. Develop engagement scoring algorithms
2. Implement trend analysis and pattern recognition
3. Create statistical analysis functions
4. Add quality assessment metrics

### Phase 3: Insights & Reporting (2 hours)
1. Build insight generation engine
2. Create recommendation algorithms
3. Implement report generation
4. Add API endpoints and integration

## Emotional Analysis Implementation

### Emotion Detection
```python
class EmotionalAnalyzer:
    def __init__(self):
        self.emotion_keywords = self._load_emotion_lexicon()
        self.sentiment_weights = self._load_sentiment_weights()
        
    def _load_emotion_lexicon(self) -> Dict[str, List[str]]:
        """Load categorized emotion keywords"""
        return {
            'joy': ['happy', 'excited', 'pleased', 'delighted', 'cheerful', 'elated', 'euphoric'],
            'sadness': ['sad', 'depressed', 'melancholy', 'dejected', 'sorrowful', 'gloomy'],
            'anger': ['angry', 'furious', 'irritated', 'frustrated', 'enraged', 'livid'],
            'fear': ['afraid', 'scared', 'anxious', 'worried', 'terrified', 'nervous'],
            'surprise': ['surprised', 'shocked', 'amazed', 'astonished', 'startled'],
            'disgust': ['disgusted', 'revolted', 'repulsed', 'sickened'],
            'trust': ['trusting', 'confident', 'secure', 'comfortable', 'peaceful'],
            'anticipation': ['excited', 'eager', 'hopeful', 'optimistic', 'expectant']
        }
    
    def analyze_emotional_content(self, text: str) -> EmotionalAnalysis:
        """Comprehensive emotional analysis of session text"""
        text_lower = text.lower()
        words = text_lower.split()
        
        # Calculate emotion scores
        emotion_scores = self._calculate_emotion_scores(text_lower)
        
        # Determine dominant emotions
        dominant_emotions = sorted(emotion_scores.items(), 
                                 key=lambda x: x[1], reverse=True)[:3]
        
        # Calculate emotional intensity
        total_emotional_words = sum(emotion_scores.values())
        emotional_intensity = total_emotional_words / max(len(words), 1)
        
        # Calculate polarity
        polarity = self._calculate_emotional_polarity(emotion_scores)
        
        # Count positive/negative indicators
        positive_count, negative_count = self._count_polarity_words(text_lower)
        
        # Assess emotional stability
        emotional_stability = self._assess_emotional_stability(emotion_scores)
        
        return EmotionalAnalysis(
            dominant_emotions=dominant_emotions,
            emotional_intensity=emotional_intensity,
            polarity=polarity,
            positive_word_count=positive_count,
            negative_word_count=negative_count,
            emotion_distribution=emotion_scores,
            mood_indicators=self._extract_mood_indicators(text_lower),
            emotional_stability=emotional_stability
        )
    
    def _calculate_emotion_scores(self, text: str) -> Dict[str, int]:
        """Calculate frequency scores for each emotion category"""
        emotion_scores = defaultdict(int)
        
        for emotion, keywords in self.emotion_keywords.items():
            for keyword in keywords:
                # Use word boundaries to match whole words
                matches = len(re.findall(r'\b' + re.escape(keyword) + r'\b', text))
                emotion_scores[emotion] += matches
        
        return dict(emotion_scores)
    
    def _calculate_emotional_polarity(self, emotion_scores: Dict[str, int]) -> float:
        """Calculate overall emotional polarity (-1 to 1)"""
        positive_emotions = ['joy', 'trust', 'anticipation']
        negative_emotions = ['sadness', 'anger', 'fear', 'disgust']
        
        positive_score = sum(emotion_scores.get(emotion, 0) for emotion in positive_emotions)
        negative_score = sum(emotion_scores.get(emotion, 0) for emotion in negative_emotions)
        
        total_score = positive_score + negative_score
        if total_score == 0:
            return 0.0
        
        return (positive_score - negative_score) / total_score
```

### Topic Extraction
```python
class TopicExtractor:
    def __init__(self):
        self.therapy_categories = self._load_therapy_categories()
        self.stopwords = self._load_stopwords()
        
    def _load_therapy_categories(self) -> Dict[str, List[str]]:
        """Load therapy-specific topic categories"""
        return {
            'relationships': [
                'family', 'friends', 'partner', 'spouse', 'marriage', 'divorce',
                'communication', 'conflict', 'trust', 'intimacy', 'boundaries'
            ],
            'work_stress': [
                'job', 'work', 'career', 'boss', 'colleague', 'deadline', 'pressure',
                'burnout', 'workplace', 'promotion', 'unemployment', 'workload'
            ],
            'emotional_regulation': [
                'anxiety', 'depression', 'mood', 'feelings', 'emotions', 'stress',
                'coping', 'overwhelmed', 'calm', 'balance', 'mindfulness'
            ],
            'self_concept': [
                'identity', 'self-esteem', 'confidence', 'worth', 'shame', 'guilt',
                'perfectionism', 'criticism', 'validation', 'acceptance'
            ],
            'life_transitions': [
                'change', 'transition', 'loss', 'grief', 'moving', 'retirement',
                'pregnancy', 'parenthood', 'aging', 'illness', 'death'
            ],
            'behavioral_patterns': [
                'habits', 'addiction', 'compulsive', 'avoidance', 'procrastination',
                'patterns', 'routine', 'behavior', 'actions', 'choices'
            ]
        }
    
    def extract_topics(self, text: str) -> TopicAnalysis:
        """Extract and analyze topics from session text"""
        text_lower = text.lower()
        words = self._preprocess_text(text_lower)
        
        # Calculate topic relevance scores
        topic_scores = self._calculate_topic_scores(text_lower)
        
        # Determine primary topics
        primary_topics = sorted(topic_scores.items(), 
                              key=lambda x: x[1]['relevance'], reverse=True)[:3]
        
        # Calculate topic diversity
        topic_diversity = len([score for score in topic_scores.values() if score['relevance'] > 0.01])
        
        # Extract focus areas and themes
        focus_areas = self._identify_focus_areas(topic_scores)
        therapeutic_themes = self._extract_therapeutic_themes(text_lower, topic_scores)
        
        # Assess discussion depth
        discussion_depth = self._calculate_discussion_depth(words, topic_scores)
        
        return TopicAnalysis(
            primary_topics=primary_topics,
            all_topics=topic_scores,
            topic_diversity=topic_diversity,
            focus_areas=focus_areas,
            therapeutic_themes=therapeutic_themes,
            discussion_depth=discussion_depth
        )
    
    def _calculate_topic_scores(self, text: str) -> Dict[str, Dict[str, Any]]:
        """Calculate relevance scores for each topic category"""
        topic_scores = {}
        
        for category, keywords in self.therapy_categories.items():
            matches = 0
            matched_keywords = []
            
            for keyword in keywords:
                count = len(re.findall(r'\b' + re.escape(keyword) + r'\b', text))
                if count > 0:
                    matches += count
                    matched_keywords.append(keyword)
            
            if matches > 0:
                # Normalize by text length
                relevance = matches / len(text.split())
                topic_scores[category] = {
                    'relevance': relevance,
                    'match_count': matches,
                    'keywords': matched_keywords,
                    'coverage': len(matched_keywords) / len(keywords)
                }
        
        return topic_scores
```

### Engagement Analysis
```python
class EngagementCalculator:
    def __init__(self):
        self.engagement_indicators = self._load_engagement_indicators()
        
    def calculate_engagement_metrics(self, session: Session) -> EngagementMetrics:
        """Calculate comprehensive user engagement metrics"""
        user_messages = [msg for msg in session.transcript if msg.role == "user"]
        
        if not user_messages:
            return EngagementMetrics(level=0.0, indicators={})
        
        # Calculate engagement indicators
        message_length_score = self._calculate_message_length_score(user_messages)
        response_frequency_score = self._calculate_response_frequency_score(user_messages)
        emotional_expression_score = self._calculate_emotional_expression_score(user_messages)
        topic_exploration_score = self._calculate_topic_exploration_score(user_messages)
        session_duration_score = self._calculate_duration_score(session.duration)
        
        # Weighted overall engagement score
        engagement_level = (
            message_length_score * 0.25 +
            response_frequency_score * 0.20 +
            emotional_expression_score * 0.25 +
            topic_exploration_score * 0.20 +
            session_duration_score * 0.10
        )
        
        return EngagementMetrics(
            level=min(1.0, engagement_level),
            indicators={
                'message_length_score': message_length_score,
                'response_frequency_score': response_frequency_score,
                'emotional_expression_score': emotional_expression_score,
                'topic_exploration_score': topic_exploration_score,
                'session_duration_score': session_duration_score,
                'average_message_length': statistics.mean(len(msg.content.split()) for msg in user_messages),
                'total_user_words': sum(len(msg.content.split()) for msg in user_messages),
                'message_count': len(user_messages)
            }
        )
    
    def _calculate_message_length_score(self, messages: List[Message]) -> float:
        """Score based on message length indicating thoughtful responses"""
        avg_length = statistics.mean(len(msg.content.split()) for msg in messages)
        # Optimal range: 15-30 words per message
        if avg_length < 5:
            return 0.2
        elif avg_length < 10:
            return 0.5
        elif avg_length < 15:
            return 0.7
        elif avg_length <= 30:
            return 1.0
        else:
            return max(0.8, 1.0 - (avg_length - 30) * 0.01)  # Penalty for overly long messages
    
    def _calculate_emotional_expression_score(self, messages: List[Message]) -> float:
        """Score based on emotional expression and vulnerability"""
        emotional_indicators = [
            'feel', 'felt', 'feeling', 'emotion', 'angry', 'sad', 'happy',
            'anxious', 'worried', 'excited', 'frustrated', 'calm', 'stressed'
        ]
        
        total_words = sum(len(msg.content.split()) for msg in messages)
        emotional_words = 0
        
        for msg in messages:
            content_lower = msg.content.lower()
            for indicator in emotional_indicators:
                emotional_words += content_lower.count(indicator)
        
        if total_words == 0:
            return 0.0
        
        emotional_ratio = emotional_words / total_words
        return min(1.0, emotional_ratio * 10)  # Scale to 0-1 range
```

### Progress Trend Analysis
```python
class TrendAnalyzer:
    def __init__(self):
        self.trend_algorithms = self._initialize_trend_algorithms()
        
    def analyze_progress_trends(self, analytics_history: List[SessionAnalytics]) -> TrendAnalysis:
        """Analyze trends across multiple sessions"""
        if len(analytics_history) < 2:
            return TrendAnalysis(insufficient_data=True)
        
        # Sort by timestamp
        sorted_analytics = sorted(analytics_history, key=lambda x: x.timestamp)
        
        # Calculate various trends
        mood_trend = self._calculate_mood_trend(sorted_analytics)
        engagement_trend = self._calculate_engagement_trend(sorted_analytics)
        topic_evolution = self._analyze_topic_evolution(sorted_analytics)
        quality_trend = self._calculate_quality_trend(sorted_analytics)
        consistency_trend = self._calculate_consistency_trend(sorted_analytics)
        
        # Overall progress assessment
        overall_progress = self._calculate_overall_progress(
            mood_trend, engagement_trend, quality_trend, consistency_trend
        )
        
        return TrendAnalysis(
            mood_trend=mood_trend,
            engagement_trend=engagement_trend,
            topic_evolution=topic_evolution,
            quality_trend=quality_trend,
            consistency_trend=consistency_trend,
            overall_progress=overall_progress,
            insufficient_data=False,
            confidence_level=self._calculate_confidence_level(sorted_analytics)
        )
    
    def _calculate_mood_trend(self, analytics: List[SessionAnalytics]) -> TrendData:
        """Calculate mood improvement/decline trend"""
        mood_scores = [a.mood_score for a in analytics]
        return self._calculate_linear_trend(mood_scores, "mood")
    
    def _calculate_linear_trend(self, values: List[float], metric_name: str) -> TrendData:
        """Calculate linear trend using least squares regression"""
        if len(values) < 2:
            return TrendData(direction='stable', strength=0.0, change=0.0, metric=metric_name)
        
        n = len(values)
        x = list(range(n))
        
        # Calculate slope using least squares
        x_mean = statistics.mean(x)
        y_mean = statistics.mean(values)
        
        numerator = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            slope = 0
        else:
            slope = numerator / denominator
        
        # Calculate R-squared for trend strength
        y_pred = [y_mean + slope * (x[i] - x_mean) for i in range(n)]
        ss_res = sum((values[i] - y_pred[i]) ** 2 for i in range(n))
        ss_tot = sum((values[i] - y_mean) ** 2 for i in range(n))
        
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        # Determine trend direction and strength
        if abs(slope) < 0.01:
            direction = 'stable'
        elif slope > 0:
            direction = 'improving'
        else:
            direction = 'declining'
        
        # Calculate percentage change
        if values[0] != 0:
            change_percent = ((values[-1] - values[0]) / abs(values[0])) * 100
        else:
            change_percent = 0
        
        return TrendData(
            direction=direction,
            strength=r_squared,
            change=change_percent,
            slope=slope,
            metric=metric_name,
            confidence=r_squared  # Higher R-squared indicates more reliable trend
        )
```

## Integration with Progress Tracking

### Goal Progress Integration
```python
async def analyze_goal_progress(self, user_id: str, goal_id: str) -> GoalProgressAnalysis:
    """Analyze progress towards specific therapeutic goals"""
    
    # Get goal details and related sessions
    goal = await self.db_service.get_goal(goal_id)
    goal_sessions = await self.db_service.get_sessions_for_goal(goal_id)
    
    # Analyze sessions for goal-related content
    goal_analytics = []
    for session in goal_sessions:
        analytics = await self.analyze_session(session)
        goal_relevance = self._calculate_goal_relevance(analytics, goal)
        analytics.goal_relevance = goal_relevance
        goal_analytics.append(analytics)
    
    # Calculate progress metrics
    progress_score = self._calculate_goal_progress_score(goal_analytics, goal)
    progress_trend = self._analyze_goal_progress_trend(goal_analytics)
    
    # Generate insights and recommendations
    insights = self._generate_goal_insights(goal_analytics, goal)
    recommendations = self._generate_goal_recommendations(goal_analytics, goal, progress_trend)
    
    return GoalProgressAnalysis(
        goal_id=goal_id,
        progress_score=progress_score,
        trend=progress_trend,
        session_count=len(goal_analytics),
        insights=insights,
        recommendations=recommendations,
        confidence_level=self._calculate_goal_analysis_confidence(goal_analytics)
    )
```

## API Integration

### Analytics Endpoints
```python
# Analytics API routes
@router.get("/analytics/session/{session_id}")
async def get_session_analytics(session_id: str, current_user: str = Depends(get_current_user)):
    session = await db_service.get_session(session_id)
    if not session or session.user_id != current_user:
        raise HTTPException(status_code=404, detail="Session not found")
    
    analytics = await analytics_engine.analyze_session(session)
    return analytics

@router.get("/analytics/progress/{user_id}")
async def get_progress_analytics(
    user_id: str, 
    timeframe: str = "month",
    current_user: str = Depends(get_current_user)
):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="Access denied")
    
    time_range = timedelta(days=30 if timeframe == "month" else 7)
    progress_report = await analytics_engine.generate_progress_report(user_id, time_range)
    return progress_report

@router.get("/analytics/trends/{user_id}")
async def get_trend_analysis(user_id: str, current_user: str = Depends(get_current_user)):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="Access denied")
    
    recent_sessions = await db_service.get_recent_user_sessions(user_id, limit=10)
    analytics_history = [await analytics_engine.analyze_session(s) for s in recent_sessions]
    
    trends = trend_analyzer.analyze_progress_trends(analytics_history)
    return trends
```

## Testing Strategy

### Analytics Accuracy Testing
- Emotion detection validation with labeled datasets
- Topic extraction relevance testing
- Engagement scoring consistency verification
- Trend analysis mathematical validation
- Progress calculation accuracy testing

### Performance Testing
- Large session analysis performance
- Batch processing efficiency
- Real-time analysis capability
- Memory usage optimization
- Concurrent analysis handling

### Integration Testing
- Database integration functionality
- API endpoint response validation
- Frontend analytics display accuracy
- Export functionality verification
- Error handling robustness

## Success Metrics
- Emotion detection accuracy > 80%
- Topic extraction relevance > 85%
- Engagement scoring consistency > 90%
- Analysis completion time < 2 seconds
- Statistical accuracy 100%
- User insight satisfaction > 4.0/5