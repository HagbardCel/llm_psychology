import { Stepper, Step, StepLabel } from '@mui/material';
import { UserStatus } from '../../types';

export interface WorkflowStepperProps {
  currentStatus: UserStatus;
  orientation?: 'horizontal' | 'vertical';
  onStepClick?: (route: string) => void;
}

interface WorkflowStep {
  label: string;
  status: UserStatus;
  route: string;
}

const WORKFLOW_STEPS: WorkflowStep[] = [
  { label: 'Profile', status: UserStatus.PROFILE_ONLY, route: '/profile' },
  { label: 'Intake', status: UserStatus.INTAKE_IN_PROGRESS, route: '/intake' },
  {
    label: 'Assessment',
    status: UserStatus.ASSESSMENT_IN_PROGRESS,
    route: '/assessment'
  },
  { label: 'Therapy', status: UserStatus.INITIAL_PLAN_COMPLETE, route: '/session/new' }
];

/**
 * WorkflowStepper displays the user's progress through the therapy workflow.
 * Steps: Profile → Intake → Assessment → Therapy
 *
 * @example
 * ```tsx
 * <WorkflowStepper
 *   currentStatus={user.status}
 *   onStepClick={(route) => navigate(route)}
 * />
 * ```
 */
export function WorkflowStepper({
  currentStatus,
  orientation = 'horizontal',
  onStepClick
}: WorkflowStepperProps) {
  const activeStep = getActiveStepIndex(currentStatus);

  return (
    <Stepper activeStep={activeStep} orientation={orientation}>
      {WORKFLOW_STEPS.map((step, index) => (
        <Step key={step.label} completed={index < activeStep}>
          <StepLabel
            onClick={() => onStepClick?.(step.route)}
            sx={{ cursor: onStepClick ? 'pointer' : 'default' }}
          >
            {step.label}
          </StepLabel>
        </Step>
      ))}
    </Stepper>
  );
}

/**
 * Maps UserStatus to step index in the workflow.
 */
function getActiveStepIndex(status: UserStatus): number {
  const statusOrder = [
    UserStatus.PROFILE_ONLY,
    UserStatus.INTAKE_IN_PROGRESS,
    UserStatus.INTAKE_COMPLETE,
    UserStatus.ASSESSMENT_IN_PROGRESS,
    UserStatus.ASSESSMENT_COMPLETE,
    UserStatus.INITIAL_PLAN_COMPLETE,
    UserStatus.PLAN_UPDATE_COMPLETE,
    UserStatus.THERAPY_IN_PROGRESS,
    UserStatus.PLAN_UPDATE_IN_PROGRESS,
    UserStatus.REFLECTION_IN_PROGRESS
  ];

  const index = statusOrder.indexOf(status);

  // Map status to step index (0=Profile, 1=Intake, 2=Assessment, 3=Therapy)
  if (index <= 0) return 0; // Profile
  if (index <= 2) return 1; // Intake (in progress or complete)
  if (index <= 4) return 2; // Assessment (in progress or complete)
  return 3; // Therapy and beyond
}
