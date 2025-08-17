export interface User {
  id: string;
  name: string;
  email?: string;
  status: UserStatus;
  createdAt: Date;
  lastActiveAt: Date;
}

export enum UserStatus {
  PROFILE_ONLY = 'PROFILE_ONLY',
  INTAKE_COMPLETE = 'INTAKE_COMPLETE', 
  PLAN_COMPLETE = 'PLAN_COMPLETE'
}

export interface Message {
  id: string;
  content: string;
  sender: 'user' | 'agent';
  timestamp: Date;
  sessionId: string;
}

export interface Session {
  id: string;
  userId: string;
  agentType: AgentType;
  therapyStyle?: TherapyStyle;
  status: SessionStatus;
  startTime: Date;
  endTime?: Date;
  messages: Message[];
  metadata?: Record<string, any>;
}

export enum AgentType {
  INTAKE = 'INTAKE',
  ASSESSMENT = 'ASSESSMENT',
  PSYCHOANALYST = 'PSYCHOANALYST',
  REFLECTION = 'REFLECTION'
}

export enum TherapyStyle {
  FREUD = 'freud',
  JUNG = 'jung',
  CBT = 'cbt'
}

export enum SessionStatus {
  ACTIVE = 'ACTIVE',
  COMPLETED = 'COMPLETED',
  PAUSED = 'PAUSED'
}

export interface TherapyPlan {
  id: string;
  userId: string;
  therapyStyle: TherapyStyle;
  goals: string[];
  sessionCount: number;
  createdAt: Date;
  updatedAt: Date;
}

export interface AppState {
  user: User | null;
  currentSession: Session | null;
  sessions: Session[];
  therapyPlan: TherapyPlan | null;
  isLoading: boolean;
  error: string | null;
}

export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

export interface LocalStorageData {
  user?: User;
  sessions?: Session[];
  therapyPlan?: TherapyPlan;
  preferences?: UserPreferences;
}

export interface UserPreferences {
  theme: 'light' | 'dark';
  notifications: boolean;
  autoSave: boolean;
  fontSize: 'small' | 'medium' | 'large';
}