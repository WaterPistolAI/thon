"use client";

import { trackAppRouter } from "@socialgouv/matomo-next";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect } from "react";

const MATOMO_URL = process.env.NEXT_PUBLIC_MATOMO_URL;
const MATOMO_SITE_ID = process.env.NEXT_PUBLIC_MATOMO_SITE_ID;
const MATOMO_DOMAINS = process.env.NEXT_PUBLIC_MATOMO_DOMAINS;

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
      debug: process.env.NODE_ENV === "development",
      onInitialization: () => {
        const _paq = (window as unknown as { _paq: unknown[][] })._paq || [];
        _paq.push(["setDocumentTitle", document.domain + "/" + document.title]);
        if (MATOMO_DOMAINS) {
          _paq.push(["setDomains", MATOMO_DOMAINS.split(",").map((d) => d.trim())]);
          _paq.push(["enableCrossDomainLinking"]);
        }
        _paq.push(["setDoNotTrack", true]);
      },
    });
  }, [pathname, searchParams]);

  return null;
}
