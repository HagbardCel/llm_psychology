"""
Unit tests for tiered patient information data models.

Tests validation, serialization, and deserialization of all Tier 1-4 models.
"""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from models.data_models import (
    AnalyticFrame,
    AnalyticOrientation,
    BasicPatientBackground,
    CurrentFocus,
    DefensiveOrganization,
    DetailedSession,
    EducationalWorkHistory,
    FamilyConstellation,
    Message,
    PatientAnalysis,
    PatientAnalysisVersion,
    PatientProfile,
    RecurringNarrative,
    RelationalLifeContext,
    TherapyPlan,
    Topic,
    TransferenceImpressions,
)


# ============================================================================
# TIER 1: Static Background Tests
# ============================================================================


class TestBasicPatientBackground:
    """Tests for BasicPatientBackground model."""

    def test_valid_basic_background(self):
        """Test creating valid basic patient background."""
        background = BasicPatientBackground(
            alias="TestPatient",
            date_of_birth=datetime(1990, 5, 15),
            gender="non-binary",
            cultural_background="Second-generation Chinese-American",
            primary_language="English",
        )
        assert background.alias == "TestPatient"
        assert background.gender == "non-binary"

    def test_alias_required(self):
        """Test that alias is required."""
        with pytest.raises(ValidationError):
            BasicPatientBackground()

    def test_alias_min_length(self):
        """Test alias minimum length validation."""
        with pytest.raises(ValidationError):
            BasicPatientBackground(alias="")

    def test_alias_max_length(self):
        """Test alias maximum length validation."""
        with pytest.raises(ValidationError):
            BasicPatientBackground(alias="x" * 101)

    def test_cultural_background_max_length(self):
        """Test cultural background max length validation."""
        with pytest.raises(ValidationError):
            BasicPatientBackground(
                alias="Test", cultural_background="x" * 501
            )

    def test_default_primary_language(self):
        """Test default primary language is English."""
        background = BasicPatientBackground(alias="Test")
        assert background.primary_language == "English"

    def test_optional_fields(self):
        """Test that optional fields can be None."""
        background = BasicPatientBackground(
            alias="Test",
            date_of_birth=None,
            gender=None,
            cultural_background=None,
        )
        assert background.date_of_birth is None
        assert background.gender is None


class TestFamilyConstellation:
    """Tests for FamilyConstellation model."""

    def test_all_fields_optional(self):
        """Test all family fields are optional."""
        family = FamilyConstellation()
        assert family.parents is None
        assert family.siblings is None
        assert family.family_atmosphere is None
        assert family.significant_events is None

    def test_field_max_lengths(self):
        """Test field max length validations."""
        # Parents max length
        with pytest.raises(ValidationError):
            FamilyConstellation(parents="x" * 1001)

        # Siblings max length
        with pytest.raises(ValidationError):
            FamilyConstellation(siblings="x" * 501)

    def test_valid_family_data(self):
        """Test creating valid family constellation."""
        family = FamilyConstellation(
            parents="Mother alive, father deceased",
            siblings="Older brother, younger sister",
            family_atmosphere="High achieving, emotionally distant",
            significant_events="Father's death when patient was 20",
        )
        assert "deceased" in family.parents


