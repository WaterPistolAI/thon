import { getLLMText, source } from '@/lib/source';
import redis from '@/lib/redis';

const CACHE_KEY = 'llms:txt:full';
const CACHE_TTL = 600;

export const revalidate = false;

export async function GET() {
  try {
    const cached = await redis.get(CACHE_KEY);
    if (cached) return new Response(cached);
  } catch {
    // Redis unavailable — fall through to compute
  }

  const scan = source.getPages().map(getLLMText);
  const scanned = await Promise.all(scan);
  const content = scanned.join('\n\n');

  try {
    await redis.setex(CACHE_KEY, CACHE_TTL, content);
  } catch {
    // Redis unavailable — continue without caching
  }

  return new Response(content);
}
