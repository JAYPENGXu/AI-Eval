import { request } from './client'
import type { AccessPolicy, AuthorizationAuditLog, Membership, Organization, Role } from '../types/api'

export const permissionApi = {
  listOrganizations: () => request<Organization[]>('/organizations/'),
  createOrganization: (payload: { name: string }) => request<Organization>('/organizations/', { method: 'POST', body: JSON.stringify(payload) }),
  updateOrganization: (id: number, payload: Record<string, unknown>) => request<Organization>(`/organizations/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) }),
  listPrincipals: (organization: number) => request<Array<Record<string, any>>>(`/organizations/${organization}/principals/`),
  listMemberships: (organization: number) => request<Membership[]>(`/organizations/${organization}/memberships/`),
  createMembership: (organization: number, payload: Record<string, unknown>) => request<Membership>(`/organizations/${organization}/memberships/`, { method: 'POST', body: JSON.stringify(payload) }),
  updateMembership: (organization: number, id: number, payload: Record<string, unknown>) => request<Membership>(`/organizations/${organization}/memberships/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) }),
  listRoles: (organization: number) => request<Role[]>(`/organizations/${organization}/roles/`),
  createRole: (organization: number, payload: Record<string, unknown>) => request<Role>(`/organizations/${organization}/roles/`, { method: 'POST', body: JSON.stringify(payload) }),
  updateRole: (organization: number, id: number, payload: Record<string, unknown>) => request<Role>(`/organizations/${organization}/roles/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) }),
  listPolicies: (organization: number) => request<AccessPolicy[]>(`/access-policies/?organization=${organization}`),
  createPolicy: (payload: Record<string, unknown>) => request<AccessPolicy>('/access-policies/', { method: 'POST', body: JSON.stringify(payload) }),
  updatePolicy: (id: number, payload: Record<string, unknown>) => request<AccessPolicy>(`/access-policies/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) }),
  listAuthorizationAuditLogs: (organization: number) => request<AuthorizationAuditLog[]>(`/authorization-audit-logs/?organization=${organization}`),
  setDocumentPolicy: (document: number, accessPolicy: number, inheritsPolicy = false) => request(`/documents/${document}/set-access-policy/`, { method: 'POST', body: JSON.stringify({ access_policy: accessPolicy, inherits_policy: inheritsPolicy }) }),
  bulkSetChunkPolicy: (chunkIds: number[], accessPolicy: number) => request('/chunks/bulk-set-access-policy/', { method: 'POST', body: JSON.stringify({ chunk_ids: chunkIds, access_policy: accessPolicy }) }),
}
