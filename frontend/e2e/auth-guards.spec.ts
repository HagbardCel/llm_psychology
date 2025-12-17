import { test, expect } from '@playwright/test';

test.describe('Auth Guards', () => {
  test('protected API endpoints reject missing token', async ({ request }) => {
    const response = await request.get('/api/user/profile?user_id=test-user');
    expect(response.status()).toBe(401);
  });
});

