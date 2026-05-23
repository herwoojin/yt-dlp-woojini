# ERD — yt-dlp web app

> Entity Relationship / Data Model
> 마지막 갱신: 2026-05-20

## 1. 개요

이 프로젝트는 **단일 사용자 가정 + 로컬 파일 시스템 저장**이라 전통적 RDBMS가 없습니다. 데이터는 두 곳에 분산:

1. **로컬 디스크** (`~/yt-dlp-downloads/<job_id>/`) — 영상, 산출물, 잡 메타
2. **in-memory** (`JobRegistry._jobs: dict[str, JobInfo]`) — 부팅 시 디스크에서 복원

향후 다중 사용자/동기화가 필요하면 Firestore를 추가하는 것이 자연스러운 진화 경로 (TRD 참고).

## 2. 엔터티 다이어그램

```
┌──────────────────────────┐         ┌──────────────────────────┐
│         User             │         │         Job              │
│ (Firebase 인증 주체)      │         │ (작업 1개)                 │
├──────────────────────────┤         ├──────────────────────────┤
│ uid (PK)        string   │ 1     N │ id (PK)         string   │
│ email           string?  │─────────│ owner_uid (FK)  string?  │
│ display_name    string?  │         │ url             string   │
│ photo_url       string?  │         │ title           string?  │
└──────────────────────────┘         │ status          enum     │
                                      │ quality         enum     │
        ┌────────────────┐            │ video_format    string   │
        │   Settings     │            │ progress        float    │
        │ (싱글톤, 키-값)  │            │ message         string?  │
        ├────────────────┤            │ error           string?  │
        │ download_dir   │            │ duration_secs   int?     │
        │ default_model  │            │ created_at      datetime │
        │ pro_model      │            │ updated_at      datetime │
        │ telegram_on    │            └─────────┬────────────────┘
        └────────────────┘                      │ 1
                                                │
                                                │ N
                                      ┌─────────▼────────────────┐
                                      │      Artifact            │
                                      │ (잡당 산출 파일들)         │
                                      ├──────────────────────────┤
                                      │ kind (PK part)  string   │
                                      │ filename        string   │
                                      │ size_bytes      int?     │
                                      └──────────────────────────┘

                                      ┌──────────────────────────┐
                                      │      Chapter             │
                                      │ (잡당 시계열 목차, 1:N)    │
                                      ├──────────────────────────┤
                                      │ time   string (HH:MM:SS) │
                                      │ title  string            │
                                      │ summary string           │
                                      └──────────────────────────┘
```

## 3. 엔터티 상세

### 3.1 User
Firebase Authentication이 관리. 백엔드는 ID 토큰만 검증.

| 필드 | 타입 | 비고 |
|------|------|------|
| `uid` | string | Firebase UID. 잡의 `owner_uid` 외래키 |
| `email` | string? | 본인 식별용 |
| `display_name` | string? | UI 헤더 표시 |
| `photo_url` | string? | (현재 미사용) |

저장 위치: **Firebase** (백엔드는 캐시 안 함)

### 3.2 Job
파이프라인의 1회 실행. 등록 → 다운로드 → 자막 → Gemini 4종 → 완료.

| 필드 | 타입 | 제약 | 비고 |
|------|------|------|------|
| `id` | string | PK, 12자 hex | `uuid.uuid4().hex[:12]` |
| `owner_uid` | string? | FK → User.uid | 텔레그램은 `"tg:<chat_id>"` 형식 |
| `url` | string | not null | YouTube URL (다른 yt-dlp 지원 사이트도 가능) |
| `title` | string? | | 다운로드 후 채움 |
| `status` | enum | not null | `pending, downloading, transcribing, generating, done, failed` |
| `quality` | enum | not null | `flash, pro` |
| `video_format` | string | not null | yt-dlp format selector (기본 `best[ext=mp4]/best`) |
| `progress` | float | 0.0~1.0 | UI 프로그레스바용 |
| `message` | string? | | 현재 단계 설명 (한국어) |
| `error` | string? | | 실패 시 traceback |
| `duration_seconds` | int? | | 영상 길이 |
| `created_at` | datetime | not null | UTC |
| `updated_at` | datetime | not null | UTC, 매 단계 갱신 |
| `artifacts` | Artifact[] | | 산출물 목록 (임베디드) |
| `chapters` | Chapter[] | | 시계열 목차 (임베디드) |

