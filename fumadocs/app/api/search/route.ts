import { source } from '@/lib/source';
import { createFromSource } from 'fumadocs-core/search/server';
import redis from '@/lib/redis';

const CACHE_KEY = 'search:index';
const CACHE_TTL = 300;

const { GET: originalGET } = createFromSource(source, {
  language: 'english',
});

export async function GET(request: Request) {
  try {
    const cached = await redis.get(CACHE_KEY);
    if (cached) {
      return new Response(cached, {
        headers: { 'Content-Type': 'application/json' },
      });
    }
  } catch {
    // Redis unavailable — fall through to compute
  }

  const response = await originalGET(request);
  const body = await response.text();

  try {
    await redis.setex(CACHE_KEY, CACHE_TTL, body);
  } catch {
    // Redis unavailable — continue without caching
  }

  return new Response(body, {
    headers: { 'Content-Type': 'application/json' },
  });
}
