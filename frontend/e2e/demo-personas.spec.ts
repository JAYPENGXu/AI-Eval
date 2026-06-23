import { expect, test } from '@playwright/test'

const api = 'http://127.0.0.1:8010/api'

async function personaToken(request: any, username: string) {
  const response = await request.post(`${api}/demo/persona-login/`, { data: { username } })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()).access as string
}

async function filenames(request: any, token: string) {
  const response = await request.get(`${api}/documents/`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).map((item: any) => item.filename as string)
}

test('persona login exposes distinct RBAC and ABAC document scopes', async ({ page, request }) => {
  const personas = await request.get(`${api}/demo/personas/`)
  expect(personas.ok()).toBeTruthy()
  expect((await personas.json()).personas).toHaveLength(6)

  const engineer = await personaToken(request, 'demo_engineer')
  const hr = await personaToken(request, 'demo_hr')
  const owner = await personaToken(request, 'demo_owner')
  const vendor = await personaToken(request, 'demo_vendor')
  const suspended = await request.post(`${api}/demo/persona-login/`, { data: { username: 'demo_suspended' } })
  expect(suspended.status()).toBe(403)

  const engineerDocs = await filenames(request, engineer)
  expect(engineerDocs).toContain('xinghai_engineering_release.pdf')
  expect(engineerDocs).toContain('xinghai_personal_salary_linxiao.pdf')
  expect(engineerDocs).not.toContain('xinghai_compensation_policy.pdf')

  const hrDocs = await filenames(request, hr)
  expect(hrDocs).toContain('xinghai_compensation_policy.pdf')
  expect(hrDocs).toContain('xinghai_personal_salary_linxiao.pdf')
  expect(hrDocs).not.toContain('xinghai_engineering_release.pdf')

  const ownerDocs = await filenames(request, owner)
  expect(ownerDocs).toContain('xinghai_compensation_policy.pdf')
  expect(ownerDocs).not.toContain('yuanhang_vendor_delivery.pdf')
  expect(await filenames(request, vendor)).toEqual(['yuanhang_vendor_delivery.pdf'])

  await page.goto('/')
  await expect(page.getByText('选择演示角色')).toBeVisible()
  await page.locator('[data-persona="demo_engineer"]').click()
  await expect(page.getByRole('heading', { name: 'RAGOps 工作台' })).toBeVisible()
  await expect(page.getByText('星海科技企业知识库').first()).toBeVisible()
})

test('switching demo personas never exposes the previous identity chat sessions', async ({ page, request }) => {
  const engineer = await personaToken(request, 'demo_engineer')
  const headers = { Authorization: 'Bearer ' + engineer }
  const kbs = await (await request.get(api + '/knowledge-bases/', { headers })).json()
  const kb = kbs.find((item: any) => item.name === '星海科技企业知识库')
  const title = '研发身份隔离会话'
  const created = await request.post(api + '/chat-sessions/', { headers, data: { kb: kb.id, title } })
  expect(created.status()).toBe(201)
  const session = await created.json()

  try {
    await page.goto('/')
    await page.locator('[data-persona="demo_engineer"]').click()
    await expect(page.getByRole('heading', { name: 'RAGOps 工作台' })).toBeVisible()
    await page.getByRole('button', { name: '历史会话' }).click()
    await expect(page.getByRole('button', { name: new RegExp(title) })).toBeVisible()
    await page.getByRole('button', { name: '关闭' }).click()

    await page.getByRole('button', { name: '退出' }).click()
    await page.locator('[data-persona="demo_vendor"]').click()
    await expect(page.getByRole('heading', { name: 'RAGOps 工作台' })).toBeVisible()
    await expect(page.getByText(title)).toHaveCount(0)
    await page.getByRole('button', { name: '历史会话' }).click()
    await expect(page.getByRole('button', { name: new RegExp(title) })).toHaveCount(0)
  } finally {
    await request.delete(api + '/chat-sessions/' + session.id + '/', { headers })
  }
})

test('seeded baseline supports HITL publish, audit and rollback', async ({ request }) => {
  const token = await personaToken(request, 'demo_owner')
  const headers = { Authorization: `Bearer ${token}` }
  const kbs = await (await request.get(`${api}/knowledge-bases/`, { headers })).json()
  const kb = kbs.find((item: any) => item.name === '星海科技企业知识库')
  expect(kb).toBeTruthy()

  const runs = await (await request.get(`${api}/rag-eval-runs/?kb=${kb.id}`, { headers })).json()
  expect(runs).toHaveLength(3)
  expect(runs.some((item: any) => item.settings?.suite === 'release' || item.case_count === 1)).toBeTruthy()
  const plans = await (await request.get(`${api}/rag-experiment-plans/?kb=${kb.id}`, { headers })).json()
  expect(plans).toHaveLength(1)
  expect(plans[0].status).toBe('completed')

  const actions = await (await request.get(`${api}/rag-agent-actions/?kb=${kb.id}`, { headers })).json()
  const publish = actions.find((item: any) => item.source === 'demo_seed')
  expect(publish.status).toBe('pending')
  const published = await request.post(`${api}/rag-agent-actions/${publish.id}/confirm/`, { headers, data: {} })
  expect(published.ok(), await published.text()).toBeTruthy()
  expect((await published.json()).status).toBe('completed')

  const versions = await (await request.get(`${api}/rag-config-versions/?kb=${kb.id}`, { headers })).json()
  const initial = versions.find((item: any) => item.version === 1)
  const rollback = await request.post(`${api}/rag-config-versions/${initial.id}/request-rollback/`, {
    headers,
    data: { reason: 'Playwright demo rollback' },
  })
  expect(rollback.status()).toBe(201)
  const rollbackAction = await rollback.json()
  const confirmed = await request.post(`${api}/rag-agent-actions/${rollbackAction.id}/confirm/`, { headers, data: {} })
  expect(confirmed.ok(), await confirmed.text()).toBeTruthy()

  const deployments = await (await request.get(`${api}/rag-config-deployments/?kb=${kb.id}`, { headers })).json()
  expect(deployments.map((item: any) => item.operation)).toEqual(expect.arrayContaining(['publish', 'rollback']))
  const protectedDelete = await request.delete(`${api}/knowledge-bases/${kb.id}/`, { headers })
  expect(protectedDelete.status()).toBe(403)
})
