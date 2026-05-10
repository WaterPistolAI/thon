"use client";

import Script from "next/script";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect } from "react";

declare global {
  interface Window {
    _paq: unknown[][];
  }
}

const MATOMO_URL = process.env.NEXT_PUBLIC_MATOMO_URL;
const MATOMO_SITE_ID = process.env.NEXT_PUBLIC_MATOMO_SITE_ID;
const MATOMO_DOMAINS = process.env.NEXT_PUBLIC_MATOMO_DOMAINS;

function buildInitScript(): string {
  const domainsPart = MATOMO_DOMAINS
    ? `_paq.push(["setDomains", ${JSON.stringify(MATOMO_DOMAINS.split(",").map((d) => d.trim()))}]); _paq.push(["enableCrossDomainLinking"]);`
    : "";
  return `
  var _paq = window._paq = window._paq || [];
  _paq.push(["setDocumentTitle", document.domain + "/" + document.title]);
  ${domainsPart}
  _paq.push(["setDoNotTrack", true]);
  _paq.push(["trackPageView"]);
  _paq.push(["enableLinkTracking"]);
  _paq.push(["setTrackerUrl", ${JSON.stringify(MATOMO_URL ?? "")}matomo.php]);
  _paq.push(["setSiteId", ${JSON.stringify(MATOMO_SITE_ID ?? "")}]);
  `;
}

function MatomoSpaTracker() {
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

export function MatomoAnalytics() {
  if (!MATOMO_URL || !MATOMO_SITE_ID) return null;

  return (
    <>
      <Script id="matomo-init" strategy="afterInteractive">
        {buildInitScript()}
      </Script>
      <Script src={`${MATOMO_URL}matomo.js`} strategy="afterInteractive" />
      <MatomoSpaTracker />
    </>
  );
}
