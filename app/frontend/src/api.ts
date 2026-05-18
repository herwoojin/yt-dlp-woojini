import { getIdToken } from './firebase'

const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export type JobStatus = 'pending' | 'downloading' | 'transcribing' | 'generating' | 'done' | 'failed'

export type JobArtifact = { kind: string; filename: string; size_bytes: number | null }

export type JobInfo = {
  id: string
  url: string
  title: string | null
  status: JobStatus
  quality: 'flash' | 'pro'
  progress: number
  message: string | null
  error: string | null
  created_at: string
  updated_at: string
  artifacts: JobArtifact[]
  chapters: { time: string; title: string; summary?: string }[]
  duration_seconds: number | null
}

export type AppSettings = {
  download_dir: string
  default_model: string
  pro_model: string
  telegram_enabled: boolean
}

async function authHeaders(): Promise<HeadersInit> {
  const t = await getIdToken()
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (t) h['Authorization'] = `Bearer ${t}`
  return h
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = { ...(await authHeaders()), ...(init.headers || {}) }
  const r = await fetch(`${BASE}${path}`, { ...init, headers })
  if (!r.ok) {
    const text = await r.text().catch(() => '')
    throw new Error(`${r.status} ${r.statusText} - ${text}`)
  }
  return r.json() as Promise<T>
}

export const api = {
  listJobs: () => req<JobInfo[]>('/api/jobs'),
  getJob: (id: string) => req<JobInfo>(`/api/jobs/${id}`),
  createJob: (url: string, quality: 'flash' | 'pro') =>
    req<JobInfo>('/api/jobs', { method: 'POST', body: JSON.stringify({ url, quality }) }),
  getSettings: () => req<AppSettings>('/api/settings'),
  updateSettings: (download_dir: string) =>
    req<AppSettings>('/api/settings', { method: 'PUT', body: JSON.stringify({ download_dir }) }),
  fileUrl: (jobId: string, filename: string) => `${BASE}/api/files/${jobId}/${filename}`,
}
