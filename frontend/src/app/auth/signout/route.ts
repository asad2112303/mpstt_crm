import { cookies } from "next/headers";
import { NextResponse, type NextRequest } from "next/server";

/**
 * Server-side sign out.
 *
 * The session cookie is written by the server (see `proxy.ts`), so only the
 * server can reliably remove it — a browser-side `signOut()` may delete a
 * cookie with different attributes and leave the original in place, after
 * which `/login` immediately redirects back to `/dashboard` and the user
 * appears stuck.
 *
 * The cookies are cleared directly rather than through the Supabase client:
 * that client refreshes and re-writes the session while it works, which would
 * emit a competing `Set-Cookie` for the same name. Token revocation is
 * attempted client-side before this route is reached; access tokens expire
 * within the hour regardless.
 */
async function signOutAndRedirect(request: NextRequest) {
  const response = NextResponse.redirect(new URL("/login", request.url), {
    status: 303,
  });

  const cookieStore = await cookies();
  for (const cookie of cookieStore.getAll()) {
    // Covers the session cookie and its chunked variants (…auth-token.0/.1).
    if (cookie.name.startsWith("sb-")) {
      response.cookies.set(cookie.name, "", { path: "/", maxAge: 0 });
    }
  }
  return response;
}

export async function GET(request: NextRequest) {
  return signOutAndRedirect(request);
}

export async function POST(request: NextRequest) {
  return signOutAndRedirect(request);
}