저장 위치: **로컬 디스크** `~/yt-dlp-downloads/<id>/job.json`
in-memory: `JobRegistry._jobs[id]`

#### 상태 전이

```
pending
  └─→ downloading
        └─→ transcribing
              ├─→ done (자막 없음 → Gemini 건너뜀)
              └─→ generating
                    ├─→ done (정상 완료)
                    └─→ done (Gemini 실패 → 영상/스크립트만 보존)
  └─→ failed (영상 다운로드 자체 실패)
```

### 3.3 Artifact
잡 디렉토리 안의 파일 하나. Job에 임베디드 (별도 테이블 없음).

| 필드 | 타입 | 비고 |
|------|------|------|
| `kind` | string | 종류 식별자. 예: `video`, `subtitle`, `transcript_txt`, `chapters`, `summary_short`, `email_readable`, `blog_long`, `info_json` |
| `filename` | string | 파일명 (디렉토리 제외) |
| `size_bytes` | int? | 바이트 크기 |

| `kind` 값 | 실제 파일 | 생성 단계 |
|-----------|----------|----------|
| `video` | `video.mp4` / `.webm` / `.mkv` | downloader |
| `subtitle` | `video.{ko,en,...}.vtt` | downloader (best-effort) |
| `info_json` | `video.info.json` | downloader |
| `transcript_txt` | `transcript.txt` | transcript |
| `chapters` | `chapters.json` | gemini |
| `summary_short` | `summary_short.html` | gemini |
| `email_readable` | `email_readable.html` | gemini |
| `blog_long` | `blog_long.html` | gemini |

### 3.4 Chapter
시계열 목차 항목. Job에 임베디드.

| 필드 | 타입 | 예시 |
|------|------|------|
| `time` | string (HH:MM:SS) | `"00:01:30"` |
| `title` | string | `"도입 - 강의 소개"` |
| `summary` | string | `"강사가 본 영상의 학습 목표를..."` |

소스: Gemini가 `transcript_timed.txt` 분석 후 JSON 배열로 반환 → `chapters.json`에 저장 + Job에 임베디드.

### 3.5 Settings (싱글톤)
런타임 설정. 백엔드 환경변수 + UI에서 변경 가능한 경로.

| 필드 | 타입 | 출처 |
|------|------|------|
| `download_dir` | string | `runtime_settings.json` > `.env` `DOWNLOAD_DIR` > `~/yt-dlp-downloads` |
| `default_model` | string | `.env` `DEFAULT_GEMINI_MODEL` (read-only via UI) |
| `pro_model` | string | `.env` `PRO_GEMINI_MODEL` (read-only via UI) |
| `telegram_enabled` | bool | `.env` `TELEGRAM_ENABLED` AND `TELEGRAM_BOT_TOKEN` 둘 다 truthy 일 때 true |

저장 위치: `app/runtime_settings.json` (UI 변경 가능 항목만)

## 4. 디스크 레이아웃

```
~/yt-dlp-downloads/                  ← 변경 가능 (Settings.download_dir)
└── <job_id>/                        ← 12자 hex
    ├── video.mp4                    ← 영상 (yt-dlp)
    ├── video.info.json              ← yt-dlp 메타
    ├── video.ko.vtt                 ← 자막 (한국어 우선)
    ├── video.en.vtt                 ← 자막 (영어 fallback)
    ├── transcript.txt               ← 가장 작은 plain text
    ├── transcript_timed.txt         ← Gemini chapters 생성용 (HH:MM:SS 포함)
    ├── chapters.json                ← Gemini 시계열 목차
    ├── summary_short.html           ← Gemini 짧은 요약 HTML
    ├── email_readable.html          ← Gemini 이메일 본문 HTML
    ├── blog_long.html               ← Gemini 블로그/카페 장문 HTML
    └── job.json                     ← 잡 메타 (JobInfo 직렬화)
```

