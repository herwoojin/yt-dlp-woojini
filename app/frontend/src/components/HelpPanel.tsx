import { useState } from 'react'

type Step = {
  title: string
  body: React.ReactNode
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      className="text-[11px] px-2 py-1 rounded bg-slate-200 hover:bg-slate-300 active:scale-[0.97] shrink-0"
    >
      {copied ? '✓ 복사됨' : '복사'}
    </button>
  )
}

function Code({ children }: { children: string }) {
  return (
    <div className="flex items-center gap-1.5 my-1.5">
      <pre className="flex-1 min-w-0 bg-slate-900 text-slate-100 text-[12px] px-2.5 py-1.5 rounded font-mono overflow-x-auto whitespace-pre-wrap break-all">{children}</pre>
      <CopyButton text={children} />
    </div>
  )
}

function Section({ idx, title, children, open: defaultOpen = false }: { idx: number; title: string; children: React.ReactNode; open?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between gap-2 px-3.5 py-3 bg-slate-50 hover:bg-slate-100 text-left"
      >
        <span className="flex items-center gap-2 min-w-0">
          <span className="w-6 h-6 shrink-0 rounded-full bg-slate-900 text-white text-xs flex items-center justify-center font-semibold">{idx}</span>
          <span className="font-medium text-sm">{title}</span>
        </span>
        <span className="text-slate-400 text-sm shrink-0">{open ? '▾' : '▸'}</span>
      </button>
      {open && <div className="px-3.5 py-3 text-[13px] leading-relaxed text-slate-700 space-y-2">{children}</div>}
    </div>
  )
}

