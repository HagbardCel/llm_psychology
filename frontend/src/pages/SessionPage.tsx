import { useParams } from 'react-router-dom';
import { TherapySession } from '../components/TherapySession';

export function SessionPage() {
  const { sessionId } = useParams<{ sessionId?: string }>();
  
  return <TherapySession sessionId={sessionId} />;
}