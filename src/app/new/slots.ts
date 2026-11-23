import type { ValidationResult } from '../../api/types'
import type { PreparedPhoto } from '../../lib/photo'

/** One of the two photo places (left palm, right palm) and where it has got to. */
export type Slot =
  | { status: 'empty' }
  | { status: 'preparing'; name: string }
  | { status: 'checking'; photo: PreparedPhoto }
  | { status: 'ready'; photo: PreparedPhoto; result: ValidationResult }
  | { status: 'rejected'; name: string; message: string }

export type ReadySlot = Extract<Slot, { status: 'ready' }>

/** A photo that passed (warnings are fine, failures are not). */
export const isUsable = (slot: Slot): slot is ReadySlot => slot.status === 'ready' && slot.result.ok

export const photoOf = (slot: Slot): PreparedPhoto | null => (slot.status === 'checking' || slot.status === 'ready' ? slot.photo : null)
