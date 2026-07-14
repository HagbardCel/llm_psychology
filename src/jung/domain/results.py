"""Application read models for Phase 4 and Phase 5 adapters."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from jung.domain.models import AppSnapshot, Message, Plan, Profile, Session


class StyleSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str


class ProfileView(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: Profile
    current_plan: Plan | None
    snapshot: AppSnapshot


class SessionHistory(BaseModel):
    model_config = ConfigDict(frozen=True)

    session: Session
    messages: tuple[Message, ...]
    plans: tuple[Plan, ...]
