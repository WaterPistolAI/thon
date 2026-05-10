"use client";

import { trackAppRouter } from "@socialgouv/matomo-next";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect } from "react";

declare global {
  interface Window {
    _paq: unknown[][];
  }
}

const MATOMO_URL = process.env.NEXT_PUBLIC_MATOMO_URL;
const MATOMO_SITE_ID = process.env.NEXT_PUBLIC_MATOMO_SITE_ID;

export function MatomoAnalytics() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (!MATOMO_URL || !MATOMO_SITE_ID) return;

    trackAppRouter({
      url: MATOMO_URL,
      siteId: MATOMO_SITE_ID,
      pathname,
      searchParams,
      disableCookies: true,
      onInitialization: () => {
        const _paq = (window._paq = window._paq || []);
        _paq.push(["setDocumentTitle", document.domain + "/" + document.title]);
        _paq.push(["setDomains", ["*.thon.waterpistol.co", "*.thon.waterpistol.co"]]);
        _paq.push(["enableCrossDomainLinking"]);
        _paq.push(["setDoNotTrack", true]);
      },
    });
  }, [pathname, searchParams]);

  return null;
}
