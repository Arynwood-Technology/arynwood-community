import { expect, it } from 'vitest'
import { describeActivity, type Activity } from './activity'

const row = (action: string, extra: Partial<Activity> = {}): Activity => ({ id: 1, at: '2026-10-14T10:00:00Z', action, actor_id: 'sam', actor_name: 'Sam',
  space_id: 'crew', space_name: 'Crew', target_id: null, target_name: '', details: {}, ...extra })

it('says who did what, where', () => {
  expect(describeActivity(row('entry_created', { target_name: 'Print badges', details: { kind: 'task' } }))).toBe('Sam added the task “Print badges” in Crew')
  expect(describeActivity(row('entry_created', { target_name: 'Milk', details: { kind: 'item', parent: 'Groceries' } }))).toBe('Sam added “Milk” to the list “Groceries” in Crew')
  expect(describeActivity(row('entry_updated', { target_name: 'Print badges', details: { kind: 'task', done: true, author: 'Ada' } }))).toBe('Sam marked Ada’s task “Print badges” done in Crew')
  expect(describeActivity(row('entry_deleted', { target_name: 'Schedule', details: { kind: 'board', children: 1 } }))).toBe('Sam deleted the board post “Schedule”, with 1 reply in Crew')
  expect(describeActivity(row('space_deleted', { details: { members: 1, items: 12 } }))).toBe('Sam deleted the space Crew, with 1 member and 12 items')
  expect(describeActivity(row('space_updated', { details: { renamed_from: 'Team', topic: '' } }))).toBe('Sam renamed Team to Crew and cleared its topic')
  expect(describeActivity(row('space_updated', { details: { topic: 'Opening night' } }))).toBe('Sam set the topic of Crew to “Opening night”')
})

it('never names a private item, and names people done to', () => {
  expect(describeActivity(row('entry_created', { target_name: '', details: { kind: 'note', private: true } }))).toBe('Sam added a private note in Crew')
  expect(describeActivity(row('sign_in_failed', { actor_name: '', target_name: 'Ada', space_name: '' }))).toBe('Someone tried to sign in as Ada with the wrong password')
  expect(describeActivity(row('grove_role_changed', { target_name: 'Ada', space_name: '', details: { role: 'manager' } }))).toBe('Sam made Ada a manager of the Grove')
  expect(describeActivity(row('signed_up', { details: { via: 'public link', invited_by: 'Ada' } }))).toBe('Sam joined the Grove through the public link from Ada to Crew')
  expect(describeActivity(row('something_new'))).toBe('Sam: something new')
})
