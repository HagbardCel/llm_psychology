/**
 * Tests for type converter utilities
 */

import { describe, it, expect } from '@jest/globals';
import {
  toUser,
  fromUser,
  toSession,
  fromSession,
  toTherapyPlan,
  fromTherapyPlan,
  toUsers,
  toSessions,
  toTherapyPlans,
} from '../converters';
import type {
  UserProfile as GeneratedUserProfile,
  Session as GeneratedSession,
  TherapyPlan as GeneratedTherapyPlan,
} from '../generated/api';
import type { User, Session, TherapyPlan } from '../index';

describe('Type Converters', () => {
  describe('User / UserProfile Converters', () => {
    it('should convert UserProfile to User', () => {
      const profile: GeneratedUserProfile = {
        userid: 'user-123',
        name: 'Test User',
        birthdate: new Date('1990-01-01'),
        profession: 'Engineer',
        status: 'PROFILE_ONLY',
        createdAt: new Date('2025-01-01'),
        updatedAt: new Date('2025-01-01'),
      };

      const user = toUser(profile);

      expect(user.id).toBe('user-123');
      expect(user.name).toBe('Test User');
      expect(user.birthdate).toEqual(profile.birthdate);
      expect(user.profession).toBe('Engineer');
      expect(user.status).toBe('PROFILE_ONLY');
      expect(user.createdAt).toEqual(profile.createdAt);
      expect(user.updatedAt).toEqual(profile.updatedAt);
    });

    it('should handle optional fields in UserProfile', () => {
      const profile: GeneratedUserProfile = {
        userid: 'user-456',
        name: 'Minimal User',
        status: 'INTAKE_IN_PROGRESS',
        createdAt: new Date(),
        updatedAt: new Date(),
      };

      const user = toUser(profile);

      expect(user.id).toBe('user-456');
      expect(user.name).toBe('Minimal User');
      expect(user.birthdate).toBeUndefined();
      expect(user.profession).toBeUndefined();
    });

    it('should convert User to UserProfile', () => {
      const user: User = {
        id: 'user-789',
        name: 'Frontend User',
        email: 'test@example.com',
        birthdate: new Date('1995-05-05'),
        profession: 'Designer',
        status: 'PLAN_COMPLETE',
        createdAt: new Date('2025-02-01'),
        updatedAt: new Date('2025-02-15'),
        lastActiveAt: new Date('2025-02-20'),
      };

      const profile = fromUser(user);

      expect(profile.userid).toBe('user-789');
      expect(profile.name).toBe('Frontend User');
      expect(profile.birthdate).toEqual(user.birthdate);
      expect(profile.profession).toBe('Designer');
      expect(profile.status).toBe('PLAN_COMPLETE');
      expect(profile.createdAt).toEqual(user.createdAt);
      expect(profile.updatedAt).toEqual(user.updatedAt);
      // Client-only fields should not be in profile
      expect((profile as any).email).toBeUndefined();
      expect((profile as any).lastActiveAt).toBeUndefined();
    });

    it('should handle round-trip conversion', () => {
      const originalProfile: GeneratedUserProfile = {
        userid: 'user-round-trip',
        name: 'Round Trip User',
        status: 'THERAPY_IN_PROGRESS',
        createdAt: new Date(),
        updatedAt: new Date(),
      };

      const user = toUser(originalProfile);
      const backToProfile = fromUser(user);

      expect(backToProfile.userid).toBe(originalProfile.userid);
      expect(backToProfile.name).toBe(originalProfile.name);
      expect(backToProfile.status).toBe(originalProfile.status);
    });

    it('should convert array of UserProfiles to Users', () => {
      const profiles: GeneratedUserProfile[] = [
        {
          userid: 'user-1',
          name: 'User 1',
          status: 'PROFILE_ONLY',
          createdAt: new Date(),
          updatedAt: new Date(),
        },
        {
          userid: 'user-2',
          name: 'User 2',
          status: 'INTAKE_COMPLETE',
          createdAt: new Date(),
          updatedAt: new Date(),
        },
      ];

      const users = toUsers(profiles);

      expect(users).toHaveLength(2);
      expect(users[0].id).toBe('user-1');
      expect(users[1].id).toBe('user-2');
    });
  });

  describe('Session Converters', () => {
    it('should convert GeneratedSession to Session', () => {
      const generatedSession: any = {
        sessionid: 'session-123',
        userid: 'user-123',
        timestamp: new Date('2025-03-01'),
        transcript: [
          {
            role: 'user',
            content: 'Hello',
            timestamp: new Date('2025-03-01T10:00:00Z'),
          },
        ],
        topics: [
          {
            name: 'anxiety',
            status: 'pending',
          },
        ],
      };

      const session = toSession(generatedSession);

      expect(session.id).toBe('session-123');
      expect(session.userId).toBe('user-123');
      expect(session.timestamp).toEqual(generatedSession.timestamp);
      expect(session.transcript).toHaveLength(1);
      expect(session.topics).toHaveLength(1);
    });

    it('should handle empty transcript and topics', () => {
      const generatedSession: any = {
        sessionid: 'session-empty',
        userid: 'user-empty',
        timestamp: new Date(),
        transcript: [],
        topics: [],
      };

      const session = toSession(generatedSession);

      expect(session.id).toBe('session-empty');
      expect(session.transcript).toHaveLength(0);
      expect(session.topics).toHaveLength(0);
    });

    it('should convert Session to GeneratedSession', () => {
      const session: Session = {
        id: 'session-456',
        userId: 'user-456',
        timestamp: new Date('2025-03-15'),
        transcript: [],
        topics: [],
        agentType: undefined,
        therapyStyle: undefined,
        status: undefined,
      };

      const generatedSession = fromSession(session);

      expect((generatedSession as any).sessionid).toBe('session-456');
      expect((generatedSession as any).userid).toBe('user-456');
      // Client-only fields should not be in generated session
      expect((generatedSession as any).agentType).toBeUndefined();
      expect((generatedSession as any).therapyStyle).toBeUndefined();
      expect((generatedSession as any).status).toBeUndefined();
    });

    it('should convert array of Sessions', () => {
      const sessions: any[] = [
        {
          sessionid: 'session-1',
          userid: 'user-1',
          timestamp: new Date(),
          transcript: [],
          topics: [],
        },
        {
          sessionid: 'session-2',
          userid: 'user-2',
          timestamp: new Date(),
          transcript: [],
          topics: [],
        },
      ];

      const converted = toSessions(sessions);

      expect(converted).toHaveLength(2);
      expect(converted[0].id).toBe('session-1');
      expect(converted[1].id).toBe('session-2');
    });
  });

  describe('TherapyPlan Converters', () => {
    it('should convert GeneratedTherapyPlan to TherapyPlan', () => {
      const generatedPlan: any = {
        planId: 'plan-123',
        userId: 'user-123',
        selectedTherapyStyle: 'freud',
        planDetails: { approach: 'psychoanalytic' },
        version: 1,
        createdAt: new Date('2025-04-01'),
        updatedAt: new Date('2025-04-01'),
      };

      const plan = toTherapyPlan(generatedPlan);

      expect(plan.id).toBe('plan-123');
      expect(plan.userId).toBe('user-123');
      expect(plan.therapyStyle).toBe('freud');
      expect(plan.planDetails).toEqual({ approach: 'psychoanalytic' });
      expect(plan.version).toBe(1);
    });

    it('should handle missing optional fields', () => {
      const generatedPlan: any = {
        planId: 'plan-minimal',
        userId: 'user-minimal',
        createdAt: new Date(),
        updatedAt: new Date(),
      };

      const plan = toTherapyPlan(generatedPlan);

      expect(plan.id).toBe('plan-minimal');
      expect(plan.therapyStyle).toBeUndefined();
      expect(plan.planDetails).toBeUndefined();
    });

    it('should convert TherapyPlan to GeneratedTherapyPlan', () => {
      const plan: TherapyPlan = {
        id: 'plan-789',
        userId: 'user-789',
        therapyStyle: 'jung',
        goals: ['goal1', 'goal2'],
        sessionCount: 5,
        createdAt: new Date('2025-05-01'),
        updatedAt: new Date('2025-05-10'),
      };

      const generatedPlan = fromTherapyPlan(plan);

      expect((generatedPlan as any).planId).toBe('plan-789');
      expect((generatedPlan as any).userId).toBe('user-789');
      expect((generatedPlan as any).selectedTherapyStyle).toBe('jung');
      // Client-only fields should not be in generated plan
      expect((generatedPlan as any).goals).toBeUndefined();
      expect((generatedPlan as any).sessionCount).toBeUndefined();
    });

    it('should convert array of TherapyPlans', () => {
      const plans: any[] = [
        {
          planId: 'plan-1',
          userId: 'user-1',
          createdAt: new Date(),
          updatedAt: new Date(),
        },
        {
          planId: 'plan-2',
          userId: 'user-2',
          createdAt: new Date(),
          updatedAt: new Date(),
        },
      ];

      const converted = toTherapyPlans(plans);

      expect(converted).toHaveLength(2);
      expect(converted[0].id).toBe('plan-1');
      expect(converted[1].id).toBe('plan-2');
    });
  });

  describe('Edge Cases', () => {
    it('should handle null values gracefully', () => {
      const profile: GeneratedUserProfile = {
        userid: 'user-null',
        name: 'Null Test',
        birthdate: null,
        profession: null,
        status: 'PROFILE_ONLY',
        createdAt: new Date(),
        updatedAt: new Date(),
      };

      const user = toUser(profile);

      expect(user.birthdate).toBeNull();
      expect(user.profession).toBeNull();
    });

    it('should preserve type information through conversion', () => {
      const profile: GeneratedUserProfile = {
        userid: 'type-test',
        name: 'Type Test',
        status: 'ASSESSMENT_COMPLETE',
        createdAt: new Date(),
        updatedAt: new Date(),
      };

      const user = toUser(profile);

      // Type should be preserved
      expect(typeof user.status).toBe('string');
      expect(user.status).toBe('ASSESSMENT_COMPLETE');
    });
  });
});