## 5. 파일 포맷 예시

### `job.json`
```json
{
  "id": "633b91852fb2",
  "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
  "title": "Me at the zoo",
  "status": "done",
  "quality": "flash",
  "video_format": "best[ext=mp4]/best",
  "progress": 1.0,
  "message": "완료",
  "error": null,
  "duration_seconds": 19,
  "created_at": "2026-05-18T15:01:52.479948",
  "updated_at": "2026-05-18T15:01:58.214000",
  "owner_uid": "local-dev",
  "artifacts": [
    {"kind": "video", "filename": "video.mp4", "size_bytes": 629172},
    {"kind": "subtitle", "filename": "video.en.vtt", "size_bytes": 440},
    {"kind": "transcript_txt", "filename": "transcript.txt", "size_bytes": 217},
    {"kind": "chapters", "filename": "chapters.json", "size_bytes": 412}
  ],
  "chapters": [
    {"time": "00:00:00", "title": "도입", "summary": "동물원 방문 소개"},
    {"time": "00:00:10", "title": "코끼리 묘사", "summary": "긴 코의 특징 언급"}
  ]
}
```

### `chapters.json`
```json
[
  {"time": "00:00:00", "title": "도입", "summary": "..."},
  {"time": "00:01:30", "title": "본론 1", "summary": "..."}
]
```

### `runtime_settings.json`
```json
{
  "download_dir": "/Users/heoujin/yt-dlp-downloads"
}
```

## 6. 데이터 수명 주기

| 데이터 | 생성 | 갱신 | 삭제 |
|--------|------|------|------|
| Job (메타) | `POST /api/jobs` | 워커 단계마다 | 사용자 수동 (현재 UI에 삭제 버튼 없음) |
| 영상 파일 | yt-dlp 완료 시 | 안 함 | 사용자 수동 (`rm -rf ~/yt-dlp-downloads/<id>`) |
| 자막 파일 | yt-dlp 자막 패스 | 안 함 | 동일 |
| Gemini HTML | Gemini 단계 완료 시 | 안 함 | 동일 |
| Settings | `PUT /api/settings` | UI 저장 | `runtime_settings.json` 삭제 시 `.env` 값 fallback |

자동 삭제/정리 정책은 MVP 밖. 향후 옵션: 30일 이상 된 잡 자동 archive, 일정 용량 초과 시 LRU 삭제 등.

## 7. 동시성

- **잡 워커**: 단일 (`asyncio.Queue` 순차 처리)
- **HTTP**: uvicorn 다중 worker는 안 씀 (단일 프로세스, asyncio)
- **텔레그램 봇**: 별도 스레드, `asyncio.run_coroutine_threadsafe`로 메인 루프와 통신
- **레이스 컨디션**: `JobRegistry._update()`는 `asyncio.Lock` 보호

## 8. 마이그레이션 / 확장 시나리오

### 다중 사용자 → Firestore 추가
1. `Job.owner_uid`는 이미 존재 → 그대로 사용
2. `JobRegistry._persist()`에 Firestore write 추가
3. `JobRegistry._load_from_disk()` 대체 → Firestore query
4. 영상 파일은 여전히 로컬 (사용자별 디렉토리 분리)

### 잡 병렬화
1. `JobRegistry._queue` → `asyncio.TaskGroup`
2. 동시 실행 수 제한 (`asyncio.Semaphore(2)`)
3. yt-dlp / Gemini rate limit 주의

### 클라우드 저장으로 이전 (Firebase Storage)
1. `services/storage.py` 추상화 (현재 로컬 경로 → 인터페이스 분리)
2. 다운로드 URL은 Storage SDK로 서명된 URL 생성
3. `/api/files` 엔드포인트 → 리다이렉트
