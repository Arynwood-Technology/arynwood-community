import { api } from './community'

export interface Person { id: string; name: string }
export interface Conversation { id: string; with: { id: string | null; name: string }; last: string; last_from_me: boolean; updated: string; unread: number }
export interface Photo { id: string; width: number; height: number }
export interface Message { id: string; sender_id: string | null; body: string; photos: Photo[]; created: string; deleted: boolean }
export interface Thread extends Conversation { messages: Message[]; can_write: boolean }

export const photoUrl = (id: string) => `/community-api/messages/photos/${id}`
// Under the Grove's 10 MB limit for one photo, which is also its web server's limit for one request.
const MOST = 9 * 1024 * 1024

/** A photo as Messages sends it: at most 4096 pixels across, as a JPEG. Drawing it afresh leaves
 *  behind what the camera wrote into the file, such as where it was taken. A very detailed photo
 *  goes at a lower JPEG quality to stay under `most` bytes. */
export async function shrinkPhoto(file: File, longest = 4096, most = MOST): Promise<Blob> {
  let picture: ImageBitmap
  try { picture = await createImageBitmap(file, { imageOrientation: 'from-image' }) }
  catch { throw new Error(`${file.name} can't be opened as a photo here. Try a JPEG or PNG.`) }
  const scale = Math.min(1, longest / Math.max(picture.width, picture.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(picture.width * scale); canvas.height = Math.round(picture.height * scale)
  const context = canvas.getContext('2d')
  if (!context) throw new Error('This browser can’t prepare photos.')
  context.fillStyle = '#ffffff'; context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(picture, 0, 0, canvas.width, canvas.height)
  picture.close()
  for (const quality of [0.85, 0.7, 0.55]) {
    const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', quality))
    if (!blob) throw new Error('This browser can’t prepare photos.')
    if (blob.size <= most) return blob
  }
  throw new Error(`${file.name} is too large to send, even made smaller.`)
}

export async function uploadPhoto(blob: Blob): Promise<Photo> {
  const response = await fetch('/community-api/messages/photos', { method: 'POST', body: blob, headers: { 'X-Community-Request': '1', 'Content-Type': blob.type || 'application/octet-stream' } })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The photo could not be sent.')
  return data as Photo
}

export const messagesApi = {
  people: () => api<Person[]>('/messages/people'),
  conversations: () => api<Conversation[]>('/messages/conversations'),
  start: (userId: string) => api<Conversation>('/messages/conversations', 'POST', { user_id: userId }),
  thread: (id: string) => api<Thread>(`/messages/conversations/${id}`),
  read: (id: string) => api(`/messages/conversations/${id}/read`, 'POST'),
  send: (id: string, body: string, photos: string[]) => api<Message>(`/messages/conversations/${id}/messages`, 'POST', { body, photos }),
  takeBack: (id: string) => api(`/messages/messages/${id}`, 'DELETE'),
  unread: () => api<{ unread: number }>('/messages/unread'),
}
