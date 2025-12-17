import { test, expect } from '@playwright/test';

test.describe('WebSocket Reconnect', () => {
  test('disconnect triggers reconnect UI state and restores session readiness', async ({ page, context }) => {
    const timestamp = Date.now();
    const username = `reconnect_${timestamp}`;
    const password = 'SecurePassword123!';

    await page.goto('/register');
    await page.getByLabel(/full name/i).fill('Reconnect User');
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/^password$/i).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);
    await page.getByRole('button', { name: /^create account$/i }).click();

    await page.waitForURL(/\/dashboard/, { timeout: 15000 });

    const continueButton = page.getByRole('button', { name: /^continue$/i });
    await expect(continueButton).toBeEnabled({ timeout: 15000 });
    await continueButton.click();

    await page.waitForURL(/\/profile/, { timeout: 15000 });

    await page.getByLabel(/^name$/i).fill('Reconnect User Updated');
    await page.getByRole('button', { name: /save changes|continue/i }).click();

    await page.waitForURL(/\/intake/, { timeout: 20000 });

    const input = page.getByPlaceholder(/share some information about yourself/i);
    await expect(input).toBeEnabled({ timeout: 20000 });

    await expect(page.getByText('Connected', { exact: true })).toBeVisible({ timeout: 20000 });

    await context.setOffline(true);
    await expect(page.getByText(/connecting\.\.\.|disconnected/i)).toBeVisible({ timeout: 20000 });

    await context.setOffline(false);
    await expect(page.getByText('Connected', { exact: true })).toBeVisible({ timeout: 20000 });
    await expect(input).toBeEnabled({ timeout: 20000 });
  });
});

