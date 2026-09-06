// AUTH.md §10: the Firebase JS SDK is loaded on the login page only. It
// holds an ID token for the few seconds between sign-in and exchange, then
// signOut() clears it — no other route imports this module.
import {
  GoogleAuthProvider,
  getAuth,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
} from "firebase/auth";
import { initializeApp, getApps } from "firebase/app";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

function firebaseApp() {
  return getApps()[0] ?? initializeApp(firebaseConfig);
}

/** Signs in, returns the ID token, then immediately signs back out — the
 * token only needs to survive long enough to reach POST /auth/session
 * (AUTH.md §10: "the browser never holds a token in JavaScript" after
 * login). */
async function exchangeAndSignOut(
  signIn: (
    auth: ReturnType<typeof getAuth>,
  ) => Promise<{ user: { getIdToken(): Promise<string> } }>,
): Promise<string> {
  const auth = getAuth(firebaseApp());
  const credential = await signIn(auth);
  const idToken = await credential.user.getIdToken();
  await signOut(auth);
  return idToken;
}

export async function signInWithEmailPassword(
  email: string,
  password: string,
): Promise<string> {
  return exchangeAndSignOut((auth) =>
    signInWithEmailAndPassword(auth, email, password),
  );
}

export async function signInWithGoogle(): Promise<string> {
  return exchangeAndSignOut((auth) =>
    signInWithPopup(auth, new GoogleAuthProvider()),
  );
}
