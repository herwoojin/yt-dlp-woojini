import { useCallback, useEffect, useState } from 'react'
import { watchAuth, signOutUser, type AuthUser } from './firebase'
import { api, type JobInfo } from './api'
import { Login } from './components/Login'
import { UrlForm } from './components/UrlForm'
import { JobList } from './components/JobList'
import { JobDetail } from './components/JobDetail'
import { SettingsPanel } from './components/SettingsPanel'

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [authReady, setAuthReady] = useState(false)
  const [jobs, setJobs] = useState<JobInfo[]>([])
  const [openId, setOpenId] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)

  useEffect(() => {
    const unsub = watchAuth((u) => { setUser(u); setAuthReady(true) })
    return () => unsub()
  }, [])

  const refresh = useCallback(async () => {
    if (!user) return
    try {
      const list = await api.listJobs()
      setJobs(list)
    } catch {/* network blip */}
  }, [user])

  useEffect(() => {
    if (!user) return
    refresh()
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [user, refresh])

  if (!authReady) {
    return <div className="min-h-screen flex items-center justify-center text-sm text-slate-500">로딩...</div>
  }

  if (!user) {
    return <Login onSignedIn={() => {/* watchAuth will fire */}} />
  }

  return (
    <div className="min-h-screen max-w-2xl mx-auto px-3 sm:px-6 py-4 sm:py-6">
      <header className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-lg sm:text-xl font-bold">🎬 yt-dlp web app</h1>
          <p className="text-[11px] text-slate-500">{user.email || user.uid}</p>
        </div>
        <div className="flex gap-1.5">
          <button
            onClick={() => setShowSettings(true)}
            className="text-xs px-2.5 py-1.5 rounded-lg bg-white border border-slate-200"
          >⚙️ 설정</button>
          <button
            onClick={async () => { await signOutUser(); setUser(null) }}
            className="text-xs px-2.5 py-1.5 rounded-lg bg-white border border-slate-200"
          >로그아웃</button>
        </div>
      </header>

      {openId ? (
        <JobDetail jobId={openId} onBack={() => setOpenId(null)} />
      ) : (
        <main className="space-y-4">
          <UrlForm onCreated={refresh} />
          <JobList jobs={jobs} onOpen={setOpenId} />
        </main>
      )}

      {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}
    </div>
  )
}