class TestPatientProfile:
    """Tests for complete PatientProfile model."""

    def test_valid_patient_profile(self):
        """Test creating valid complete patient profile."""
        profile = PatientProfile(
            user_id="user123",
            basic_info=BasicPatientBackground(alias="Alex"),
            family=FamilyConstellation(),
            history=EducationalWorkHistory(),
            context=RelationalLifeContext(),
            frame=AnalyticFrame(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert profile.user_id == "user123"
        assert profile.basic_info.alias == "Alex"

    def test_json_serialization_roundtrip(self):
        """Test JSON serialization and deserialization."""
        original = PatientProfile(
            user_id="user123",
            basic_info=BasicPatientBackground(
                alias="Test", cultural_background="Test culture"
            ),
            family=FamilyConstellation(parents="Test parents"),
            history=EducationalWorkHistory(),
            context=RelationalLifeContext(),
            frame=AnalyticFrame(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        # Serialize to JSON
        json_str = original.model_dump_json()
        json_dict = json.loads(json_str)

        # Deserialize back
        restored = PatientProfile.model_validate(json_dict)

        assert restored.user_id == original.user_id
        assert restored.basic_info.alias == original.basic_info.alias
        assert (
            restored.basic_info.cultural_background
            == original.basic_info.cultural_background
        )


# ============================================================================
# TIER 2: Session History Tests
# ============================================================================


class TestDetailedSession:
    """Tests for DetailedSession model."""

    def test_basic_session_fields(self):
        """Test standard session fields."""
        session = DetailedSession(
            session_id="sess123",
            user_id="user123",
            timestamp=datetime.now(),
            transcript=[
                Message(
                    role="user",
                    content="Hello",
                    timestamp=datetime.now(),
                )
            ],
        )
        assert session.session_id == "sess123"
        assert len(session.transcript) == 1

    def test_tier2_enrichment_fields(self):
        """Test Tier 2 enrichment fields."""
        session = DetailedSession(
            session_id="sess123",
            user_id="user123",
            timestamp=datetime.now(),
            transcript=[],
            psychological_summary="Patient discussed work anxiety...",
            dominant_affects=["anxiety", "sadness"],
            key_themes=["work stress", "family conflict"],
            notable_interactions="Strong resistance to interpretation",
            interpretations="Linked anxiety to father relationship",
            patient_reactions="Initially defensive, then tearful",
            enriched=True,
        )
        assert session.enriched is True
        assert "anxiety" in session.dominant_affects
        assert len(session.key_themes) == 2

    def test_default_enriched_false(self):
        """Test enriched defaults to False."""
        session = DetailedSession(
            session_id="sess123",
            user_id="user123",
            timestamp=datetime.now(),
            transcript=[],
        )
        assert session.enriched is False

    def test_psychological_summary_max_length(self):
        """Test psychological summary max length validation."""
        with pytest.raises(ValidationError):
            DetailedSession(
                session_id="sess123",
                user_id="user123",
                timestamp=datetime.now(),
                transcript=[],
                psychological_summary="x" * 3001,
            )


# ============================================================================
# TIER 3: Dynamic Analysis Tests
# ============================================================================


class TestCurrentFocus:
    """Tests for CurrentFocus model."""

    def test_valid_current_focus(self):
        """Test creating valid current focus."""
        focus = CurrentFocus(
            theme="Unresolved grief about father",
            salience="Recent work stress activating old patterns",
        )
        assert "grief" in focus.theme

    def test_theme_required(self):
        """Test theme is required."""
        with pytest.raises(ValidationError):
            CurrentFocus(salience="test")

    def test_theme_max_length(self):
        """Test theme max length validation."""
        with pytest.raises(ValidationError):
            CurrentFocus(theme="x" * 201, salience="test")


class TestPatientAnalysis:
    """Tests for PatientAnalysis model."""

    def test_valid_patient_analysis(self):
        """Test creating valid patient analysis."""
        analysis = PatientAnalysis(
            current_focus=CurrentFocus(
                theme="Work anxiety", salience="Recent promotion"
            ),
            transference=TransferenceImpressions(),
            narratives=[
                RecurringNarrative(
                    title="The Perfect Performance",
                    description="Pattern of needing to be perfect",
                )
            ],
            defenses=DefensiveOrganization(
                primary_defenses=["intellectualization", "isolation"]
            ),
            orientation=AnalyticOrientation(pacing="Gentle exploration"),
        )
        assert len(analysis.narratives) == 1
        assert "intellectualization" in analysis.defenses.primary_defenses

    def test_json_serialization(self):
        """Test analysis JSON serialization."""
        analysis = PatientAnalysis(
            current_focus=CurrentFocus(theme="Test", salience="Test"),
            transference=TransferenceImpressions(),
            defenses=DefensiveOrganization(),
            orientation=AnalyticOrientation(),
        )

        json_str = analysis.model_dump_json()
        restored = PatientAnalysis.model_validate_json(json_str)

        assert restored.current_focus.theme == "Test"


class TestPatientAnalysisVersion:
    """Tests for PatientAnalysisVersion model."""

    def test_version_creation(self):
        """Test creating analysis version."""
        analysis = PatientAnalysis(
            current_focus=CurrentFocus(theme="Test", salience="Test"),
            transference=TransferenceImpressions(),
            defenses=DefensiveOrganization(),
            orientation=AnalyticOrientation(),
        )

        version = PatientAnalysisVersion(
            user_id="user123",
            version=1,
            analysis_data=analysis,
            change_summary="Initial formulation",
        )

        assert version.version == 1
        assert version.change_summary == "Initial formulation"
        assert version.superseded_by is None

    def test_auto_generated_fields(self):
        """Test auto-generated fields."""
        version = PatientAnalysisVersion(
            user_id="user123",
            version=1,
            analysis_data=PatientAnalysis(
                current_focus=CurrentFocus(theme="Test", salience="Test"),
                transference=TransferenceImpressions(),
                defenses=DefensiveOrganization(),
                orientation=AnalyticOrientation(),
            ),
        )

        assert version.analysis_id.startswith("analysis_")
        assert isinstance(version.created_at, datetime)

    def test_version_min_value(self):
        """Test version must be >= 1."""
        with pytest.raises(ValidationError):
            PatientAnalysisVersion(
                user_id="user123",
                version=0,
                analysis_data=PatientAnalysis(
                    current_focus=CurrentFocus(theme="Test", salience="Test"),
                    transference=TransferenceImpressions(),
                    defenses=DefensiveOrganization(),
                    orientation=AnalyticOrientation(),
                ),
            )

    def test_version_linking(self):
        """Test version superseding links."""
        v1 = PatientAnalysisVersion(
            user_id="user123",
            version=1,
            analysis_data=PatientAnalysis(
                current_focus=CurrentFocus(theme="Test", salience="Test"),
                transference=TransferenceImpressions(),
                defenses=DefensiveOrganization(),
                orientation=AnalyticOrientation(),
            ),
        )

        v2 = PatientAnalysisVersion(
            user_id="user123",
            version=2,
            analysis_data=PatientAnalysis(
                current_focus=CurrentFocus(
                    theme="Updated theme", salience="Test"
                ),
                transference=TransferenceImpressions(),
                defenses=DefensiveOrganization(),
                orientation=AnalyticOrientation(),
            ),
        )

        # Simulate linking
        v1.superseded_by = v2.analysis_id
        assert v1.superseded_by == v2.analysis_id


# ============================================================================
# TIER 4: Treatment Plan Tests
# ============================================================================


class TestTherapyPlanTier4:
    """Tests for TherapyPlan Tier 4 fields."""

    def test_tier4_fields_required(self):
        """TherapyPlan requires Tier 4 fields (no backwards-compat defaults)."""
        with pytest.raises(ValidationError):
            TherapyPlan(
                plan_id="plan123",
                user_id="user123",
                plan_details={"focus": "stabilize"},
            )

    def test_custom_tier4_data(self):
        """Tier 4 data can be populated explicitly."""
        plan = TherapyPlan(
            plan_id="plan123",
            user_id="user123",
            plan_details={"focus": "growth"},
            initial_goals=["Reduce anxiety"],
            current_progress="Moderate improvement",
            planned_interventions=["CBT", "Mindfulness"],
            status="paused",
        )
        assert plan.initial_goals == ["Reduce anxiety"]
        assert plan.current_progress.startswith("Moderate")
        assert plan.planned_interventions[0] == "CBT"
        assert plan.status == "paused"

    def test_serialization_roundtrip(self):
        """Ensure Tier 4 fields persist through JSON serialization."""
        original = TherapyPlan(
            plan_id="planABC",
            user_id="user123",
            plan_details={"focus": "relationships"},
            initial_goals=["Improve communication"],
            current_progress="Baseline established",
            planned_interventions=["Role-play"],
            status="active",
        )

        restored = TherapyPlan.model_validate_json(original.model_dump_json())
        assert restored.initial_goals == ["Improve communication"]
        assert restored.current_progress == "Baseline established"
        assert restored.planned_interventions == ["Role-play"]

# ============================================================================
# Integration Tests
# ============================================================================


class TestModelIntegration:
    """Tests for model integration and complex scenarios."""

    def test_complete_patient_file_structure(self):
        """Test creating complete patient file with all tiers."""
        # Tier 1: Patient Profile
        profile = PatientProfile(
            user_id="user123",
            basic_info=BasicPatientBackground(alias="Alex"),
            family=FamilyConstellation(parents="Test"),
            history=EducationalWorkHistory(),
            context=RelationalLifeContext(),
            frame=AnalyticFrame(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        # Tier 2: Detailed Session
        session = DetailedSession(
            session_id="sess123",
            user_id="user123",
            timestamp=datetime.now(),
            transcript=[],
            psychological_summary="Test summary",
            enriched=True,
        )

        # Tier 3: Patient Analysis
        analysis = PatientAnalysisVersion(
            user_id="user123",
            version=1,
            analysis_data=PatientAnalysis(
                current_focus=CurrentFocus(theme="Test", salience="Test"),
                transference=TransferenceImpressions(),
                defenses=DefensiveOrganization(),
                orientation=AnalyticOrientation(),
            ),
        )

        # Tier 4: Therapy Plan
        plan = TherapyPlan(
            user_id="user123",
            plan_details={"focus": "stability"},
            initial_goals=["Goal 1"],
            current_progress="Progress",
            planned_interventions=["Supportive listening"],
        )

        # All should have same user_id
        assert profile.user_id == session.user_id == analysis.user_id == plan.user_id

    def test_serialization_preserves_nested_structure(self):
        """Test that serialization preserves nested model structure."""
        profile = PatientProfile(
            user_id="user123",
            basic_info=BasicPatientBackground(
                alias="Test",
                cultural_background="Test culture",
                primary_language="Spanish",
            ),
            family=FamilyConstellation(
                parents="Test parents",
                siblings="Test siblings",
            ),
            history=EducationalWorkHistory(education="PhD"),
            context=RelationalLifeContext(
                current_situation="Test situation"
            ),
            frame=AnalyticFrame(session_mode="in-person"),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        # Serialize and restore
        json_str = profile.model_dump_json()
        restored = PatientProfile.model_validate_json(json_str)

        # Check nested fields preserved
        assert restored.basic_info.cultural_background == "Test culture"
        assert restored.basic_info.primary_language == "Spanish"
        assert restored.family.parents == "Test parents"
        assert restored.history.education == "PhD"
        assert restored.context.current_situation == "Test situation"
        assert restored.frame.session_mode == "in-person"
