const { test, expect } = require('@playwright/test');

// Helper: navigate to catalog and wait for groups
async function openCatalog(page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Parts Catalog' }).click();
  // Wait for Alpine to load groups (they appear as buttons in the left panel)
  await expect(
    page.getByRole('button', { name: 'ENGINE', exact: true })
  ).toBeVisible({ timeout: 15000 });
}

test('catalog groups load', async ({ page }) => {
  await openCatalog(page);
  await expect(page.getByRole('button', { name: 'SERVICE AND SCOPE OF REPAIR WORK', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'BRAKES', exact: true })).toBeVisible();
});

test('subgroups load on group click', async ({ page }) => {
  await openCatalog(page);
  await page.getByRole('button', { name: 'SERVICE AND SCOPE OF REPAIR WORK', exact: true }).click();
  await expect(page.getByRole('button', { name: /ENGINE OIL/i })).toBeVisible({ timeout: 15000 });
});

test('parts load on subgroup click', async ({ page }) => {
  await openCatalog(page);
  await page.getByRole('button', { name: 'SERVICE AND SCOPE OF REPAIR WORK', exact: true }).click();
  await page.getByRole('button', { name: /ENGINE OIL/i }).click();
  await expect(page.getByText('Set oil-filter element')).toBeVisible({ timeout: 30000 });
});

test('RockAuto link opens correct URL', async ({ page }) => {
  // Intercept window.open before any navigation
  await page.addInitScript(() => {
    window._openedUrls = [];
    window.open = (url, target, features) => {
      window._openedUrls.push({ url: String(url), target, features });
      console.log('window.open:', url);
      return null;
    };
  });

  await openCatalog(page);
  await page.getByRole('button', { name: 'SERVICE AND SCOPE OF REPAIR WORK', exact: true }).click();
  await page.getByRole('button', { name: /ENGINE OIL/i }).click();
  await expect(page.getByText('Set oil-filter element')).toBeVisible({ timeout: 30000 });

  // Wait for at least one green RA price link to appear
  const raLink = page.locator('a.text-green-400').first();
  await expect(raLink).toBeVisible({ timeout: 30000 });

  const linkText = await raLink.textContent();
  console.log('Clicking RA link:', linkText?.trim());

  await raLink.click();

  const calls = await page.evaluate(() => window._openedUrls);
  console.log('window.open calls:', JSON.stringify(calls));

  expect(calls.length, 'window.open should have been called').toBeGreaterThan(0);
  expect(calls[0].url).toContain('rockauto.com');
  expect(calls[0].url).not.toContain('localhost');
  expect(calls[0].url.length).toBeGreaterThan(10);
});
