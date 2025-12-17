import { test, expect } from '@playwright/test';

/**
 * E2E tests for authentication flows
 */

test.describe('Authentication', () => {
  test('should display login page', async ({ page }) => {
    await page.goto('/login');

    // Verify login page elements
    await expect(page.getByText(/sign in to your account/i)).toBeVisible();
    await expect(page.getByLabel(/username/i)).toBeVisible();
    await expect(page.getByLabel(/password/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /^sign in$/i })).toBeVisible();
  });

  test('should navigate to register page from login', async ({ page }) => {
    await page.goto('/login');

    // Click register link
    await page.getByRole('link', { name: /register here/i }).click();

    // Should be on register page
    await expect(page).toHaveURL(/\/register/);
    await expect(page.getByText(/create your account/i)).toBeVisible();
  });

  test('should display register page', async ({ page }) => {
    await page.goto('/register');

    // Verify register page elements
    await expect(page.getByText(/create your account/i)).toBeVisible();
    await expect(page.getByLabel(/username/i)).toBeVisible();
    await expect(page.getByLabel(/^password$/i)).toBeVisible();
    await expect(page.getByLabel(/confirm password/i)).toBeVisible();
    await expect(page.getByLabel(/full name/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /^create account$/i })).toBeVisible();
  });

  test('should show validation error for empty fields', async ({ page }) => {
    await page.goto('/login');

    // Try to submit without filling fields
    await page.getByRole('button', { name: /^sign in$/i }).click();

    // Uses custom validation message in LoginPage
    await expect(page.locator('text=/please enter both username and password/i')).toBeVisible();
  });

  test('should show error for invalid credentials', async ({ page }) => {
    await page.goto('/login');

    // Fill in invalid credentials
    await page.getByLabel(/username/i).fill('nonexistent_user');
    await page.getByLabel(/password/i).fill('wrong_password');

    // Submit form
    await page.getByRole('button', { name: /^sign in$/i }).click();

    // Should show error message
    await expect(
      page.locator('text=/invalid username or password/i')
    ).toBeVisible({ timeout: 5000 });
  });

  test('should register new user successfully', async ({ page }) => {
    const timestamp = Date.now();
    const username = `testuser_${timestamp}`;
    const password = 'SecurePassword123!';
    const name = 'E2E Test User';

    await page.goto('/register');

    // Fill in registration form
    await page.getByLabel(/full name/i).fill(name);
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/^password$/i).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);

    // Submit form
    await page.getByRole('button', { name: /^create account$/i }).click();

    // Should redirect to dashboard after successful registration
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 });
  });

  test('should login with valid credentials', async ({ page }) => {
    // First register a user
    const timestamp = Date.now();
    const username = `loginuser_${timestamp}`;
    const password = 'LoginPassword123!';
    const name = 'Login Test User';

    await page.goto('/register');
    await page.getByLabel(/full name/i).fill(name);
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/^password$/i).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);
    await page.getByRole('button', { name: /^create account$/i }).click();

    // Wait for redirect
    await page.waitForURL(/\/dashboard/, { timeout: 10000 });

    // Simulate logout by clearing session storage and reloading.
    await page.evaluate(() => {
      sessionStorage.removeItem('auth_token');
      sessionStorage.removeItem('current_user_id');
    });
    await page.reload();
    await page.goto('/login');

    // Now login with the same credentials
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/password/i).fill(password);
    await page.getByRole('button', { name: /^sign in$/i }).click();

    // Should redirect to dashboard
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10000 });
  });

  test('should show error when passwords do not match', async ({ page }) => {
    await page.goto('/register');

    await page.getByLabel(/full name/i).fill('Test User');
    await page.getByLabel(/username/i).fill('testuser');
    await page.getByLabel(/^password$/i).fill('Password123!');
    await page.getByLabel(/confirm password/i).fill('DifferentPassword!');

    await page.getByRole('button', { name: /^create account$/i }).click();

    // Should show password mismatch error
    await expect(page.locator('text=/passwords do not match/i')).toBeVisible();
  });

  test('should reject duplicate username', async ({ page }) => {
    const timestamp = Date.now();
    const username = `duplicate_${timestamp}`;
    const password = 'Password123!';

    // Register first user
    await page.goto('/register');
    await page.getByLabel(/full name/i).fill('First User');
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/^password$/i).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);
    await page.getByRole('button', { name: /^create account$/i }).click();

    // Wait for success
    await page.waitForURL(/\/dashboard/, { timeout: 10000 });

    // Try to register again with same username
    await page.goto('/register');
    await page.getByLabel(/full name/i).fill('Second User');
    await page.getByLabel(/username/i).fill(username);
    await page.getByLabel(/^password$/i).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);
    await page.getByRole('button', { name: /^create account$/i }).click();

    // Should show error about duplicate username
    await expect(
      page.locator('text=/username already exists/i')
    ).toBeVisible({ timeout: 5000 });
  });
});
