import { test, expect } from '@playwright/test';

test.describe('Golden Path (Deterministic)', () => {
  test('profile → intake chat streams a response', async ({ page }) => {
    await page.goto('/dashboard');

    // Dashboard → Profile (backend-driven)
    await page.waitForURL(/\/(dashboard|profile)/, { timeout: 15000 });
    if (page.url().includes('/dashboard')) {
      const continueButton = page.getByRole('button', { name: /^continue$/i });
      await expect(continueButton).toBeEnabled({ timeout: 15000 });
      await continueButton.click();
    }

    await page.waitForURL(/\/profile/, { timeout: 15000 });

    // Save profile to advance workflow to intake
    await page.getByRole('button', { name: /create new profile/i }).click({ timeout: 15000 });
    await page.getByRole('textbox', { name: /name/i }).fill('E2E User Updated');
    await page.getByRole('button', { name: /save changes|continue/i }).click();

    await page.waitForURL(/\/intake/, { timeout: 20000 });

    // Intake chat should connect + request a session; input enabled after session_started.
    await expect(page.getByText('Connected', { exact: true })).toBeVisible({ timeout: 20000 });
    const input = page.getByRole('textbox');
    await expect(input).toBeEnabled({ timeout: 20000 });

    const userMessage = 'I have been feeling stressed lately.';
    await input.fill(userMessage);
    await input.press('Enter');

    await expect(page.locator(`text=${userMessage}`)).toBeVisible({ timeout: 10000 });

    // Deterministic backend always produces deterministic marker text.
    await expect(
      page.locator('text=/\\[deterministic-llm\\]/').first()
    ).toBeVisible({ timeout: 20000 });
  });
});
