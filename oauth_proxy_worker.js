/**
 * MUTXRI OAuth proxy - Cloudflare Worker
 * Route: mutxriterminal.com/api/auth/oauth/*
 * Forwards Google/GitHub OAuth callbacks to the Render backend so the
 * redirect URI lives on the authorized domain (mutxriterminal.com).
 */
export default {
  async fetch(request) {
    const url = new URL(request.url);
    const target = 'https://mutxri-terminal.onrender.com' + url.pathname + url.search;
    const init = {
      method: request.method,
      headers: request.headers,
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
      redirect: 'manual', // pass 302s through untouched
    };
    const resp = await fetch(target, init);
    return new Response(resp.body, {
      status: resp.status,
      statusText: resp.statusText,
      headers: resp.headers,
    });
  },
};
