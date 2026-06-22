import { expect, test } from '@playwright/test'
test('upload, parse evaluation and workbench login', async ({ page, request }) => {
  const suffix = Date.now(), username = `e2e_${suffix}`, password = 'e2e-secret'
  const api = 'http://127.0.0.1:8010/api'
  let response = await request.post(`${api}/auth/register/`, { data: { username, password } })
  expect(response.ok()).toBeTruthy()
  response = await request.post(`${api}/auth/login/`, { data: { username, password } })
  const token = (await response.json()).access, headers = { Authorization: `Bearer ${token}` }
  response = await request.post(`${api}/knowledge-bases/`, { headers, data: { name: `E2E KB ${suffix}`, description: 'Playwright flow' } })
  const kb = await response.json()
  const markdown = Buffer.from('# E2E Architecture\n\nRedis and Celery execute document parsing.')
  response = await request.post(`${api}/documents/`, { headers, multipart: { kb: String(kb.id), file: { name: 'e2e.md', mimeType: 'text/markdown', buffer: markdown } } })
  const document = await response.json()
  await expect.poll(async () => (await (await request.get(`${api}/documents/${document.id}/parse-status/`, { headers })).json()).status).toBe('completed')
  response = await request.get(`${api}/documents/${document.id}/parse-preview/?page=1`, { headers })
  expect((await response.json()).page.text).toContain('Redis and Celery')
  response = await request.post(`${api}/document-parse-cases/`, { headers, multipart: {
    case_id: `e2e-parse-${suffix}`, title: 'E2E Markdown', suite: 'smoke', expected_page_count: '1',
    expected_ocr_pages: '[]', expected_headings: '["E2E Architecture"]', expected_terms_by_page: '{"1":["Redis","Celery"]}',
    expected_block_types: '["heading","paragraph"]', expected_table_terms: '[]', thresholds: '{}', tags: '["e2e"]', enabled: 'true',
    file: { name: 'parse-case.md', mimeType: 'text/markdown', buffer: markdown },
  } })
  expect(response.ok()).toBeTruthy()
  response = await request.post(`${api}/document-parse-eval-runs/run/`, { headers, data: { suite: 'smoke' } })
  expect(response.status()).toBe(202)
  const parseRun = await response.json()
  await expect.poll(async () => (await (await request.get(`${api}/document-parse-eval-runs/${parseRun.id}/`, { headers })).json()).status).toBe('completed')
  const detail = await (await request.get(`${api}/document-parse-eval-runs/${parseRun.id}/`, { headers })).json()
  expect(detail.passed_count).toBe(1)
  await page.goto('/')
  await page.getByPlaceholder('用户名').fill(username)
  await page.getByPlaceholder('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('heading', { name: 'RAGOps 工作台' })).toBeVisible()
  await expect(page.locator('.status')).toHaveText(`E2E KB ${suffix}`)
  await page.getByText('评测集', { exact: true }).first().click()
  await expect(page.locator('.parse-case-form')).toBeVisible()
  const suiteBox = await page.locator('.parse-case-form .el-form-item').nth(2).boundingBox()
  const createBox = await page.getByRole('button', { name: '创建解析 Case' }).boundingBox()
  const jsonBox = await page.getByLabel('逐页术语 JSON').boundingBox()
  expect(suiteBox && createBox && jsonBox).toBeTruthy()
  expect(createBox!.y).toBeGreaterThan(jsonBox!.y + jsonBox!.height)
  expect(createBox!.y).toBeGreaterThan(suiteBox!.y + suiteBox!.height)

  response = await request.post(`${api}/reset-workspace/`, { headers, data: {} })
  expect(response.ok()).toBeTruthy()
})

test('organization policy isolates confidential documents', async ({ page, request }) => {
  const suffix = Date.now(), password = 'e2e-secret'
  const ownerName = `acl_owner_${suffix}`, employeeName = `acl_employee_${suffix}`
  const api = 'http://127.0.0.1:8010/api'
  const registerAndLogin = async (username: string) => {
    expect((await request.post(`${api}/auth/register/`, { data: { username, password } })).ok()).toBeTruthy()
    const login = await request.post(`${api}/auth/login/`, { data: { username, password } })
    return (await login.json()).access as string
  }
  const ownerToken = await registerAndLogin(ownerName), employeeToken = await registerAndLogin(employeeName)
  const ownerHeaders = { Authorization: `Bearer ${ownerToken}` }, employeeHeaders = { Authorization: `Bearer ${employeeToken}` }
  const me = await (await request.get(`${api}/auth/me/`, { headers: ownerHeaders })).json()
  const organization = me.organizations[0]
  const roles = await (await request.get(`${api}/organizations/${organization.id}/roles/`, { headers: ownerHeaders })).json()
  const memberRole = roles.find((item: any) => item.slug === 'member')
  expect((await request.post(`${api}/organizations/${organization.id}/memberships/`, { headers: ownerHeaders, data: { username: employeeName, status: 'active', department: 'engineering', clearance: 'internal', roles: [memberRole.id] } })).ok()).toBeTruthy()
  const policies = await (await request.get(`${api}/access-policies/?organization=${organization.id}`, { headers: ownerHeaders })).json()
  const privatePolicy = policies[0]
  let response = await request.post(`${api}/access-policies/`, { headers: ownerHeaders, data: { organization: organization.id, name: `General ${suffix}`, classification: 'internal', visibility: 'organization', allowed_roles: [], allowed_users: [], denied_users: [], allowed_departments: [], is_active: true } })
  const generalPolicy = await response.json()
  response = await request.post(`${api}/knowledge-bases/`, { headers: ownerHeaders, data: { organization: organization.id, access_policy: generalPolicy.id, visibility: 'organization', name: `ACL KB ${suffix}` } })
  const kb = await response.json()
  const upload = async (name: string, policy: number, text: string) => request.post(`${api}/documents/`, { headers: ownerHeaders, multipart: { kb: String(kb.id), access_policy: String(policy), file: { name, mimeType: 'text/plain', buffer: Buffer.from(text) } } })
  expect((await upload('handbook.txt', generalPolicy.id, 'engineering handbook')).status()).toBe(201)
  expect((await upload('salary.txt', privatePolicy.id, 'executive salary 900000')).status()).toBe(201)
  const employeeDocuments = await (await request.get(`${api}/documents/`, { headers: employeeHeaders })).json()
  expect(employeeDocuments.map((item: any) => item.filename)).toContain('handbook.txt')
  expect(employeeDocuments.map((item: any) => item.filename)).not.toContain('salary.txt')

  await page.goto('/')
  await page.getByPlaceholder('用户名').fill(ownerName)
  await page.getByPlaceholder('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.getByText('权限', { exact: true }).click()
  await expect(page.getByRole('heading', { name: '组织与权限' })).toBeVisible()
  await page.getByRole('tab', { name: '成员' }).click()
  await expect(page.getByText(employeeName)).toBeVisible()

  response = await request.post(`${api}/reset-workspace/`, { headers: ownerHeaders, data: { organization: organization.id, confirm_shared: organization.slug } })
  expect(response.ok()).toBeTruthy()
})
