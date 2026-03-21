import { test, expect } from '@playwright/test'

test('app should render and show login page', async ({ page }) => {
  await page.goto('/login')
  // 验证登录页能基本渲染
  await expect(page.locator('body')).toContainText('登录', { timeout: 10000 })
})
