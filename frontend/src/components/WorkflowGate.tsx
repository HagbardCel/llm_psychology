import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useCurrentUserId } from '../contexts/AppContext';
import { useWorkflowNextAction } from '../hooks/useWorkflowNavigation';

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

  const shouldEnforce = !!userId && WORKFLOW_ROUTES.has(location.pathname);
  const { data: nextAction } = useWorkflowNextAction(
    userId || '',
    location.pathname,
    { enabled: shouldEnforce }
  );

  useEffect(() => {
    if (!shouldEnforce) return;
    if (!nextAction) return;

    if (
      nextAction.action === 'navigate' &&
      nextAction.route &&
      nextAction.route !== location.pathname
    ) {
      navigate(nextAction.route, { replace: true });
    }
  }, [shouldEnforce, nextAction, navigate, location.pathname]);

  return null;
}
