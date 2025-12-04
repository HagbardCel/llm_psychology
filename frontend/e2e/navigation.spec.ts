import { test, expect } from '@playwright/test';

/**
 * E2E tests for navigation and routing
 */

test.describe('Navigation', () => {
  // Helper to register and login a user
  async function registerAndLogin(page, username, password, name) {
    await page.goto('/register');
    await page.getByLabel(/name|full name/i).fill(name);
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/^password$/i).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);
    await page.getByRole('button', { name: /register|sign up|create/i }).click();
    await page.waitForURL(/\/(dashboard|profile|intake)/, { timeout: 10000 });
  }

  test('should redirect unauthenticated user to login', async ({ page }) => {
    // Try to access protected route
    await page.goto('/dashboard');

    // Should redirect to login
    await expect(page).toHaveURL(/\/login/, { timeout: 5000 });
  });

  test('should allow navigation after authentication', async ({ page }) => {
    const timestamp = Date.now();
    await registerAndLogin(page, `navuser_${timestamp}`, 'NavPassword123!', 'Nav Test User');

    // Try to navigate to different pages
    // The actual routes depend on your app structure

    // Navigate to profile (if exists)
    await page.goto('/profile');
    await expect(page).toHaveURL(/\/profile/);

    // Navigate to dashboard (if exists)
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/dashboard/);

    // Navigate to settings (if exists)
    await page.goto('/settings');
    // Should either show settings or redirect to valid page
    await expect(page).toHaveURL(/\/(settings|dashboard|profile)/);
  });

  test('should persist authentication across page navigations', async ({ page }) => {
    const timestamp = Date.now();
    await registerAndLogin(page, `persistuser_${timestamp}`, 'PersistPassword123!', 'Persist User');

    // Navigate to different pages
    await page.goto('/profile');
    await expect(page).toHaveURL(/\/profile/);

    // Navigate to dashboard
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/dashboard/);

    // Reload page
    await page.reload();

    // Should still be authenticated (not redirected to login)
    await expect(page).not.toHaveURL(/\/login/);
  });

  test('should handle browser back/forward navigation', async ({ page }) => {
    const timestamp = Date.now();
    await registerAndLogin(page, `backfwduser_${timestamp}`, 'BackFwdPassword123!', 'BackFwd User');

    // Navigate to profile
    await page.goto('/profile');
    await expect(page).toHaveURL(/\/profile/);

    // Navigate to dashboard
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/dashboard/);

    // Go back
    await page.goBack();
    await expect(page).toHaveURL(/\/profile/);

    // Go forward
    await page.goForward();
    await expect(page).toHaveURL(/\/dashboard/);
  });

  test('should handle direct URL access for authenticated routes', async ({ page }) => {
    const timestamp = Date.now();
    await registerAndLogin(page, `directuser_${timestamp}`, 'DirectPassword123!', 'Direct User');

    // Directly access various routes
    const routes = ['/dashboard', '/profile', '/settings', '/history'];

    for (const route of routes) {
      await page.goto(route);
      // Should either show the page or redirect to a valid authenticated page
      // But should not redirect to login
      await expect(page).not.toHaveURL(/\/login/);
    }
  });

  test('should show navigation menu for authenticated users', async ({ page }) => {
    const timestamp = Date.now();
    await registerAndLogin(page, `menuuser_${timestamp}`, 'MenuPassword123!', 'Menu User');

    // Look for navigation elements (menu, drawer, navbar)
    const navigationElements = [
      page.getByRole('navigation'),
      page.getByRole('button', { name: /menu|navigation/i }),
      page.locator('nav'),
    ];

    // At least one navigation element should exist
    let foundNavigation = false;
    for (const element of navigationElements) {
      if (await element.isVisible().catch(() => false)) {
        foundNavigation = true;
        break;
      }
    }

    expect(foundNavigation).toBeTruthy();
  });

  test('should handle invalid routes gracefully', async ({ page }) => {
    await page.goto('/this-route-does-not-exist-12345');

    // Should either show 404 page or redirect to valid page
    // But should not crash or show blank page
    await expect(page.locator('body')).toBeVisible();

    // Should eventually settle on a valid page
    const url = page.url();
    expect(url).toMatch(/\/(login|404|dashboard|profile|not-found)/);
  });

  test('should navigate using menu/navigation links', async ({ page }) => {
    const timestamp = Date.now();
    await registerAndLogin(page, `linksuser_${timestamp}`, 'LinksPassword123!', 'Links User');

    // Wait for page to be fully loaded
    await page.waitForLoadState('networkidle');

    // Try to find and click navigation links
    // These selectors are generic - adapt to your actual app structure

    const possibleLinks = [
      { name: /dashboard/i, expectedUrl: /\/dashboard/ },
      { name: /profile/i, expectedUrl: /\/profile/ },
      { name: /settings/i, expectedUrl: /\/settings/ },
      { name: /history|sessions/i, expectedUrl: /\/(history|sessions)/ },
    ];

    for (const linkInfo of possibleLinks) {
      const link = page.getByRole('link', { name: linkInfo.name });

      if (await link.isVisible().catch(() => false)) {
        await link.click();
        await expect(page).toHaveURL(linkInfo.expectedUrl, { timeout: 3000 });
        break; // Successfully clicked and navigated
      }
    }
  });
});
