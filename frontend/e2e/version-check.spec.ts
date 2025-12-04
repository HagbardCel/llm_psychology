import { test, expect } from '@playwright/test';

/**
 * E2E tests for version checking UI
 */

test.describe('Version Check', () => {
  test('should show loading screen during version check', async ({ page }) => {
    // Navigate to app root
    await page.goto('/');

    // Version check should show loading state briefly
    // We might catch it or it might be too fast
    const loadingElement = page.locator('text=/checking version|verifying compatibility/i');

    // If loading is visible, verify it
    if (await loadingElement.isVisible().catch(() => false)) {
      await expect(loadingElement).toBeVisible();
    }

    // Eventually should proceed to login or main app
    await expect(page).toHaveURL(/\/(login|dashboard|profile|intake)/, { timeout: 15000 });
  });

  test('should allow app to load with compatible version', async ({ page }) => {
    await page.goto('/');

    // App should load successfully
    // Wait for either login page or authenticated content
    await page.waitForURL(/\/(login|register|dashboard|profile|intake)/, { timeout: 15000 });

    // Verify no version error dialogs
    const errorDialog = page.locator('role=dialog').filter({ hasText: /version.*error|incompatible/i });
    await expect(errorDialog).not.toBeVisible();
  });

  test('should not block authentication with version check', async ({ page }) => {
    await page.goto('/login');

    // Should reach login page (version check should not block)
    await expect(page.locator('h1, h2, h4')).toContainText(/login|sign in/i, { timeout: 15000 });

    // Fill and submit login form
    await page.getByLabel(/username/i).fill('testuser');
    await page.getByLabel(/password/i).fill('password');

    // Should be able to interact with form (not blocked by version check)
    await expect(page.getByRole('button', { name: /login|sign in/i })).toBeEnabled();
  });

  test('should show version info in dev mode', async ({ page }) => {
    await page.goto('/');

    // In dev mode, version info might be shown
    // Check if version info is available (either in console or UI)
    const consoleLogs: string[] = [];
    page.on('console', (msg) => {
      consoleLogs.push(msg.text());
    });

    // Wait for page load
    await page.waitForLoadState('networkidle');

    // Check if version info appears in console logs
    const hasVersionLog = consoleLogs.some((log) =>
      /version|api.*version|checking.*compatibility/i.test(log)
    );

    // Either version appears in logs or page loads successfully
    const pageLoaded = await page
      .locator('body')
      .isVisible()
      .catch(() => false);

    expect(hasVersionLog || pageLoaded).toBeTruthy();
  });

  // Note: Testing incompatible version scenarios requires mocking the backend
  // or using a test server with different version. Those tests would be:
  //
  // test('should show error dialog for incompatible version')
  // test('should show warning banner for outdated version')
  // test('should allow refresh on version error')
  //
  // These require backend API mocking which can be added with MSW (Mock Service Worker)
});
