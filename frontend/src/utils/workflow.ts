import type { RequiredWorkflowAction } from '../types';

export function routeForRequiredAction(action?: RequiredWorkflowAction | null): string | null {
  switch (action) {
    case 'complete_profile':
      return '/profile';
    case 'start_intake':
      return '/intake';
    case 'select_therapy_style':
      return '/assessment';
    case 'start_therapy':
      return '/assessment';
    case 'continue_therapy':
      return '/session/new';
    case 'retry_plan_update':
    case 'wait':
    default:
      return null;
  }
}

export function labelForRequiredAction(action?: RequiredWorkflowAction | null): string {
  switch (action) {
    case 'complete_profile':
      return 'Complete Profile';
    case 'start_intake':
      return 'Start Intake';
    case 'select_therapy_style':
      return 'Choose Therapy Style';
    case 'start_therapy':
      return 'Start Therapy';
    case 'continue_therapy':
      return 'Continue Therapy';
    case 'retry_plan_update':
      return 'Retry Plan Update';
    case 'wait':
      return 'Please Wait';
    default:
      return 'Continue';
  }
}
