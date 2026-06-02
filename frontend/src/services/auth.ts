import { auth } from "./firebase";

export async function getCurrentSessionToken(): Promise<string | null> {
  return auth.currentUser?.getIdToken() ?? null;
}
