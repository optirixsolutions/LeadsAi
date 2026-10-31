import { type NextRequest, NextResponse } from "next/server";

/**
 * Fast-path redirect to sign-in when there is no session cookie at all. This is only a UX
 * shortcut: the cookie's validity is checked by the API on every request, and server
 * components redirect to /login when the API rejects it.
 */
const PUBLIC_PATHS = [
  "/login",
  "/register",
  "/forgot-password",
  "/reset-password",
  "/verify-email",
  "/invite",
  "/unsubscribe",
];

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return NextResponse.next();
  }
  // Outside development the API sets this with the __Host- prefix.
  if (request.cookies.has("salesiq_session") || request.cookies.has("__Host-salesiq_session")) {
    return NextResponse.next();
  }

  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname + search)}`;
  return NextResponse.redirect(url);
}

export const config = {
  // Skip API passthrough, Next internals, and static files.
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico|.*\\.[a-z0-9]+$).*)"],
};
