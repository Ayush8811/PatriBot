/** Server components: who is signed in (for the header). Server only. */
import { cookies } from "next/headers";

import { readAuthConfig, SESSION_COOKIE } from "./config";
import { authStateFromToken, type AuthState } from "./session";

export async function getViewer(): Promise<AuthState> {
  const store = await cookies();
  return authStateFromToken(store.get(SESSION_COOKIE)?.value, readAuthConfig());
}
