import type { JobInfo } from '../api'

const STATUS_COLOR: Record<string, string> = {
  pending: 'bg-slate-200 text-slate-700',
  downloading: 'bg-blue-100 text-blue-700',
  transcribing: 'bg-amber-100 text-amber-700',
  generating: 'bg-purple-100 text-purple-700',
  done: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-red-100 text-red-700',
}

export function JobList({ jobs, onOpen }: { jobs: JobInfo[]; onOpen: (id: string) => void }) {
  if (jobs.length === 0) {
    return (
      <div className="text-center text-sm text-slate-500 py-12">
        아직 작업이 없습니다. 위에 YouTube URL을 붙여넣고 시작해보세요.
      </div>
    )
  }
  return (
    <ul className="space-y-2">
      {jobs.map((j) => (
        <li
          key={j.id}
          onClick={() => onOpen(j.id)}
          className="bg-white rounded-xl shadow-sm p-3 sm:p-4 cursor-pointer hover:shadow-md transition"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="font-medium truncate">{j.title || j.url}</p>
              <p className="text-xs text-slate-500 truncate">{j.url}</p>
              <p className="text-xs text-slate-400 mt-1">{new Date(j.created_at).toLocaleString()}</p>
            </div>
            <span className={`text-xs px-2 py-1 rounded-full shrink-0 ${STATUS_COLOR[j.status] || ''}`}>
              {j.status}
            </span>
          </div>
          {j.status !== 'done' && j.status !== 'failed' && (
            <div className="mt-2 h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
              <div className="h-full bg-slate-900 transition-all" style={{ width: `${Math.round(j.progress * 100)}%` }} />
            </div>
          )}
          {j.message && <p className="text-[11px] text-slate-500 mt-1">{j.message}</p>}
        </li>
      ))}
    </ul>
  )
}
