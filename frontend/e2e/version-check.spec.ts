import { test, expect } from '@playwright/test';

/**
 * E2E tests for version checking UI
 */

test.describe('Version Check', () => {
  test('performs compatibility check and does not block login routing', async ({ page }) => {
    const versionCheckRequest = page.waitForRequest((req) => {
      return req.method() === 'POST' && req.url().includes('/api/version/check');
    });

    const versionCheckResponse = page.waitForResponse((resp) => {
      return resp.request().method() === 'POST' && resp.url().includes('/api/version/check');
    });

    await page.goto('/');

    await versionCheckRequest;
    const response = await versionCheckResponse;
    expect(response.ok()).toBeTruthy();

    // Unauthenticated users end up on the login page after the version check completes.
    await expect(page).toHaveURL(/\/login/, { timeout: 15000 });
    await expect(page.getByRole('button', { name: /^sign in$/i })).toBeVisible();

    // A compatible backend must not show an incompatibility dialog.
    await expect(
      page.getByRole('dialog', { name: /version compatibility error/i })
    ).not.toBeVisible();
  });
});
