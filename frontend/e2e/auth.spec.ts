import { test, expect } from '@playwright/test';

/**
 * E2E tests for authentication flows
 */

test.describe('Authentication', () => {
  test('should display login page', async ({ page }) => {
    await page.goto('/login');

    // Verify login page elements
    await expect(page.locator('h1, h2, h4')).toContainText(/login|sign in/i);
    await expect(page.getByLabel(/username/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /login|sign in/i })).toBeVisible();
  });

  test('should navigate to register page from login', async ({ page }) => {
    await page.goto('/login');

    // Click register link
    await page.getByRole('link', { name: /register|sign up|create account/i }).click();

    // Should be on register page
    await expect(page).toHaveURL(/\/register/);
    await expect(page.locator('h1, h2, h4')).toContainText(/register|sign up/i);
  });

  test('should display register page', async ({ page }) => {
    await page.goto('/register');

    // Verify register page elements
    await expect(page.locator('h1, h2, h4')).toContainText(/register|sign up/i);
    await expect(page.getByLabel(/username/i)).toBeVisible();
    await expect(page.getByLabel(/^password$/i)).toBeVisible();
    await expect(page.getByLabel(/confirm password/i)).toBeVisible();
    await expect(page.getByLabel(/name|full name/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /register|sign up|create/i })).toBeVisible();
  });

  test('should show validation error for empty fields', async ({ page }) => {
    await page.goto('/login');

    // Try to submit without filling fields
    await page.getByRole('button', { name: /login|sign in/i }).click();

    // Should show validation errors (HTML5 or custom)
    // Check for either native validation or custom error messages
    const usernameInput = page.getByLabel(/username/i);
    const passwordInput = page.getByLabel(/password/i);

    // At least one field should have invalid state or error message nearby
    const hasValidation =
      (await usernameInput.evaluate((el: HTMLInputElement) => !el.validity.valid)) ||
      (await passwordInput.evaluate((el: HTMLInputElement) => !el.validity.valid)) ||
      (await page.locator('text=/required|must be|cannot be empty/i').count()) > 0;

    expect(hasValidation).toBeTruthy();
  });

  test('should show error for invalid credentials', async ({ page }) => {
    await page.goto('/login');

    // Fill in invalid credentials
    await page.getByLabel(/username/i).fill('nonexistent_user');
    await page.getByLabel(/password/i).fill('wrong_password');

    // Submit form
    await page.getByRole('button', { name: /login|sign up/i }).click();

    // Should show error message
    await expect(
      page.locator('text=/invalid|incorrect|failed|error|not found/i')
    ).toBeVisible({ timeout: 5000 });
  });

  test('should register new user successfully', async ({ page }) => {
    const timestamp = Date.now();
    const username = `testuser_${timestamp}`;
    const password = 'SecurePassword123!';
    const name = 'E2E Test User';

    await page.goto('/register');

    // Fill in registration form
    await page.getByLabel(/name|full name/i).fill(name);
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/^password$/i).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);

    // Submit form
    await page.getByRole('button', { name: /register|sign up|create/i }).click();

    // Should redirect to dashboard or profile after successful registration
    await expect(page).toHaveURL(/\/(dashboard|profile|intake)/, { timeout: 10000 });
  });

  test('should login with valid credentials', async ({ page }) => {
    // First register a user
    const timestamp = Date.now();
    const username = `loginuser_${timestamp}`;
    const password = 'LoginPassword123!';
    const name = 'Login Test User';

    await page.goto('/register');
    await page.getByLabel(/name|full name/i).fill(name);
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/^password$/i).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);
    await page.getByRole('button', { name: /register|sign up|create/i }).click();

    // Wait for redirect
    await page.waitForURL(/\/(dashboard|profile|intake)/, { timeout: 10000 });

    // Logout (if logout button exists)
    const logoutButton = page.getByRole('button', { name: /logout|sign out/i });
    if (await logoutButton.isVisible().catch(() => false)) {
      await logoutButton.click();
    } else {
      // Navigate to login manually
      await page.goto('/login');
    }

    // Now login with the same credentials
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/password/i).fill(password);
    await page.getByRole('button', { name: /login|sign in/i }).click();

    // Should redirect to dashboard
    await expect(page).toHaveURL(/\/(dashboard|profile|intake)/, { timeout: 10000 });
  });

  test('should show error when passwords do not match', async ({ page }) => {
    await page.goto('/register');

    await page.getByLabel(/name|full name/i).fill('Test User');
    await page.getByLabel(/username/i).fill('testuser');
    await page.getByLabel(/^password$/i).fill('Password123!');
    await page.getByLabel(/confirm password/i).fill('DifferentPassword!');

    await page.getByRole('button', { name: /register|sign up|create/i }).click();

    // Should show password mismatch error
    await expect(page.locator('text=/password.*match|passwords.*same/i')).toBeVisible();
  });

  test('should reject duplicate username', async ({ page }) => {
    const timestamp = Date.now();
    const username = `duplicate_${timestamp}`;
    const password = 'Password123!';

    // Register first user
    await page.goto('/register');
    await page.getByLabel(/name|full name/i).fill('First User');
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/^password$/i).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);
    await page.getByRole('button', { name: /register|sign up|create/i }).click();

    // Wait for success
    await page.waitForURL(/\/(dashboard|profile|intake)/, { timeout: 10000 });

    // Try to register again with same username
    await page.goto('/register');
    await page.getByLabel(/name|full name/i).fill('Second User');
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/^password$/i).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);
    await page.getByRole('button', { name: /register|sign up|create/i }).click();

    // Should show error about duplicate username
    await expect(
      page.locator('text=/already exists|username.*taken|duplicate/i')
    ).toBeVisible({ timeout: 5000 });
  });
});
