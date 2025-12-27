# User and Patient Profile Consolidation Plan (Refined)

## Goal Description
Consolidate `user_profiles` and `patient_profiles` into a single, fully flattened standard SQL table. This simplifies the architecture, improves queryability, and ensures data consistency by removing embedded JSON structures.

## User Review Required
> [!IMPORTANT]
> **Database Schema Change**: This plan involves a major migration to a flattened structure.
> - **We will use a single `user_profiles` table.** (This is a neutral name that reflects the primary entity).
> - All fields previously stored in the `PatientProfile` JSON blob will be promoted to individual columns in the `user_profiles` table.

## Proposed Changes

### Data Models (`src/psychoanalyst_app/models/data_models.py`)

#### [MODIFY] [data_models.py](file:///home/fabian/Projects/llm_psychology/psychoanalyst_app/src/psychoanalyst_app/models/data_models.py)
 - Update `UserProfile` to include ALL fields. The nested Pydantic models (like `BasicPatientBackground`) will be removed or used only for grouping in code if needed, but the primary model will be flat.
 - **Unified Model**:
    ```python
    class UserProfile(BaseModel):
        user_id: str
        name: str
        alias: str | None = None
        date_of_birth: datetime | None = None
        gender: str | None = None
        cultural_background: str | None = None
        primary_language: str = "English"
        profession: str | None = None
        status: UserStatus = UserStatus.PROFILE_ONLY
        
        # Family fields
        parents: str | None = None
        siblings: str | None = None
        family_atmosphere: str | None = None
        significant_events: str | None = None
        
        # History & Context
        education: str | None = None
        work_history: str | None = None
        relationship_to_work: str | None = None
        relationships: str | None = None
        social_context: str | None = None
        current_situation: str | None = None
        
        # Frame
        preferred_school: str | None = None
        session_mode: str = "virtual"
        boundary_notes: str | None = None
        frame_notes: str | None = None
        
        created_at: datetime
        updated_at: datetime
    ```

### Database Repositories

#### [NEW] [profiles_repo.py](file:///home/fabian/Projects/llm_psychology/psychoanalyst_app/src/psychoanalyst_app/services/db/repos/profiles_repo.py)
 - Create a clean repository for the flattened `user_profiles` table.
 - Functions: `get_profile(user_id)`, `save_profile(profile)`, `update_status(user_id, status)`.

#### [DELETE] [users_repo.py](file:///home/fabian/Projects/llm_psychology/psychoanalyst_app/src/psychoanalyst_app/services/db/repos/users_repo.py)
 - Replaced by `profiles_repo.py`.

#### [DELETE] [patient_profiles_repo.py](file:///home/fabian/Projects/llm_psychology/psychoanalyst_app/src/psychoanalyst_app/services/db/repos/patient_profiles_repo.py)
 - Replaced by `profiles_repo.py`.

### Database Schema

- **Table: `user_profiles`** (Primary identity table)
    - `user_id`: TEXT PRIMARY KEY
    - `name`: TEXT (Real name)
    - `alias`: TEXT (Pseudonym)
    - `date_of_birth`: TEXT (ISO Date)
    - `gender`: TEXT
    - `cultural_background`: TEXT
    - `primary_language`: TEXT
    - `profession`: TEXT
    - `status`: TEXT (Workflow state)
    - `parents`: TEXT
    - `siblings`: TEXT
    - `family_atmosphere`: TEXT
    - `significant_events`: TEXT
    - `education`: TEXT
    - `work_history`: TEXT
    - `relationship_to_work`: TEXT
    - `relationships`: TEXT
    - `social_context`: TEXT
    - `current_situation`: TEXT
    - `preferred_school`: TEXT
    - `session_mode`: TEXT
    - `boundary_notes`: TEXT
    - `frame_notes`: TEXT
    - `created_at`: TEXT
    - `updated_at`: TEXT

## Verification Plan

### Automated Tests
- **New Repository Tests**: Create `src/psychoanalyst_app/testing/test_profiles_repo.py` to test CRUD operations for the flattened table.
- **Existing Suite**: Run `pytest src/psychoanalyst_app/testing/` to ensure no regressions in auth or other services that use the profile.

### Manual Verification
- **Frontend Check**: Open the browser to `/profile` and ensure user data is fetched correctly.
- **Intake Flow**: Complete an intake session and verify that data is saved into individual columns in the database (`sqlite3 database.db "SELECT * FROM user_profiles;"`).
- **Status Progression**: Verify that advancing the workflow status still updates the `status` column correctly.
