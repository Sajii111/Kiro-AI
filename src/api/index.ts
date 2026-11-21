// The one place that decides which backend the app talks to.
//   VITE_USE_MOCK unset or "true"  -> the sample backend (works with no server)
//   VITE_USE_MOCK=false            -> the FastAPI backend at VITE_API_URL
import { USE_MOCK } from '../config'
import { httpApi } from './http'
import { mockApi } from './mock/mockApi'
import type { Api } from './types'

export const api: Api = USE_MOCK ? mockApi : httpApi
export const isMock = USE_MOCK
