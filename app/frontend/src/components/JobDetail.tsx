import { useEffect, useState } from 'react'
import { api, type JobInfo } from '../api'

const ARTIFACT_LABEL: Record<string, string> = {
  video: '🎥 영상 (mp4)',
  subtitle: '📝 자막 (vtt/srt)',
  transcript_txt: '📄 원본 스크립트 (txt)',
  chapters: '📚 시계열 목차 (json)',
  summary_short: '✨ 짧은 요약 (html)',
  email_readable: '✉️ 이메일용 가독성 HTML',
  blog_long: '📰 블로그/카페용 장문 HTML',
  info_json: 'ℹ️ 영상 메타 (info.json)',
}

export function JobDetail({ jobId, onBack }: { jobId: string; onBack: () => void }) {
  const [job, setJob] = useState<JobInfo | null>(null)
  const [preview, setPreview] = useState<{ kind: string; html: string } | null>(null)

  useEffect(() => {
    let alive = true
    async function load() {
      try {
        const j = await api.getJob(jobId)
        if (alive) setJob(j)
      } catch {/* noop */}
    }
    load()
    const t = setInterval(load, 2500)
    return () => { alive = false; clearInterval(t) }
  }, [jobId])

  async function previewHtml(filename: string, kind: string) {
    const url = api.fileUrl(jobId, filename)
    const r = await fetch(url, { headers: { Accept: 'text/html' } })
    const html = await r.text()
    setPreview({ kind, html })
  }

  if (!job) {
    return <div className="p-8 text-center text-sm text-slate-500">불러오는 중...</div>
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <button onClick={onBack} className="text-sm text-slate-600 hover:underline">← 목록</button>
      </div>

      <div className="bg-white rounded-2xl shadow p-4 sm:p-5 space-y-2">
        <h2 className="font-semibold text-lg">{job.title || job.url}</h2>
        <p className="text-xs text-slate-500 break-all">{job.url}</p>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="px-2 py-1 rounded-full bg-slate-100">상태: {job.status}</span>
          <span className="px-2 py-1 rounded-full bg-slate-100">진행: {Math.round(job.progress * 100)}%</span>
          <span className="px-2 py-1 rounded-full bg-slate-100">Gemini: {job.quality}</span>
        </div>
        {job.message && <p className="text-xs text-slate-500">{job.message}</p>}
        {job.error && <pre className="text-xs text-red-600 whitespace-pre-wrap">{job.error}</pre>}
      </div>

      {job.chapters?.length > 0 && (
        <div className="bg-white rounded-2xl shadow p-4 sm:p-5">
          <h3 className="font-semibold mb-2">📚 시계열 목차</h3>
          <ul className="space-y-1.5">
            {job.chapters.map((c, i) => (
              <li key={i} className="text-sm">
                <span className="text-slate-400 font-mono mr-2">{c.time}</span>
                <span className="font-medium">{c.title}</span>
                {c.summary && <span className="text-slate-500"> — {c.summary}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="bg-white rounded-2xl shadow p-4 sm:p-5">
        <h3 className="font-semibold mb-3">📦 산출물</h3>
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {job.artifacts.map((a) => (
            <li key={a.filename} className="border border-slate-200 rounded-xl p-3 flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-medium truncate">{ARTIFACT_LABEL[a.kind] || a.kind}</p>
                <p className="text-[11px] text-slate-500 truncate">{a.filename} · {fmtSize(a.size_bytes)}</p>
              </div>
              <div className="flex gap-1 shrink-0">
                {a.filename.endsWith('.html') && (
                  <button
                    onClick={() => previewHtml(a.filename, a.kind)}
                    className="text-xs px-2 py-1 rounded bg-slate-100 hover:bg-slate-200"
                  >미리보기</button>
                )}
                <a
                  href={api.fileUrl(jobId, a.filename)}
                  download
                  className="text-xs px-2 py-1 rounded bg-slate-900 text-white"
                >다운로드</a>
              </div>
            </li>
          ))}
        </ul>
      </div>

      {preview && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-end sm:items-center justify-center p-2 sm:p-6"
             onClick={() => setPreview(null)}>
          <div className="bg-white rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden flex flex-col"
               onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-3 border-b">
              <span className="text-sm font-medium">{ARTIFACT_LABEL[preview.kind]} 미리보기</span>
              <div className="flex gap-2">
                <button
                  onClick={async () => { await navigator.clipboard.writeText(preview.html); alert('HTML이 클립보드에 복사되었습니다.') }}
                  className="text-xs px-2 py-1 rounded bg-slate-100"
                >HTML 복사</button>
                <button onClick={() => setPreview(null)} className="text-xs px-2 py-1 rounded bg-slate-900 text-white">닫기</button>
              </div>
            </div>
            <iframe className="flex-1 w-full" srcDoc={preview.html} title="preview" />
          </div>
        </div>
      )}
    </div>
  )
}

function fmtSize(n: number | null): string {
  if (!n) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`
}
