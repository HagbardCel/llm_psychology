import { useParams } from 'react-router';
import { TherapySession } from '../components/TherapySession';

export function SessionPage() {
  const { sessionId } = useParams<{ sessionId?: string }>();
  
  return <TherapySession sessionId={sessionId} />;
}