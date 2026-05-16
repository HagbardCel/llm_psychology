import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useCurrentSessionId, useCurrentUserId } from '../contexts/AppContext';
import { useWorkflowNextAction } from '../hooks/useWorkflowNavigation';
import { routeForRequiredAction } from '../utils/workflow';

const WORKFLOW_ROUTES = new Set([
  '/profile',
  '/intake',
  '/assessment',
  '/dashboard',
  '/session/new',
]);

/**
 * WorkflowGate keeps the user on the backend-defined workflow route.
 * When a user deep-links to the wrong step, the backend's next-action API
 * instructs us where to navigate next and the gate performs the redirect.
 */
export function WorkflowGate() {
  const location = useLocation();
  const navigate = useNavigate();
  const userId = useCurrentUserId();
  const sessionId = useCurrentSessionId();

  const shouldEnforce = !!userId && !!sessionId && WORKFLOW_ROUTES.has(location.pathname);
  const { data: nextAction } = useWorkflowNextAction(
    userId || '',
    sessionId || '',
    location.pathname,
    { enabled: shouldEnforce }
  );

  useEffect(() => {
    if (!shouldEnforce) return;
    if (!nextAction) return;

    const targetRoute = routeForRequiredAction(nextAction.required_action);
    if (targetRoute && targetRoute !== location.pathname) {
      navigate(targetRoute, { replace: true });
    }
  }, [shouldEnforce, nextAction, navigate, location.pathname]);

  return null;
}
