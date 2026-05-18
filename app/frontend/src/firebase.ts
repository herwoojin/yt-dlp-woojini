import { initializeApp, type FirebaseApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged, type User } from 'firebase/auth'

const insecure = import.meta.env.VITE_ALLOW_INSECURE_AUTH === 'true'

let app: FirebaseApp | null = null
let provider: GoogleAuthProvider | null = null

function ensureApp(): FirebaseApp {
  if (app) return app
  const cfg = {
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
    appId: import.meta.env.VITE_FIREBASE_APP_ID,
  }
  if (!cfg.apiKey) throw new Error('Firebase config 누락 - .env 확인')
  app = initializeApp(cfg)
  provider = new GoogleAuthProvider()
  return app
}

export type AuthUser = { uid: string; email: string | null; displayName: string | null; photoURL: string | null }

export function isInsecure() { return insecure }

export async function signIn(): Promise<AuthUser> {
  if (insecure) return { uid: 'local-dev', email: 'local@dev', displayName: 'Local Dev', photoURL: null }
  ensureApp()
  const cred = await signInWithPopup(getAuth(), provider!)
  return mapUser(cred.user)
}

export async function signOutUser(): Promise<void> {
  if (insecure) return
  ensureApp()
  await signOut(getAuth())
}

export function watchAuth(cb: (user: AuthUser | null) => void): () => void {
  if (insecure) {
    cb({ uid: 'local-dev', email: 'local@dev', displayName: 'Local Dev', photoURL: null })
    return () => {}
  }
  ensureApp()
  return onAuthStateChanged(getAuth(), (u) => cb(u ? mapUser(u) : null))
}

export async function getIdToken(): Promise<string | null> {
  if (insecure) return null
  ensureApp()
  const u = getAuth().currentUser
  if (!u) return null
  return u.getIdToken()
}

function mapUser(u: User): AuthUser {
  return { uid: u.uid, email: u.email, displayName: u.displayName, photoURL: u.photoURL }
}
