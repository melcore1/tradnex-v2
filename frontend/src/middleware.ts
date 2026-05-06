import { NextResponse, type NextRequest } from 'next/server'

/**
 * Auth guard. Public routes (login + Next internals) bypass the check.
 * For everything else, verify the session cookie by hitting
 * /api/auth/me server-side. Bad cookie → redirect to /login + clear it.
 *
 * The cookie is HttpOnly so client-side JS can't introspect it; this
 * middleware is the only place it gets validated before page render.
 */

const PUBLIC_PATHS = new Set<string>(['/login'])

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl

  if (PUBLIC_PATHS.has(pathname)) {
    return NextResponse.next()
  }

  const cookieName = process.env.SESSION_COOKIE_NAME ?? 'tradnex_session'
  const cookie = req.cookies.get(cookieName)

  if (!cookie) {
    const url = new URL('/login', req.url)
    return NextResponse.redirect(url)
  }

  const apiBase = process.env.API_INTERNAL_URL ?? 'http://api:8080'
  try {
    const verify = await fetch(`${apiBase}/api/auth/me`, {
      headers: { Cookie: `${cookieName}=${cookie.value}` },
      cache: 'no-store',
    })
    if (verify.status !== 200) {
      const res = NextResponse.redirect(new URL('/login', req.url))
      res.cookies.delete(cookieName)
      return res
    }
  } catch {
    // Network error reaching the API — let the page through and let the
    // client-side fetch fail loudly. Failing closed (redirecting) here
    // would log out users every time the API is briefly unreachable.
    return NextResponse.next()
  }

  return NextResponse.next()
}

export const config = {
  // Run on every page route except Next internals, the API itself, and static.
  matcher: ['/((?!_next/|favicon|api/|public/).*)'],
}
