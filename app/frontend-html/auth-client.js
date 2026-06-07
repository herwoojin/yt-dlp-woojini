// 공용 Firebase 인증(구글 로그인) 모듈 — index/blog-studio/reference-images 가 공유.
// 로그인하면 ID 토큰을 백엔드(fly.dev)에 Authorization 헤더로 보내 사용자별로 격리된다.
//
// 동적 import + 실패 시 무력화: Firebase CDN 로드가 실패해도 앱 본체는 절대 깨지지 않게 한다.
const firebaseConfig = {
  apiKey: "AIzaSyBihEFte-LokFjx4p5b8ahhngjvIHIR4Wg",
  authDomain: "poetic-sentinel-468112-a1.firebaseapp.com",
  projectId: "poetic-sentinel-468112-a1",
  appId: "1:608400359125:web:bb5eed2582431e74d46c5c",
};

let _auth = null;
let _login = null;
let _logout = null;
let _onUser = null;

const _ready = (async () => {
  try {
    const V = "https://www.gstatic.com/firebasejs/10.13.2";
    const appMod = await import(`${V}/firebase-app.js`);
    const authMod = await import(`${V}/firebase-auth.js`);
    const app = appMod.initializeApp(firebaseConfig);
    _auth = authMod.getAuth(app);
    authMod.setPersistence(_auth, authMod.browserLocalPersistence).catch(() => {});
    const provider = new authMod.GoogleAuthProvider();
    _login = () => authMod.signInWithPopup(_auth, provider);
    _logout = () => authMod.signOut(_auth);
    _onUser = (cb) => authMod.onAuthStateChanged(_auth, cb);
  } catch (e) {
    console.warn("Firebase 로드 실패 — 구글 로그인 비활성화", e);
  }
})();

export async function loginWithGoogle() {
  await _ready;
  if (!_login) throw new Error("로그인 모듈을 불러오지 못했습니다 (네트워크 확인)");
  return _login();
}
export async function logout() {
  await _ready;
  if (_logout) return _logout();
}
export async function onUser(cb) {
  await _ready;
  if (_onUser) _onUser(cb);
  else cb(null);  // Firebase 미로드 시 비로그인 상태로 콜백
}
export function currentUser() {
  return _auth ? _auth.currentUser : null;
}

// ── Gemini API 키를 로그인 사용자(uid)별로 분리 저장 ──
// 같은 브라우저라도 계정마다 자기 키를 쓰게 한다. 비로그인 시 'anon'.
function geminiKeyName() {
  const u = _auth && _auth.currentUser;
  return u ? `ytdlp_gemkey_${u.uid}` : "ytdlp_gemkey_anon";
}
export function getGeminiKey() {
  try { return localStorage.getItem(geminiKeyName()) || ""; } catch (_) { return ""; }
}
export function setGeminiKey(k) {
  try { localStorage.setItem(geminiKeyName(), (k || "").trim()); } catch (_) {}
}
export async function getIdTokenOrNull() {
  await _ready;
  const u = _auth && _auth.currentUser;
  if (!u) return null;
  try { return await u.getIdToken(); } catch (_) { return null; }
}
