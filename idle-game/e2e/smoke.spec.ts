import { expect, test } from '@playwright/test';

test('opens the workbench and switches activity tabs', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('边境日志')).toBeVisible();
  await expect(page.getByRole('heading', { name: '边境巡猎' })).toBeVisible();
  await page.getByRole('button', { name: '采集' }).click();
  await expect(page.getByRole('heading', { name: '野外采集' })).toBeVisible();
  await page.getByRole('button', { name: '制作' }).click();
  await expect(page.getByRole('heading', { name: '工坊清单' })).toBeVisible();
});
