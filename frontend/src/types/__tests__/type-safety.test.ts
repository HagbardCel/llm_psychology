/**
 * Integration tests for type safety across the application
 */

import { describe, it, expect } from 'vitest';
import type {
  User,
  UserStatus,
  Message,
  Session,
  TherapyPlan,
  Topic,
  WorkflowNextAction,
  AgentType,
  TherapyStyle,
  SessionStatus,
} from '../index';

describe('Type Safety Integration', () => {
  describe('User Type', () => {
    it('should enforce required fields', () => {
      const user: User = {
        user_id: 'user-123',
        name: 'Test User',
        status: 'PROFILE_ONLY',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
      };

      expect(user.user_id).toBeDefined();
      expect(user.name).toBeDefined();
      expect(user.status).toBeDefined();
    });

    it('should allow optional fields', () => {
      const user: User = {
        user_id: 'user-123',
        name: 'Test User',
        data_of_birth: '1990-01-01T00:00:00Z',
        profession: 'Engineer',
        status: 'PROFILE_ONLY',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
      };

      expect(user.data_of_birth).toBeDefined();
      expect(user.profession).toBe('Engineer');
    });

    it('should enforce UserStatus enum values', () => {
      const validStatuses: UserStatus[] = [
        'PROFILE_ONLY',
        'INTAKE_IN_PROGRESS',
        'INTAKE_COMPLETE',
        'ASSESSMENT_IN_PROGRESS',
        'ASSESSMENT_COMPLETE',
        'INITIAL_PLAN_COMPLETE',
        'THERAPY_IN_PROGRESS',
        'PLAN_UPDATE_IN_PROGRESS',
        'REFLECTION_IN_PROGRESS',
        'PLAN_UPDATE_COMPLETE',
      ];

      validStatuses.forEach(status => {
        const user: User = {
          user_id: 'test',
          name: 'Test',
          status,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-02T00:00:00Z',
        };

        expect(user.status).toBe(status);
      });
    });
  });

  describe('Message Type', () => {
    it('should support basic message structure', () => {
      const message: Message = {
        role: 'user',
        content: 'Hello, therapist',
        timestamp: '2024-01-01T00:00:00Z',
      };

      expect(message.role).toBe('user');
      expect(message.content).toBe('Hello, therapist');
      expect(typeof message.timestamp).toBe('string');
      // Phase 1 decision (D2): datetimes stay as ISO strings on the wire.
      expect(new Date(message.timestamp).toISOString()).toBe('2024-01-01T00:00:00.000Z');
    });

    it('should allow client-only fields', () => {
      const message: Message = {
        id: 'msg-123',
        sessionId: 'session-456',
        role: 'assistant',
        content: 'How are you feeling today?',
        timestamp: '2024-01-01T00:00:00Z',
      };

      expect(message.id).toBe('msg-123');
      expect(message.sessionId).toBe('session-456');
    });
  });

  describe('Session Type', () => {
    it('should support session with transcript', () => {
      const session: Session = {
        session_id: 'session-123',
        user_id: 'user-123',
        timestamp: '2024-01-01T00:00:00Z',
        transcript: [
          {
            role: 'user',
            content: 'I feel anxious',
            timestamp: '2024-01-01T00:00:00Z',
          },
          {
            role: 'assistant',
            content: 'Tell me more about that',
            timestamp: '2024-01-01T00:05:00Z',
          },
        ],
        topics: [
          {
            name: 'anxiety',
            status: 'pending',
          },
        ],
        psychological_summary: null,
        dominant_affects: [],
        key_themes: [],
        notable_interactions: null,
        interpretations: null,
        patient_reactions: null,
        enriched: false,
      };

      expect(session.transcript).toHaveLength(2);
      expect(session.topics).toHaveLength(1);
    });

    it('should allow client-only session fields', () => {
      const session: Session = {
        session_id: 'session-456',
        user_id: 'user-456',
        timestamp: '2024-01-02T00:00:00Z',
        transcript: [],
        topics: [],
        psychological_summary: null,
        dominant_affects: [],
        key_themes: [],
        notable_interactions: null,
        interpretations: null,
        patient_reactions: null,
        enriched: false,
        agentType: 'PSYCHOANALYST' as AgentType,
        therapyStyle: 'freud' as TherapyStyle,
        status: 'ACTIVE' as SessionStatus,
        startTime: new Date(),
        endTime: new Date(),
        metadata: { sessionNumber: 5 },
      };

      expect(session.agentType).toBe('PSYCHOANALYST');
      expect(session.therapyStyle).toBe('freud');
      expect(session.status).toBe('ACTIVE');
      expect(session.metadata).toEqual({ sessionNumber: 5 });
    });
  });

  describe('TherapyPlan Type', () => {
    it('should support basic plan structure', () => {
      const plan: TherapyPlan = {
        plan_id: 'plan-123',
        user_id: 'user-123',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
        version: 1,
        selected_therapy_style: 'freud',
        plan_details: {},
        initial_goals: ['goal'],
        current_progress: 'Baseline',
        planned_interventions: ['intervention'],
        status: 'active',
        session_briefing: null,
      };

      expect(plan.plan_id).toBeDefined();
      expect(plan.user_id).toBeDefined();
    });

    it('should allow optional plan fields', () => {
      const plan: TherapyPlan = {
        plan_id: 'plan-456',
        user_id: 'user-456',
        selected_therapy_style: 'jung',
        sessionCount: 10,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
        plan_details: {
          approach: 'analytical',
          focus: 'dreams',
        },
        initial_goals: ['Reduce anxiety', 'Improve sleep'],
        current_progress: 'Progressing',
        planned_interventions: ['Technique A', 'Technique B'],
        status: 'active',
        version: 2,
        session_briefing: null,
      };

      expect(plan.initial_goals).toHaveLength(2);
      expect(plan.sessionCount).toBe(10);
      expect(plan.plan_details).toBeDefined();
    });
  });

  describe('Topic Type', () => {
    it('should support topic structure', () => {
      const topic: Topic = {
        name: 'anxiety',
        status: 'pending',
      };

      expect(topic.name).toBe('anxiety');
      expect(topic.status).toBe('pending');
    });

    it('should allow different topic statuses', () => {
      const statuses = ['pending', 'covered', 'partially_covered'];

      statuses.forEach(status => {
        const topic: Topic = {
          name: 'test-topic',
          status,
        };

        expect(topic.status).toBe(status);
      });
    });
  });

  describe('WorkflowNextAction Type', () => {
    it('should support required action payloads', () => {
      const action: WorkflowNextAction = {
        user_id: 'user-1',
        workflow_state: 'intake_in_progress',
        required_action: 'start_intake',
        required_fields: [],
        defaults: null,
        prompt: 'Continue your intake session.',
        blocking: false,
        timestamp: new Date().toISOString(),
      };

      expect(action.required_action).toBe('start_intake');
      expect(action.workflow_state).toBe('intake_in_progress');
    });
  });

  describe('Client-Only Enums', () => {
    it('should support AgentType enum', () => {
      const types: AgentType[] = [
        'INTAKE' as AgentType,
        'ASSESSMENT' as AgentType,
        'PSYCHOANALYST' as AgentType,
        'PLANNING' as AgentType,
        'REFLECTION' as AgentType,
      ];

      types.forEach(type => {
        expect(typeof type).toBe('string');
      });
    });

    it('should support TherapyStyle enum', () => {
      const styles: TherapyStyle[] = [
        'freud' as TherapyStyle,
        'jung' as TherapyStyle,
        'cbt' as TherapyStyle,
      ];

      styles.forEach(style => {
        expect(typeof style).toBe('string');
      });
    });

    it('should support SessionStatus enum', () => {
      const statuses: SessionStatus[] = [
        'ACTIVE' as SessionStatus,
        'COMPLETED' as SessionStatus,
        'PAUSED' as SessionStatus,
      ];

      statuses.forEach(status => {
        expect(typeof status).toBe('string');
      });
    });
  });

  describe('Type Compatibility', () => {
    it('should allow User objects to be created from API responses', () => {
      // Simulating API response with backend field names
      const apiResponse = {
        user_id: 'user-api-123',
        name: 'API User',
        status: 'THERAPY_IN_PROGRESS' as UserStatus,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
      };

      // Directly assign to frontend User type (no conversion needed)
      const user: User = apiResponse;

      expect(user.user_id).toBe('user-api-123');
      expect(user.name).toBe('API User');
    });

    it('should maintain type safety with nested objects', () => {
      const session: Session = {
        session_id: 'nested-test',
        user_id: 'user-nested',
        timestamp: '2024-01-01T00:00:00Z',
        transcript: [
          {
            role: 'user',
            content: 'Test message',
            timestamp: '2024-01-01T00:00:00Z',
            id: 'msg-nested',
          },
        ],
        topics: [
          {
            name: 'nested-topic',
            status: 'pending',
          },
        ],
        psychological_summary: null,
        dominant_affects: [],
        key_themes: [],
        notable_interactions: null,
        interpretations: null,
        patient_reactions: null,
        enriched: false,
      };

      expect(session.transcript?.[0].id).toBe('msg-nested');
      expect(session.topics?.[0].name).toBe('nested-topic');
    });

    it('should handle Date types correctly', () => {
      const now = new Date();
      const session: Session = {
        session_id: 'date-session',
        user_id: 'user-date',
        timestamp: '2024-01-01T00:00:00Z',
        transcript: [],
        topics: [],
        psychological_summary: null,
        dominant_affects: [],
        key_themes: [],
        notable_interactions: null,
        interpretations: null,
        patient_reactions: null,
        enriched: false,
        startTime: now,
        endTime: now,
      };

      expect(session.startTime).toBeInstanceOf(Date);
      expect(session.endTime).toBeInstanceOf(Date);
    });
  });

  describe('Type Inference', () => {
    it('should infer correct types from object literals', () => {
      const user = {
        user_id: 'infer-test',
        name: 'Infer Test',
        status: 'PROFILE_ONLY' as UserStatus,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
      };

      // This should type check correctly
      const typedUser: User = user;

      expect(typedUser.user_id).toBe('infer-test');
    });

    it('should support partial updates', () => {
      const partialUser: Partial<User> = {
        name: 'Updated Name',
        profession: 'New Profession',
      };

      expect(partialUser.name).toBe('Updated Name');
      expect(partialUser.user_id).toBeUndefined();
    });

    it('should support Pick and Omit utility types', () => {
      type UserIdentity = Pick<User, 'user_id' | 'name'>;

      const identity: UserIdentity = {
        user_id: 'pick-test',
        name: 'Pick Test',
      };

      expect(identity.user_id).toBeDefined();
      expect((identity as any).created_at).toBeUndefined();
    });
  });
});
