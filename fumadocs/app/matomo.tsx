"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect } from "react";

declare global {
  interface Window {
    _paq: unknown[][];
  }
}

const MATOMO_URL = process.env.NEXT_PUBLIC_MATOMO_URL;
const MATOMO_SITE_ID = process.env.NEXT_PUBLIC_MATOMO_SITE_ID;

export function MatomoSpaTracker() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (!MATOMO_URL || !MATOMO_SITE_ID) return;
    const _paq = (window._paq = window._paq || []);
    _paq.push(["setCustomUrl", pathname + (searchParams?.toString() ? `?${searchParams.toString()}` : "")]);
    _paq.push(["trackPageView"]);
  }, [pathname, searchParams]);

  return null;
}