export function HelpPanel({ onClose }: { onClose: () => void }) {
  const sections: Step[] = [
    {
      title: 'Gemini API 키 발급 (5분, 무료)',
      body: (
        <>
          <p>목차/요약/HTML 생성에 사용합니다. 무료 quota 충분합니다.</p>
          <ol className="list-decimal pl-5 space-y-1.5">
            <li>
              <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className="text-blue-600 underline">
                aistudio.google.com/app/apikey
              </a>{' '}
              열기
            </li>
            <li>Google 계정 로그인 → <b>"Create API key"</b> 클릭</li>
            <li>발급된 <code className="bg-slate-100 px-1 rounded">AIzaSy...</code> 키 복사</li>
            <li>맥 터미널에서 <code className="bg-slate-100 px-1 rounded">app/.env</code> 열고 <code className="bg-slate-100 px-1 rounded">GEMINI_API_KEY</code> 값에 붙여넣기</li>
          </ol>
          <p className="mt-2"><b>편집 명령:</b></p>
          <Code>open -a TextEdit /Users/heoujin/yt-dlp/app/.env</Code>
          <p className="text-xs text-slate-500">또는 VS Code: <code className="bg-slate-100 px-1 rounded">code /Users/heoujin/yt-dlp/app/.env</code></p>
        </>
      ),
    },
    {
      title: 'Pro 모드 = Gemini 3 Pro 사용',
      body: (
        <>
          <p>잡 등록 시 <b>"Pro (고품질)"</b> 버튼을 선택하면 Gemini 3 Pro로 처리합니다 (Flash 보다 더 정교한 요약).</p>
          <p>실제 호출되는 모델 ID는 <code className="bg-slate-100 px-1 rounded">.env</code>의 <code className="bg-slate-100 px-1 rounded">PRO_GEMINI_MODEL</code> 값. 기본 <code className="bg-slate-100 px-1 rounded">gemini-3-pro-preview</code>.</p>
          <p className="mt-1.5">호출 시 <b>"400 not found"</b> 가 나면 실제 사용 가능한 ID로 교체:</p>
          <ul className="list-disc pl-5 text-xs space-y-0.5">
            <li><code className="bg-slate-100 px-1 rounded">gemini-3-pro-preview</code> (현재 권장)</li>
            <li><code className="bg-slate-100 px-1 rounded">gemini-3-pro</code></li>
            <li><code className="bg-slate-100 px-1 rounded">gemini-3-pro-latest</code></li>
          </ul>
          <p className="text-[11px] text-slate-500 mt-1.5">
            👉 AI Studio의 <a href="https://aistudio.google.com/" target="_blank" rel="noreferrer" className="text-blue-600 underline">모델 선택 메뉴</a>에서 현재 사용 가능한 정확한 ID 확인 가능
          </p>
        </>
      ),
    },
    {
      title: '텔레그램 봇 활성화 (10분)',
      body: (
        <>
          <p>휴대폰에서 텔레그램으로 YouTube URL 보내기 → 자동 다운로드 + 요약 + 알림.</p>
          <ol className="list-decimal pl-5 space-y-1.5">
            <li>
              텔레그램 앱에서 <a href="https://t.me/BotFather" target="_blank" rel="noreferrer" className="text-blue-600 underline">@BotFather</a> 검색
            </li>
            <li>BotFather 채팅 시작 → <code className="bg-slate-100 px-1 rounded">/newbot</code> 입력</li>
            <li>봇 이름 입력 (예: <i>My yt-dlp helper</i>)</li>
            <li>봇 username 입력 (반드시 <code className="bg-slate-100 px-1 rounded">_bot</code> 끝나야 함, 예: <i>woojini_ytdlp_bot</i>)</li>
            <li>BotFather가 보내준 토큰 <code className="bg-slate-100 px-1 rounded">1234567890:AAAA...</code> 복사</li>
            <li><code className="bg-slate-100 px-1 rounded">app/.env</code>의 <code className="bg-slate-100 px-1 rounded">TELEGRAM_BOT_TOKEN</code> 에 붙여넣기</li>
            <li>백엔드 재시작 (아래 명령)</li>
            <li>봇 채팅창 열고 YouTube URL 전송 → 잠시 후 알림 도착</li>
          </ol>
          <p className="text-[11px] text-slate-500 mt-2">⚠️ 텔레그램 50MB 제한 — 50MB 이하 영상만 봇으로 전송됩니다 (모든 산출물은 어차피 맥 로컬에 저장됨).</p>
        </>
      ),
    },
    {
      title: '백엔드 재시작 (`.env` 바꿨을 때 필수)',
      body: (
        <>
          <p>환경변수 변경 후 백엔드가 새 값을 읽도록 1줄 명령:</p>
          <Code>launchctl kickstart -k gui/$UID/com.user.ytdlp-backend</Code>
          <p>또는 unload/load 방식:</p>
          <Code>{`launchctl unload ~/Library/LaunchAgents/com.user.ytdlp-backend.plist
launchctl load   ~/Library/LaunchAgents/com.user.ytdlp-backend.plist`}</Code>
          <p>재시작 후 확인:</p>
          <Code>curl http://localhost:8000/api/settings</Code>
          <p className="text-[11px] text-slate-500">텔레그램 활성화 됐는지: 응답에서 <code className="bg-slate-100 px-1 rounded">"telegram_enabled": true</code> 확인</p>
        </>
      ),
    },
    {
      title: 'Netlify에 새 URL 반영 (터널 재시작 시)',
      body: (
        <>
          <p>cloudflared quick tunnel URL은 재시작 시 바뀝니다. 현재 활성 URL 확인:</p>
          <Code>bash /Users/heoujin/yt-dlp/app/scripts/get-url.sh</Code>
          <p>Netlify dashboard에서:</p>
          <ol className="list-decimal pl-5 space-y-1">
            <li>Site settings → Environment variables</li>
            <li><code className="bg-slate-100 px-1 rounded">VITE_API_BASE_URL</code> 값을 새 URL로 교체</li>
            <li>Deploys → Trigger deploy → <b>Clear cache and deploy site</b></li>
          </ol>
          <p className="text-[11px] text-slate-500 mt-2">💡 매번 갱신이 귀찮으면 Tailscale 영구 URL로 전환: <code className="bg-slate-100 px-1 rounded">bash app/scripts/setup-anywhere.sh</code> (1회 수동 설정 필요)</p>
        </>
      ),
    },
    {
      title: '문제 해결',
      body: (
        <>
          <ul className="space-y-1.5">
            <li><b>다운로드 실패 (HTTP 429)</b> — YouTube 레이트 리밋. 5~10분 대기 후 재시도.</li>
            <li><b>HTTP 403 Forbidden</b> — IP 차단. Chrome에서 "Get cookies.txt" 확장으로 쿠키 export → <code className="bg-slate-100 px-1 rounded">YT_DLP_COOKIES_FILE</code> 에 경로 지정.</li>
            <li><b>Gemini 400 INVALID_ARGUMENT</b> — API 키 미설정. 위 1번 단계 확인.</li>
            <li><b>Gemini 모델 not found</b> — 위 2번에서 다른 모델 ID로 변경.</li>
            <li><b>봇이 응답 안함</b> — <code className="bg-slate-100 px-1 rounded">tail ~/Library/Logs/ytdlp-backend.err.log</code> 로 에러 확인. 토큰 오타, 백엔드 재시작 누락이 흔함.</li>
            <li><b>전체 로그</b>:</li>
          </ul>
          <Code>{`tail -f ~/Library/Logs/ytdlp-backend.err.log
tail -f ~/Library/Logs/ytdlp-tunnel.err.log`}</Code>
        </>
      ),
    },
  ]

  return (
    <div
      className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center p-2 sm:p-6"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <div>
            <h2 className="font-semibold text-base">🛟 셋업 가이드</h2>
            <p className="text-[11px] text-slate-500">Gemini · 텔레그램 · 백엔드 재시작 — 차례대로 따라하세요</p>
          </div>
          <button onClick={onClose} className="text-xs px-2.5 py-1.5 rounded-lg bg-slate-100">닫기</button>
        </div>
        <div className="flex-1 overflow-y-auto p-3 sm:p-4 space-y-2.5">
          {sections.map((s, i) => (
            <Section key={i} idx={i + 1} title={s.title} open={i === 0}>
              {s.body}
            </Section>
          ))}
          <div className="text-[11px] text-slate-500 pt-2 px-1">
            💡 더 자세한 안내는 레포의 <code className="bg-slate-100 px-1 rounded">README.md</code> 참고
          </div>
        </div>
      </div>
    </div>
  )
}
