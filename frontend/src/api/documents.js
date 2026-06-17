import { request } from './client'

export const documentApi = {
  listDocuments: () => request('/documents/'),
  uploadDocument: (kb, file) => {
    const form = new FormData()
    form.append('kb', kb)
    form.append('file', file)
    return request('/documents/', { method: 'POST', body: form })
  },
  previewChunks: (id, payload) =>
    request(`/documents/${id}/chunk-preview/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  indexDocument: (id, payload) =>
    request(`/documents/${id}/index/`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
