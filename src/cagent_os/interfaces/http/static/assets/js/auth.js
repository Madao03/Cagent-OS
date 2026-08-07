/**
 * auth.js — shared authentication state for all pages.
 *
 * Responsibilities:
 *   1. Read/write JWT token in localStorage
 *   2. Redirect to /login when no token or token expired
 *   3. Attach `Authorization: Bearer <token>` to all fetch requests
 *   4. Provide get_current_user() for UI rendering (avatar, display name)
 *
 * Usage from any page:
 *   <script src="/static/assets/js/auth.js"></script>
 *   <script>
 *     const user = await Auth.requireUser();  // redirects to /login if missing
 *     const resp = await Auth.fetch('/api/v1/conversations');  // auto-adds header
 *   </script>
 */

window.Auth = (function () {
  "use strict";

  const TOKEN_KEY = "cagentos_jwt";
  const USER_KEY = "cagentos_user";

  // ── Token management ───────────────────────────────────────────

  function getToken() {
    return localStorage.getItem(TOKEN_KEY) || "";
  }

  function setToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
  }

  function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  function getCachedUser() {
    try {
      return JSON.parse(localStorage.getItem(USER_KEY) || "null");
    } catch {
      return null;
    }
  }

  function setCachedUser(user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  // ── API calls ──────────────────────────────────────────────────

  /**
   * Wrapper around fetch() that automatically adds the Authorization header.
   * Use this instead of fetch() for any endpoint that requires auth.
   * On 401, clears the token and redirects to /login.
   */
  async function fetchWithAuth(url, options = {}) {
    const token = getToken();
    const headers = Object.assign({}, options.headers || {});
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    const resp = await fetch(url, Object.assign({}, options, { headers }));
    if (resp.status === 401) {
      clearToken();
      console.warn("[Auth] 401 — token invalid or expired, redirecting to /login");
      // Don't redirect if we're already on /login
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
      }
    }
    return resp;
  }

  /**
   * Validate the current token against the server.
   * Returns the user dict if valid, null if invalid/expired.
   */
  async function fetchCurrentUser() {
    const token = getToken();
    if (!token) return null;
    try {
      const resp = await fetch("/api/v1/auth/me", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) return null;
      const data = await resp.json();
      return data.user || null;
    } catch {
      return null;
    }
  }

  /**
   * Page-guard: returns the current user, or redirects to /login.
   * Use on pages that require authentication (chat / brief / knowledge).
   */
  async function requireUser() {
    let user = getCachedUser();
    if (!user) {
      user = await fetchCurrentUser();
      if (user) setCachedUser(user);
    }
    if (!user) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/login?next=${next}`;
      return null;
    }
    return user;
  }

  /**
   * Logout: call server (no-op if offline) then clear local state and redirect.
   */
  function logout() {
    clearToken();
    window.location.href = "/login";
  }

  /**
   * Render the user into the topbar avatar.
   * Call after requireUser() succeeds.
   */
  function renderUserBadge(user) {
    if (!user) return;
    // Update topbar avatar (any element with class ds-avatar)
    const avatars = document.querySelectorAll(".ds-avatar");
    avatars.forEach((av) => {
      const initial = (user.display_name || user.email || "U").charAt(0).toUpperCase();
      av.textContent = initial;
      av.setAttribute("title", `${user.display_name} <${user.email}>`);
    });
    // Make the avatar clickable → logout
    avatars.forEach((av) => {
      if (av.dataset.authBound === "1") return;
      av.dataset.authBound = "1";
      av.style.cursor = "pointer";
      av.addEventListener("click", () => {
        if (confirm(`Logout as ${user.display_name}?`)) logout();
      });
    });
  }

  /**
   * Check if the current user has admin role.
   */
  function isAdmin() {
    const user = getCachedUser();
    return !!(user && user.role === "admin");
  }

  return {
    getToken,
    setToken,
    clearToken,
    getCachedUser,
    setCachedUser,
    isAdmin,
    fetch: fetchWithAuth,
    fetchCurrentUser,
    requireUser,
    logout,
    renderUserBadge,
  };
})();
