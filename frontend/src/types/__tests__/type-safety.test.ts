/**
 * Integration tests for type safety across the application
 */

import { describe, it, expect } from '@jest/globals';
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
        id: 'user-123',
        name: 'Test User',
        status: 'PROFILE_ONLY',
        createdAt: new Date(),
        updatedAt: new Date(),
      };

      expect(user.id).toBeDefined();
      expect(user.name).toBeDefined();
      expect(user.status).toBeDefined();
    });

    it('should allow optional fields', () => {
      const user: User = {
        id: 'user-123',
        name: 'Test User',
        email: 'test@example.com',
        birthdate: new Date('1990-01-01'),
        profession: 'Engineer',
        status: 'PROFILE_ONLY',
        createdAt: new Date(),
        updatedAt: new Date(),
        lastActiveAt: new Date(),
      };

      expect(user.email).toBe('test@example.com');
      expect(user.lastActiveAt).toBeDefined();
    });

    it('should enforce UserStatus enum values', () => {
      const validStatuses: UserStatus[] = [
        'PROFILE_ONLY',
        'INTAKE_IN_PROGRESS',
        'INTAKE_COMPLETE',
        'ASSESSMENT_IN_PROGRESS',
        'ASSESSMENT_COMPLETE',
        'THERAPY_IN_PROGRESS',
        'REFLECTION_IN_PROGRESS',
        'PLAN_COMPLETE',
      ];

      validStatuses.forEach(status => {
        const user: User = {
          id: 'test',
          name: 'Test',
          status,
          createdAt: new Date(),
          updatedAt: new Date(),
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
        timestamp: new Date(),
      };

      expect(message.role).toBe('user');
      expect(message.content).toBe('Hello, therapist');
      expect(message.timestamp).toBeInstanceOf(Date);
    });

    it('should allow client-only fields', () => {
      const message: Message = {
        id: 'msg-123',
        sessionId: 'session-456',
        role: 'assistant',
        content: 'How are you feeling today?',
        timestamp: new Date(),
      };

      expect(message.id).toBe('msg-123');
      expect(message.sessionId).toBe('session-456');
    });
  });

  describe('Session Type', () => {
    it('should support session with transcript', () => {
      const session: Session = {
        id: 'session-123',
        userId: 'user-123',
        timestamp: new Date(),
        transcript: [
          {
            role: 'user',
            content: 'I feel anxious',
            timestamp: new Date(),
          },
          {
            role: 'assistant',
            content: 'Tell me more about that',
            timestamp: new Date(),
          },
        ],
        topics: [
          {
            name: 'anxiety',
            status: 'pending',
          },
        ],
      };

      expect(session.transcript).toHaveLength(2);
      expect(session.topics).toHaveLength(1);
    });

    it('should allow client-only session fields', () => {
      const session: Session = {
        id: 'session-456',
        userId: 'user-456',
        timestamp: new Date(),
        transcript: [],
        topics: [],
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
        id: 'plan-123',
        userId: 'user-123',
        createdAt: new Date(),
        updatedAt: new Date(),
      };

      expect(plan.id).toBeDefined();
      expect(plan.userId).toBeDefined();
    });

    it('should allow optional plan fields', () => {
      const plan: TherapyPlan = {
        id: 'plan-456',
        userId: 'user-456',
        therapyStyle: 'jung',
        goals: ['Reduce anxiety', 'Improve sleep'],
        sessionCount: 10,
        createdAt: new Date(),
        updatedAt: new Date(),
        planDetails: {
          approach: 'analytical',
          focus: 'dreams',
        },
        version: 1,
      };

      expect(plan.goals).toHaveLength(2);
      expect(plan.sessionCount).toBe(10);
      expect(plan.planDetails).toBeDefined();
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
    it('should support navigate action', () => {
      const action: WorkflowNextAction = {
        action: 'navigate',
        route: '/intake',
        reason: 'User needs intake assessment',
      };

      expect(action.action).toBe('navigate');
      expect(action.route).toBe('/intake');
    });

    it('should support display action', () => {
      const action: WorkflowNextAction = {
        action: 'display',
        display: {
          title: 'Welcome',
          description: 'Please complete your profile',
        },
      };

      expect(action.action).toBe('display');
      expect(action.display?.title).toBe('Welcome');
    });

    it('should support error action', () => {
      const action: WorkflowNextAction = {
        action: 'error',
        error: 'User not found',
      };

      expect(action.action).toBe('error');
      expect(action.error).toBe('User not found');
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
        userid: 'user-api-123',
        name: 'API User',
        status: 'THERAPY_IN_PROGRESS' as UserStatus,
        createdAt: new Date(),
        updatedAt: new Date(),
      };

      // Converting to frontend User type
      const user: User = {
        ...apiResponse,
        id: apiResponse.userid,
      };

      expect(user.id).toBe('user-api-123');
      expect(user.name).toBe('API User');
    });

    it('should maintain type safety with nested objects', () => {
      const session: Session = {
        id: 'nested-test',
        userId: 'user-nested',
        timestamp: new Date(),
        transcript: [
          {
            role: 'user',
            content: 'Test message',
            timestamp: new Date(),
            id: 'msg-nested',
          },
        ],
        topics: [
          {
            name: 'nested-topic',
            status: 'pending',
          },
        ],
      };

      expect(session.transcript[0].id).toBe('msg-nested');
      expect(session.topics[0].name).toBe('nested-topic');
    });

    it('should handle Date types correctly', () => {
      const now = new Date();
      const user: User = {
        id: 'date-test',
        name: 'Date Test',
        birthdate: now,
        status: 'PROFILE_ONLY',
        createdAt: now,
        updatedAt: now,
        lastActiveAt: now,
      };

      expect(user.birthdate).toBeInstanceOf(Date);
      expect(user.createdAt).toBeInstanceOf(Date);
      expect(user.lastActiveAt).toBeInstanceOf(Date);
    });
  });

  describe('Type Inference', () => {
    it('should infer correct types from object literals', () => {
      const user = {
        id: 'infer-test',
        name: 'Infer Test',
        status: 'PROFILE_ONLY' as UserStatus,
        createdAt: new Date(),
        updatedAt: new Date(),
      };

      // This should type check correctly
      const typedUser: User = user;

      expect(typedUser.id).toBe('infer-test');
    });

    it('should support partial updates', () => {
      const partialUser: Partial<User> = {
        name: 'Updated Name',
        profession: 'New Profession',
      };

      expect(partialUser.name).toBe('Updated Name');
      expect(partialUser.id).toBeUndefined();
    });

    it('should support Pick and Omit utility types', () => {
      type UserIdentity = Pick<User, 'id' | 'name'>;

      const identity: UserIdentity = {
        id: 'pick-test',
        name: 'Pick Test',
      };

      expect(identity.id).toBeDefined();
      expect((identity as any).email).toBeUndefined();
    });
  });
});
