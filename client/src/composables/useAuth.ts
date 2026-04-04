/**
 * @fileoverview Composable for optional OAuth2 authentication.
 * Checks ``/auth/me`` on first call to determine whether auth is
 * enabled and whether the current user has a valid session.
 */

import { ref } from 'vue'

export interface AuthUser {
  sub: string
  name: string
  email: string
  picture?: string
}

/**
 * Composable that manages authentication state.
 *
 * When auth is disabled on the server the app renders normally.
 * When auth is enabled and the user has no session, the browser
 * is redirected to the server-side login flow.
 */
export function useAuth() {
  const user = ref<AuthUser | null>(null)
  const isAuthenticated = ref(false)
  const isAuthEnabled = ref(false)
  const isCheckingAuth = ref(true)

  const apiBase = import.meta.env.VITE_API_URL || ''

  /** Check the current session with the server. */
  async function checkAuth(): Promise<void> {
    try {
      const res = await fetch(`${apiBase}/auth/me`)

      if (res.ok) {
        const data = await res.json()
        if (data.enabled === false) {
          // Auth is not configured — everyone is allowed in.
          isAuthEnabled.value = false
          isAuthenticated.value = true
        } else {
          // Auth is enabled and the session is valid.
          isAuthEnabled.value = true
          isAuthenticated.value = true
          user.value = {
            sub: data.sub,
            name: data.name,
            email: data.email,
            picture: data.picture,
          }
        }
      } else if (res.status === 401) {
        // Auth is enabled but there is no valid session — redirect.
        isAuthEnabled.value = true
        isAuthenticated.value = false
        window.location.href = `${apiBase}/auth/login`
        return
      }
    } catch {
      // Network error or server unavailable — assume no auth.
      isAuthEnabled.value = false
      isAuthenticated.value = true
    }

    isCheckingAuth.value = false
  }

  /** Sign out via POST to prevent CSRF-based forced logout. */
  function logout(): void {
    const form = document.createElement('form')
    form.method = 'POST'
    form.action = `${apiBase}/auth/logout`
    document.body.appendChild(form)
    form.submit()
  }

  return {
    user,
    isAuthenticated,
    isAuthEnabled,
    isCheckingAuth,
    checkAuth,
    logout,
  }
}
