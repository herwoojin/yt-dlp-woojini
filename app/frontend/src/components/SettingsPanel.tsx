import { useEffect, useState } from 'react'
import { api, type AppSettings } from '../api'

export function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [dir, setDir] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.getSettings().then((s) => { setSettings(s); setDir(s.download_dir) }).catch((e) => setErr(String(e)))
  }, [])

  async function save() {
    setMsg(null); setErr(null)
    try {
      const s = await api.updateSettings(dir)
      setSettings(s)
      setMsg('저장됨')
    } catch (e: any) {
      setErr(String(e?.message || e))
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-end sm:items-center justify-center p-2 sm:p-6" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-md p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-semibold">⚙️ 설정</h3>
        {!settings ? <p className="text-sm">로딩...</p> : (
          <>
            <label className="text-sm block">
              저장 경로
              <input
                value={dir}
                onChange={(e) => setDir(e.target.value)}
                className="mt-1 w-full px-3 py-2 rounded-lg border border-slate-300 text-sm"
              />
              <span className="text-[11px] text-slate-500">현재: {settings.download_dir}</span>
            </label>
            <div className="text-[12px] text-slate-600 space-y-1">
              <div>기본 모델: <span className="font-mono">{settings.default_model}</span></div>
              <div>고품질 모델: <span className="font-mono">{settings.pro_model}</span></div>
              <div>텔레그램: {settings.telegram_enabled ? '활성' : '비활성'}</div>
            </div>
          </>
        )}
        {msg && <p className="text-sm text-emerald-600">{msg}</p>}
        {err && <p className="text-sm text-red-600">{err}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="px-3 py-2 rounded-lg bg-slate-100 text-sm">닫기</button>
          <button onClick={save} className="px-3 py-2 rounded-lg bg-slate-900 text-white text-sm">저장</button>
        </div>
      </div>
    </div>
  )
}
