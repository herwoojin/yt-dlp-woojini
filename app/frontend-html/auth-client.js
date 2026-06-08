// 공용 Firebase 인증(구글 로그인) + Gemini 키 계정별(uid) 동기화 모듈.
// - 로그인하면 ID 토큰을 백엔드(fly.dev)에 Authorization 헤더로 보내 사용자별로 격리.
// - Gemini 키는 Firestore users/{uid}.gemini_key 에 저장 → 어느 기기에서 로그인해도 따라옴.
//   (localStorage 는 빠른 동기 조회용 캐시. 로그인 시 Firestore→캐시로 동기화)
// 동적 import + 실패 시 무력화: CDN/Firestore 로드가 실패해도 앱 본체는 안 깨진다.
const firebaseConfig = {
  apiKey: "AIzaSyBihEFte-LokFjx4p5b8ahhngjvIHIR4Wg",
  authDomain: "poetic-sentinel-468112-a1.firebaseapp.com",
  projectId: "poetic-sentinel-468112-a1",
  appId: "1:608400359125:web:bb5eed2582431e74d46c5c",
};

let _auth = null;
let _login = null;
let _logout = null;
let _onUserRaw = null;
let _db = null;
let _fs = null;  // { doc, getDoc, setDoc }

const _ready = (async () => {
  try {
    const V = "https://www.gstatic.com/firebasejs/10.13.2";
    const appMod = await import(`${V}/firebase-app.js`);
    const authMod = await import(`${V}/firebase-auth.js`);
    const app = appMod.initializeApp(firebaseConfig);
    _auth = authMod.getAuth(app);
    authMod.setPersistence(_auth, authMod.browserLocalPersistence).catch(() => {});
    const provider = new authMod.GoogleAuthProvider();
    // 팝업은 COOP(Cross-Origin-Opener-Policy)로 막혀 튕기는 경우가 많아 리디렉트 방식 사용.
    _login = () => authMod.signInWithRedirect(_auth, provider);
    _logout = () => authMod.signOut(_auth);
    _onUserRaw = (cb) => authMod.onAuthStateChanged(_auth, cb);
    // 리디렉트로 돌아온 직후 결과 처리(에러 로깅용). 로그인 자체는 onAuthStateChanged가 처리.
    authMod.getRedirectResult(_auth).catch((e) => console.warn("redirect login result", e));
    // Firestore (키 동기화용) — 실패해도 localStorage-only 로 동작
    try {
      const fsMod = await import(`${V}/firebase-firestore.js`);
      _db = fsMod.getFirestore(app);
      _fs = { doc: fsMod.doc, getDoc: fsMod.getDoc, setDoc: fsMod.setDoc };
    } catch (e) {
      console.warn("Firestore 로드 실패 — 키는 이 기기에만 저장됨", e);
    }
  } catch (e) {
    console.warn("Firebase 로드 실패 — 구글 로그인 비활성화", e);
  }
})();

function geminiKeyName(uid) {
  const u = uid || (_auth && _auth.currentUser && _auth.currentUser.uid);
  return u ? `ytdlp_gemkey_${u}` : "ytdlp_gemkey_anon";
}

// 로그인 시: Firestore의 키를 캐시에 동기화(원격 우선). 원격이 비고 로컬에 있으면 업로드(이전).
async function _syncKeyFromFirestore(uid) {
  if (!_db || !_fs || !uid) return;
  const lsName = geminiKeyName(uid);
  try {
    const ref = _fs.doc(_db, "users", uid);
    const snap = await _fs.getDoc(ref);
    const remote = snap.exists() ? (snap.data().gemini_key || "") : "";
    const local = localStorage.getItem(lsName) || "";
    if (remote) {
      localStorage.setItem(lsName, remote);          // 다른 기기에서 저장한 키를 가져옴
    } else if (local) {
      await _fs.setDoc(ref, { gemini_key: local }, { merge: true });  // 기존 키 이전
    }
  } catch (e) {
    console.warn("Gemini 키 동기화 실패", e);
  }
}

export const auth = () => _auth;
export async function loginWithGoogle() {
  await _ready;
  if (!_login) throw new Error("로그인 모듈을 불러오지 못했습니다 (네트워크 확인)");
  return _login();
}
export async function logout() {
  await _ready;
  if (_logout) return _logout();
}
// 콜백 호출 전에 Firestore 키를 캐시에 동기화한 뒤 cb(user) 실행
export async function onUser(cb) {
  await _ready;
  if (!_onUserRaw) { cb(null); return; }
  _onUserRaw(async (user) => {
    if (user) { await _syncKeyFromFirestore(user.uid); }
    cb(user);
  });
}
export function currentUser() {
  return _auth ? _auth.currentUser : null;
}

// 현재 로그인 사용자의 ID 토큰(없으면 null). api() 가 매 호출 시 백엔드 전송용으로 사용.
export async function getIdTokenOrNull() {
  await _ready;
  const u = _auth && _auth.currentUser;
  if (!u) return null;
  try { return await u.getIdToken(); } catch (_) { return null; }
}

// ── Gemini API 키 (계정별) ──
export function getGeminiKey() {
  try { return localStorage.getItem(geminiKeyName()) || ""; } catch (_) { return ""; }
}
// 캐시 + Firestore 양쪽에 저장. 저장 완료를 기다리려면 await.
export async function setGeminiKey(k) {
  const val = (k || "").trim();
  try { localStorage.setItem(geminiKeyName(), val); } catch (_) {}
  const u = _auth && _auth.currentUser;
  if (u && _db && _fs) {
    try {
      await _fs.setDoc(_fs.doc(_db, "users", u.uid), { gemini_key: val }, { merge: true });
    } catch (e) {
      console.warn("Gemini 키 Firestore 저장 실패(이 기기에는 저장됨)", e);
    }
  }
}
