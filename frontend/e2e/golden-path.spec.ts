import { test, expect } from '@playwright/test';

test.describe('Golden Path (Deterministic)', () => {
  test('register → profile → intake chat streams a response', async ({ page }) => {
    const timestamp = Date.now();
    const username = `e2e_${timestamp}`;
    const password = 'SecurePassword123!';
    const name = 'E2E User';

    // Register
    await page.goto('/register');
    await page.getByLabel(/full name/i).fill(name);
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/^password$/i).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);
    await page.getByRole('button', { name: /create account/i }).click();

    await page.waitForURL(/\/dashboard/, { timeout: 15000 });

    // Dashboard → Profile (backend-driven)
    const continueButton = page.getByRole('button', { name: /^continue$/i });
    await expect(continueButton).toBeEnabled({ timeout: 15000 });
    await continueButton.click();

    await page.waitForURL(/\/profile/, { timeout: 15000 });

    // Save profile to advance workflow to intake
    await page.getByLabel(/^name$/i).fill('E2E User Updated');
    await page.getByRole('button', { name: /save changes|continue/i }).click();

    await page.waitForURL(/\/intake/, { timeout: 20000 });

    // Intake chat should connect + request a session; input enabled after session_started.
    const input = page.getByPlaceholder(/share some information about yourself/i);
    await expect(input).toBeEnabled({ timeout: 20000 });

    const userMessage = 'I have been feeling stressed lately.';
    await input.fill(userMessage);
    await input.press('Enter');

    await expect(page.locator(`text=${userMessage}`)).toBeVisible({ timeout: 10000 });

    // Deterministic backend always produces deterministic marker text.
    await expect(page.locator('text=/\\[deterministic-llm\\]/')).toBeVisible({ timeout: 20000 });
  });
});

