import { useState, FormEvent, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Alert,
  Snackbar,
  CircularProgress,
  Box,
  Divider,
  List,
  ListItemButton,
  ListItemText,
  Typography,
} from '@mui/material';
import { PageContainer, FormField } from '../components/shared';
import { useAppContext } from '../contexts/AppContext';
import {
  useCreateUserProfile,
  useLoginUserProfile,
  useRegisterUserProfile,
  useUserProfile,
  useUserProfiles,
  useUpdateUserProfile,
} from '../hooks/useUserProfile';
import { useWorkflowNextAction } from '../hooks/useWorkflowNavigation';
import { routeForRequiredAction } from '../utils/workflow';
import type { RequiredWorkflowAction } from '../types';

/**
 * ProfilePage allows users to create or update their profile.
 * Refactored to use React Query for server state management.
 */
export function ProfilePage() {
  const {
    currentUserId: userId,
    currentSessionId: sessionId,
    setCurrentUserId,
    setCurrentSessionId,
  } =
    useAppContext();
  const navigate = useNavigate();

  // Fetch user data from backend via React Query
  const { data: user, isLoading: userLoading } = useUserProfile(
    userId || '',
    sessionId || ''
  );

  // Mutation for updating profile
  const { mutateAsync: createProfile, isPending: isCreating } = useCreateUserProfile();
  const { mutateAsync: registerProfile, isPending: isRegistering } = useRegisterUserProfile();
  const { mutateAsync: loginProfile, isPending: isLoggingIn } = useLoginUserProfile();
  const { mutateAsync: updateProfile, isPending: isUpdating } = useUpdateUserProfile();
  const isPending = isCreating || isUpdating || isRegistering || isLoggingIn;
  const { data: profiles = [], isLoading: profilesLoading } = useUserProfiles();

  // Get next action for navigation
  const { data: nextAction, refetch: refetchNextAction } = useWorkflowNextAction(
    userId || '',
    sessionId || '',
    '/profile'
  );

  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [creatingNew, setCreatingNew] = useState(false);

  const [formData, setFormData] = useState({
    name: '',
    data_of_birth: '',
    profession: '',
    primary_language: 'English',
  });

  // Initialize form with user data when loaded
  useEffect(() => {
    if (user) {
      setFormData({
        name: user.name || '',
        data_of_birth: user.data_of_birth || '',
        profession: user.profession || '',
        primary_language: user.primary_language || 'English',
      });
    }
  }, [user]);

  const [errors, setErrors] = useState<Record<string, string>>({});

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!formData.name.trim()) {
      newErrors.name = 'Name is required';
    }
    if (!formData.primary_language.trim()) {
      newErrors.primary_language = 'Primary language is required';
    }

    if (formData.data_of_birth) {
      const date = new Date(formData.data_of_birth);
      if (isNaN(date.getTime())) {
        newErrors.data_of_birth = 'Invalid date format';
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
      let nextActionOverride = nextAction;
      const payload = {
        user_id: userId || `user_${Date.now()}`,
        name: formData.name.trim(),
        data_of_birth: formData.data_of_birth || undefined,
        profession: formData.profession || undefined,
        primary_language: formData.primary_language.trim(),
      };

      if (user) {
        if (!sessionId) {
          setError('Session is required to update your profile. Please reconnect.');
          return;
        }
        await updateProfile({ ...payload, session_id: sessionId });
      } else if (!sessionId) {
        const response = await registerProfile(payload);
        setCurrentSessionId(response.session.session_id);
        nextActionOverride = response.workflow_next_action;
      } else {
        await createProfile({ ...payload, session_id: sessionId });
      }

      setSuccess(true);

      // Backend-driven navigation - check next action
      const refreshed = sessionId ? await refetchNextAction() : null;
      const next = refreshed?.data || nextActionOverride;
      const targetRoute = routeForRequiredAction(next?.required_action);
      if (targetRoute && targetRoute !== '/profile') {
        setTimeout(() => navigate(targetRoute), 1500);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save profile');
      console.error('Profile save error:', err);
    }
  };

  const navigateFromAction = (requiredAction?: RequiredWorkflowAction | null) => {
    const targetRoute = routeForRequiredAction(requiredAction);
    if (targetRoute && targetRoute !== '/profile') {
      setTimeout(() => navigate(targetRoute), 300);
    }
  };

  const handleLogin = async (selectedUserId: string) => {
    setError(null);
    try {
      const response = await loginProfile(selectedUserId);
      setCurrentUserId(selectedUserId);
      setCurrentSessionId(response.session.session_id);
      setSuccess(true);
      navigateFromAction(response.workflow_next_action?.required_action);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to log in');
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
      title={user ? 'Edit Profile' : 'Profile'}
      subtitle={
        user
          ? 'Update your information'
          : 'Select an existing profile or create a new one'
      }
      maxWidth="sm"
    >
      {!user && !creatingNew && (
        <Box sx={{ mb: 3 }}>
          {profilesLoading ? (
            <CircularProgress size={24} />
          ) : profiles.length > 0 ? (
            <List aria-label="Existing profiles" sx={{ mb: 2 }}>
              {profiles.map((profile) => (
                <ListItemButton
                  key={profile.user_id}
                  onClick={() => handleLogin(profile.user_id)}
                  disabled={isPending}
                  sx={{ px: 0 }}
                >
                  <ListItemText
                    primary={profile.name}
                    secondary={`${profile.status} - ${profile.primary_language}`}
                  />
                </ListItemButton>
              ))}
            </List>
          ) : (
            <Typography color="text.secondary" sx={{ mb: 2 }}>
              No existing profiles found.
            </Typography>
          )}
          <Button
            variant="outlined"
            fullWidth
            onClick={() => setCreatingNew(true)}
            disabled={isPending}
          >
            Create New Profile
          </Button>
          <Divider sx={{ my: 3 }} />
        </Box>
      )}

      {error && !creatingNew && !user && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {(user || creatingNew) && (
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
          label="Primary Language"
          value={formData.primary_language}
          onChange={(value) => setFormData({ ...formData, primary_language: value })}
          error={errors.primary_language}
          required
          disabled={isPending}
        />

        <FormField
          label="Birthdate"
          type="date"
          value={formData.data_of_birth}
          onChange={(value) => setFormData({ ...formData, data_of_birth: value })}
          error={errors.data_of_birth}
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
      )}

      <Snackbar
        open={success}
        autoHideDuration={6000}
        onClose={() => setSuccess(false)}
        message="Profile saved successfully"
      />
    </PageContainer>
  );
}
