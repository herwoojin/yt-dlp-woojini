import { signIn, isInsecure } from '../firebase'

export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm bg-white rounded-2xl shadow-lg p-8 text-center space-y-4">
        <div className="text-5xl">🎬</div>
        <h1 className="text-xl font-bold">yt-dlp web app</h1>
        <p className="text-sm text-slate-500">
          유튜브 URL → 영상 + 자막 + 요약 + 이메일/블로그 HTML 까지 한번에.
        </p>
        <button
          onClick={async () => { await signIn(); onSignedIn() }}
          className="w-full py-3 rounded-xl bg-slate-900 text-white font-medium hover:bg-slate-800 active:scale-[0.99] transition"
        >
          {isInsecure() ? '로컬 개발자 모드로 시작' : 'Google로 로그인'}
        </button>
        {isInsecure() && (
          <p className="text-[11px] text-amber-600">VITE_ALLOW_INSECURE_AUTH=true (로컬 전용)</p>
        )}
      </div>
    </div>
  )
}
