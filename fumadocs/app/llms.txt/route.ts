import { source } from '@/lib/source';
import { llms } from 'fumadocs-core/source';
import redis from '@/lib/redis';

const CACHE_KEY = 'llms:txt:index';
const CACHE_TTL = 600;

export const revalidate = false;

export async function GET() {
  try {
    const cached = await redis.get(CACHE_KEY);
    if (cached) return new Response(cached);
  } catch {
    // Redis unavailable — fall through to compute
  }

  const content = llms(source).index();

  try {
    await redis.setex(CACHE_KEY, CACHE_TTL, content);
  } catch {
    // Redis unavailable — continue without caching
  }

  return new Response(content);
}
