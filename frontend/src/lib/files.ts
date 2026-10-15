import { api } from './community'

export interface FileItem {
  id: string; folder: string; name: string; kind: 'file' | 'folder'; size: number; version: number
  created: string; updated: string; deleted: string | null; author_id: string | null; author: string; updated_by: string
}
export interface Listing { folder: string; items: FileItem[]; used: number; limit: number; file_limit: number }
export interface Version { version: number; size: number; created: string; author: string }

export function bytes(n: number) {
  if (n < 1024) return `${n} B`
  const [value, unit] = n < 1024 ** 2 ? [n / 1024, 'KB'] : n < 1024 ** 3 ? [n / 1024 ** 2, 'MB'] : [n / 1024 ** 3, 'GB']
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${unit}`
}
export const joined = (folder: string, name: string) => folder ? `${folder}/${name}` : name
export const contentUrl = (spaceId: string, id: string, query = '') => `/community-api/community/spaces/${spaceId}/files/${id}/content${query}`
export const zipUrl = (spaceId: string, id: string) => `/community-api/community/spaces/${spaceId}/files/${id}/zip`
const images = /\.(png|jpe?g|gif|webp)$/i, texts = /\.(txt|md|csv|tsv|json|html?|css|m?js|tsx?|jsx|svg|xml|ya?ml|toml|ini|srt|vtt)$/i
export const isImage = (name: string) => images.test(name)
export const isText = (name: string) => texts.test(name)

/** "Poster.png" → "Poster (2).png", the first name not already in `taken`. */
export function freeName(name: string, taken: Set<string>) {
  const dot = name.lastIndexOf('.'), stem = dot > 0 ? name.slice(0, dot) : name, ext = dot > 0 ? name.slice(dot) : ''
  for (let n = 2; ; n++) if (!taken.has(`${stem} (${n})${ext}`)) return `${stem} (${n})${ext}`
}

// Under nginx's 1 MB default, for servers whose proxy refuses the larger pieces the Grove asks for.
const SMALL_PIECE = 768 * 1024

async function reason(response: Response) {
  const data = await response.json().catch(() => ({}))
  return typeof data.detail === 'string' ? data.detail : 'The upload failed.'
}

/** Sends a file in pieces. A dropped connection picks up where the server got to. */
export async function uploadFile(spaceId: string, file: File, options: { folder?: string; name?: string; replaces?: string; onProgress?: (sent: number) => void } = {}) {
  const root = `/community/spaces/${spaceId}/uploads`
  const started = await api<{ id: string; chunk: number }>(root, 'POST', { folder: options.folder ?? '', name: options.name ?? file.name, size: file.size, replaces: options.replaces ?? null })
  let piece = started.chunk, offset = 0, failures = 0
  while (offset < file.size) {
    const part = file.slice(offset, offset + piece)
    const response = await fetch(`/community-api${root}/${started.id}?offset=${offset}`, { method: 'PUT', body: part,
      headers: { 'X-Community-Request': '1', 'Content-Type': 'application/octet-stream' } }).catch(() => null)
    if (response?.ok) { offset += part.size; failures = 0; options.onProgress?.(offset); continue }
    if (response?.status === 413 && piece > SMALL_PIECE) { piece = SMALL_PIECE; continue }
    if (response && response.status !== 409 && response.status < 500) throw new Error(await reason(response))
    if (++failures > 5) throw new Error('The connection keeps dropping. Try again in a moment.')
    await new Promise(resolve => setTimeout(resolve, 500 * failures))
    offset = (await api<{ received: number }>(`${root}/${started.id}`)).received
  }
  return api<FileItem>(`${root}/${started.id}/finish`, 'POST')
}

export const saveText = (spaceId: string, id: string, text: string, version: number) => api<FileItem>(`/community/spaces/${spaceId}/files/${id}/text`, 'PUT', { text, version })
export const previewFolder = (spaceId: string, folder: string) => api<{ url: string }>(`/community/spaces/${spaceId}/previews`, 'POST', { folder })
export async function readText(spaceId: string, item: Pick<FileItem, 'id' | 'version'>) {
  const response = await fetch(contentUrl(spaceId, item.id, `?inline=1&version=${item.version}`))
  if (!response.ok) throw new Error('The file could not be opened. Try again.')
  return response.text()
}
