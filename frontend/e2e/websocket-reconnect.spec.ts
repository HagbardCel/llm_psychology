import { test, expect } from '@playwright/test';

test.describe('WebSocket Reconnect', () => {
  test('disconnect triggers reconnect UI state and restores session readiness', async ({ page, context }) => {
    await page.goto('/dashboard');

    await page.waitForURL(/\/(dashboard|profile)/, { timeout: 15000 });
    if (page.url().includes('/dashboard')) {
      const continueButton = page.getByRole('button', { name: /^continue$/i });
      await expect(continueButton).toBeEnabled({ timeout: 15000 });
      await continueButton.click();
    }

    await page.waitForURL(/\/profile/, { timeout: 15000 });

    await page.getByRole('button', { name: /create new profile/i }).click({ timeout: 15000 });
    await page.getByRole('textbox', { name: /name/i }).fill('Reconnect User Updated');
    await page.getByRole('button', { name: /save changes|continue/i }).click();

    await page.waitForURL(/\/intake/, { timeout: 20000 });

    await expect(page.getByText('Connected', { exact: true })).toBeVisible({ timeout: 20000 });
    const input = page.getByRole('textbox');
    await expect(input).toBeEnabled({ timeout: 20000 });

    await context.setOffline(true);
    await expect(page.getByText(/connecting\.\.\.|disconnected/i)).toBeVisible({ timeout: 20000 });

    await context.setOffline(false);
    await expect(page.getByText('Connected', { exact: true })).toBeVisible({ timeout: 20000 });
    await expect(input).toBeEnabled({ timeout: 20000 });
  });
});
