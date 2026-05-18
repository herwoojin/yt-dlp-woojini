import { useState } from 'react'
import { api } from '../api'

export function UrlForm({ onCreated }: { onCreated: () => void }) {
  const [url, setUrl] = useState('')
  const [quality, setQuality] = useState<'flash' | 'pro'>('flash')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      await api.createJob(url.trim(), quality)
      setUrl('')
      onCreated()
    } catch (e: any) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="bg-white rounded-2xl shadow p-4 sm:p-5 space-y-3">
      <label className="block text-sm font-medium text-slate-700">YouTube URL</label>
      <input
        type="url"
        required
        placeholder="https://www.youtube.com/watch?v=..."
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        className="w-full px-3 py-3 rounded-xl border border-slate-300 focus:border-slate-900 focus:outline-none text-base"
      />
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-slate-600">Gemini 품질:</span>
        <button
          type="button"
          onClick={() => setQuality('flash')}
          className={`px-3 py-1.5 rounded-full text-sm border ${quality === 'flash' ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-700 border-slate-300'}`}
        >Flash (기본/빠름)</button>
        <button
          type="button"
          onClick={() => setQuality('pro')}
          className={`px-3 py-1.5 rounded-full text-sm border ${quality === 'pro' ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-700 border-slate-300'}`}
        >Pro (고품질)</button>
      </div>
      <button
        type="submit"
        disabled={busy || !url}
        className="w-full py-3 rounded-xl bg-emerald-600 text-white font-medium disabled:opacity-50 active:scale-[0.99] transition"
      >
        {busy ? '등록 중...' : '다운로드 + 요약 시작'}
      </button>
      {err && <p className="text-sm text-red-600 whitespace-pre-wrap">{err}</p>}
    </form>
  )
}
