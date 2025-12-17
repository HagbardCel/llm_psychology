/**
 * Type Converters
 *
 * Utility functions to convert between generated backend types and client types.
 * Handles field name mappings (userid → id) and client-only fields.
 */

import type {
  UserProfile as GeneratedUserProfile,
  Session as GeneratedSession,
  TherapyPlan as GeneratedTherapyPlan,
} from './generated/api';
import type { User, Session, TherapyPlan } from './index';

// ============================================================================
// User / UserProfile Converters
// ============================================================================

/**
 * Convert generated UserProfile to client User type
 */
export function toUser(profile: GeneratedUserProfile): User {
  return {
    ...profile,
    id: profile.userid,
    // Client-only fields remain undefined unless set elsewhere
  };
}

/**
 * Convert client User to generated UserProfile (for API requests)
 */
export function fromUser(user: User): GeneratedUserProfile {
  const { id, email, lastActiveAt, ...rest } = user;
  return {
    ...rest,
    userid: id,
  } as GeneratedUserProfile;
}

// ============================================================================
// Session Converters
// ============================================================================

/**
 * Convert generated Session to client Session type
 */
export function toSession(session: GeneratedSession): Session {
  // Type assertion needed due to complex type mapping
  const { sessionid, userid, ...rest } = session as any;

  return {
    ...rest,
    id: sessionid || '',
    userId: userid || '',
    // Client-only fields remain undefined unless set elsewhere
  };
}

/**
 * Convert client Session to generated Session (for API requests)
 */
export function fromSession(session: Session): GeneratedSession {
  const {
    id,
    userId,
    agentType,
    therapyStyle,
    status,
    startTime,
    endTime,
    metadata,
    ...rest
  } = session;

  return {
    ...rest,
    sessionid: id,
    userid: userId,
  } as GeneratedSession;
}

// ============================================================================
// TherapyPlan Converters
// ============================================================================

/**
 * Convert generated TherapyPlan to client TherapyPlan type
 */
export function toTherapyPlan(plan: GeneratedTherapyPlan): TherapyPlan {
  // Type assertion for field mapping (quicktype currently generates `planid`/`userid`).
  const { planid, userid, selectedTherapyStyle, ...rest } = plan as any;

  return {
    ...rest,
    id: planid || (plan as any).planId || '',
    userId: userid || (plan as any).userId || '',
    therapyStyle: selectedTherapyStyle ?? undefined,
    // Client-only fields remain undefined unless set elsewhere
  };
}

/**
 * Convert client TherapyPlan to generated TherapyPlan (for API requests)
 */
export function fromTherapyPlan(plan: TherapyPlan): GeneratedTherapyPlan {
  const { id, userId, therapyStyle, goals, sessionCount, ...rest } = plan;

  return {
    ...rest,
    planid: id,
    userid: userId,
    selectedTherapyStyle: therapyStyle,
  } as GeneratedTherapyPlan;
}

// ============================================================================
// Batch Converters
// ============================================================================

/**
 * Convert array of generated UserProfiles to client Users
 */
export function toUsers(profiles: GeneratedUserProfile[]): User[] {
  return profiles.map(toUser);
}

/**
 * Convert array of generated Sessions to client Sessions
 */
export function toSessions(sessions: GeneratedSession[]): Session[] {
  return sessions.map(toSession);
}

/**
 * Convert array of generated TherapyPlans to client TherapyPlans
 */
export function toTherapyPlans(plans: GeneratedTherapyPlan[]): TherapyPlan[] {
  return plans.map(toTherapyPlan);
}
