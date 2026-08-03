/**
 * Reverse proxy → Railway whisper-groq-proxy.
 * Hosted on Layero (CDN RU) so Mac client in RF never hits *.up.railway.app / api.groq.com.
 *
 * Note: Layero edge may cut HTTP ~60s — typical Groq whisper replies are well under that.
 */

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const fetchCache = 'force-no-store';
export const revalidate = 0;
export const maxDuration = 300;

const TARGET = (
  process.env.RAILWAY_ORIGIN ||
  'https://whisper-groq-proxy-production.up.railway.app'
).replace(/\/$/, '');

const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailers',
  'transfer-encoding',
  'upgrade',
  'host',
  'content-length',
]);

const DROP_UPSTREAM_CACHE = new Set([
  'age',
  'expires',
  'etag',
  'last-modified',
  'cf-cache-status',
  'x-cache',
  'x-layero-cache',
]);

function buildUpstreamUrl(req) {
  const incoming = new URL(req.url);
  return `${TARGET}${incoming.pathname}${incoming.search}`;
}

function filterRequestHeaders(req) {
  const out = new Headers();
  req.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (HOP_BY_HOP.has(k)) return;
    if (k === 'accept-encoding') return;
    out.set(key, value);
  });
  out.set('x-forwarded-host', req.headers.get('host') || '');
  out.set('x-forwarded-proto', 'https');
  out.set('x-rf-mirror', 'layero');
  out.set('cache-control', 'no-cache');
  out.set('pragma', 'no-cache');
  return out;
}

function rewriteLocation(location) {
  if (!location) return location;
  try {
    const base = new URL(TARGET);
    const u = new URL(location, TARGET);
    if (u.host === base.host) {
      return `${u.pathname}${u.search}${u.hash}`;
    }
  } catch (_) {}
  return location;
}

function cleanSetCookie(value) {
  return String(value || '')
    .replace(/;\s*Domain=[^;]*/gi, '')
    .replace(/;\s*Secure/gi, '; Secure');
}

function applyNoStore(resHeaders) {
  resHeaders.set('cache-control', 'private, no-store, no-cache, must-revalidate, max-age=0');
  resHeaders.set('cdn-cache-control', 'no-store');
  resHeaders.set('surrogate-control', 'no-store');
  resHeaders.set('pragma', 'no-cache');
  resHeaders.set('expires', '0');
  resHeaders.set('vary', 'Cookie, Authorization, Accept-Encoding');
}

function collectSetCookies(upstream) {
  if (typeof upstream.headers.getSetCookie === 'function') {
    return upstream.headers.getSetCookie();
  }
  const single = upstream.headers.get('set-cookie');
  return single ? [single] : [];
}

async function proxy(req) {
  const incoming = new URL(req.url);
  if (incoming.pathname === '/__rf_mirror_health') {
    const h = new Headers();
    applyNoStore(h);
    return Response.json(
      {
        ok: true,
        mirror: 'whisper-groq-proxy-layero',
        target: TARGET,
        ts: new Date().toISOString(),
        no_store: true,
      },
      { headers: h }
    );
  }

  const url = buildUpstreamUrl(req);
  const method = req.method || 'GET';
  const headers = filterRequestHeaders(req);

  const init = {
    method,
    headers,
    redirect: 'manual',
    cache: 'no-store',
    duplex: 'half',
  };

  if (method !== 'GET' && method !== 'HEAD') {
    init.body = req.body;
  }

  let upstream;
  try {
    upstream = await fetch(url, init);
  } catch (err) {
    const h = new Headers();
    applyNoStore(h);
    return Response.json(
      {
        ok: false,
        error: 'rf_mirror_upstream',
        message: String(err && err.message ? err.message : err),
        target: TARGET,
      },
      { status: 502, headers: h }
    );
  }

  const resHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (HOP_BY_HOP.has(k)) return;
    if (DROP_UPSTREAM_CACHE.has(k)) return;
    if (k === 'content-encoding') return;
    if (k === 'cache-control' || k === 'cdn-cache-control' || k === 'surrogate-control' || k === 'pragma') {
      return;
    }
    if (k === 'set-cookie') return;
    if (k === 'location') {
      resHeaders.set('location', rewriteLocation(value));
      return;
    }
    resHeaders.set(key, value);
  });

  for (const raw of collectSetCookies(upstream)) {
    resHeaders.append('set-cookie', cleanSetCookie(raw));
  }

  applyNoStore(resHeaders);

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: resHeaders,
  });
}

const handler = (req) => proxy(req);

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
export const HEAD = handler;
export const OPTIONS = handler;
