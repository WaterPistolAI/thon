import { getLLMText, getPageMarkdownUrl, source } from '@/lib/source';
import { notFound } from 'next/navigation';
import redis from '@/lib/redis';

const CACHE_TTL = 600;

export const revalidate = false;

export async function GET(_req: Request, { params }: RouteContext<'/llms.mdx/docs/[[...slug]]'>) {
  const { slug } = await params;
  const page = source.getPage(slug?.slice(0, -1));
  if (!page) notFound();

  const cacheKey = `llms:mdx:${page.slugs.join('/')}`;

  try {
    const cached = await redis.get(cacheKey);
    if (cached) {
      return new Response(cached, {
        headers: { 'Content-Type': 'text/markdown' },
      });
    }
  } catch {
    // Redis unavailable — fall through to compute
  }

  const content = await getLLMText(page);

  try {
    await redis.setex(cacheKey, CACHE_TTL, content);
  } catch {
    // Redis unavailable — continue without caching
  }

  return new Response(content, {
    headers: {
      'Content-Type': 'text/markdown',
    },
  });
}

export function generateStaticParams() {
  return source.getPages().map((page) => ({
    lang: page.locale,
    slug: getPageMarkdownUrl(page).segments,
  }));
}
