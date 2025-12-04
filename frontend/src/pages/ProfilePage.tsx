import { useState, FormEvent, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Alert, Snackbar, CircularProgress } from '@mui/material';
import { PageContainer, FormField } from '../components/shared';
import { useCurrentUserId } from '../contexts/AppContext';
import { useUserProfile, useUpdateUserProfile } from '../hooks/useUserProfile';
import { useWorkflowNextAction } from '../hooks/useWorkflowNavigation';

/**
 * ProfilePage allows users to create or update their profile.
 * Refactored to use React Query for server state management.
 */
export function ProfilePage() {
  const userId = useCurrentUserId();
  const navigate = useNavigate();

  // Fetch user data from backend via React Query
  const { data: user, isLoading: userLoading } = useUserProfile(userId || '');

  // Mutation for updating profile
  const { mutateAsync: updateProfile, isPending } = useUpdateUserProfile();

  // Get next action for navigation
  const { data: nextAction } = useWorkflowNextAction(userId || '', '/profile');

  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const [formData, setFormData] = useState({
    name: '',
    birthdate: '',
    profession: ''
  });

  // Initialize form with user data when loaded
  useEffect(() => {
    if (user) {
      setFormData({
        name: user.name || '',
        birthdate: user.birthdate || '',
        profession: user.profession || ''
      });
    }
  }, [user]);

  const [errors, setErrors] = useState<Record<string, string>>({});

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!formData.name.trim()) {
      newErrors.name = 'Name is required';
    }

    if (formData.birthdate) {
      const date = new Date(formData.birthdate);
      if (isNaN(date.getTime())) {
        newErrors.birthdate = 'Invalid date format';
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    if (!validate()) {
      return;
    }

    setError(null);

    try {
      await updateProfile({
        user_id: userId || `user_${Date.now()}`,
        ...formData
      });

      setSuccess(true);

      // Backend-driven navigation - check next action
      if (nextAction?.route && nextAction.route !== '/profile') {
        setTimeout(() => navigate(nextAction.route!), 1500);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save profile');
      console.error('Profile save error:', err);
    }
  };

  if (userLoading) {
    return (
      <PageContainer title="Loading Profile..." maxWidth="sm">
        <CircularProgress />
      </PageContainer>
    );
  }

  return (
    <PageContainer
      title={user ? 'Edit Profile' : 'Welcome!'}
      subtitle={
        user
          ? 'Update your information'
          : 'Tell us about yourself to get started'
      }
      maxWidth="sm"
    >
      <form onSubmit={handleSubmit}>
        <FormField
          label="Name"
          value={formData.name}
          onChange={(value) => setFormData({ ...formData, name: value })}
          error={errors.name}
          required
          disabled={isPending}
        />

        <FormField
          label="Birthdate"
          type="date"
          value={formData.birthdate}
          onChange={(value) => setFormData({ ...formData, birthdate: value })}
          error={errors.birthdate}
          disabled={isPending}
          helperText="Optional - helps us personalize your experience"
        />

        <FormField
          label="Profession"
          value={formData.profession}
          onChange={(value) => setFormData({ ...formData, profession: value })}
          disabled={isPending}
          helperText="Optional"
        />

        {error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {error}
          </Alert>
        )}

        <Button
          type="submit"
          variant="contained"
          fullWidth
          size="large"
          disabled={isPending}
          sx={{ mt: 3 }}
        >
          {isPending ? (
            <CircularProgress size={24} />
          ) : user ? (
            'Save Changes'
          ) : (
            'Continue'
          )}
        </Button>
      </form>

      <Snackbar
        open={success}
        autoHideDuration={6000}
        onClose={() => setSuccess(false)}
        message="Profile saved successfully"
      />
    </PageContainer>
  );
}
