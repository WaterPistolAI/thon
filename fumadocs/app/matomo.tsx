"use client";

import Script from "next/script";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState, useCallback } from "react";

declare global {
  interface Window {
    _paq: unknown[][];
  }
}

const MATOMO_URL = process.env.NEXT_PUBLIC_MATOMO_URL;
const MATOMO_SITE_ID = process.env.NEXT_PUBLIC_MATOMO_SITE_ID;
const MATOMO_DOMAINS = process.env.NEXT_PUBLIC_MATOMO_DOMAINS;

const CONSENT_KEY = "matomo_consent_given";

function buildInitScript(): string {
  const domainsPart = MATOMO_DOMAINS
    ? `_paq.push(["setDomains", ${JSON.stringify(MATOMO_DOMAINS.split(",").map((d) => d.trim()))}]); _paq.push(["enableCrossDomainLinking"]);`
    : "";
  const trackerUrl = JSON.stringify((MATOMO_URL ?? "") + "matomo.php");
  const trackerSrc = JSON.stringify((MATOMO_URL ?? "") + "matomo.js");
  return `
var _paq = window._paq = window._paq || [];
_paq.push(["setTrackerUrl", ${trackerUrl}]);
_paq.push(["setSiteId", ${JSON.stringify(MATOMO_SITE_ID ?? "")}]);
_paq.push(["requireConsent"]);
_paq.push(["setDocumentTitle", document.domain + "/" + document.title]);
${domainsPart}
_paq.push(["trackPageView"]);
_paq.push(["enableLinkTracking"]);
var d=document, g=d.createElement("script"), s=d.getElementsByTagName("script")[0];
g.async=true; g.src=${trackerSrc}; s.parentNode.insertBefore(g,s);
`;
}

export function MatomoAnalytics() {
  if (!MATOMO_URL || !MATOMO_SITE_ID) return null;

  useEffect(() => {
    const stored = localStorage.getItem(CONSENT_KEY);
    if (stored === "true") {
      const _paq = (window._paq = window._paq || []);
      _paq.push(["setConsentGiven"]);
    }
  }, []);

  return (
    <Script id="matomo-init" strategy="beforeInteractive">
      {buildInitScript()}
    </Script>
  );
}

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

export function MatomoConsent() {
  const [consentGiven, setConsentGiven] = useState<boolean | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [optedOut, setOptedOut] = useState(false);

  useEffect(() => {
    if (!MATOMO_URL || !MATOMO_SITE_ID) return;
    const stored = localStorage.getItem(CONSENT_KEY);
    if (stored === "true") {
      setConsentGiven(true);
      setDismissed(true);
    } else if (stored === "false") {
      setConsentGiven(false);
      setDismissed(true);
      setOptedOut(true);
    } else {
      setConsentGiven(null);
    }
  }, []);

  const grantConsent = useCallback(() => {
    const _paq = (window._paq = window._paq || []);
    _paq.push(["rememberConsentGiven"]);
    localStorage.setItem(CONSENT_KEY, "true");
    setConsentGiven(true);
    setDismissed(true);
    setOptedOut(false);
  }, []);

  const denyConsent = useCallback(() => {
    localStorage.setItem(CONSENT_KEY, "false");
    setConsentGiven(false);
    setDismissed(true);
    setOptedOut(true);
  }, []);

  const toggleOptOut = useCallback(() => {
    const _paq = (window._paq = window._paq || []);
    if (optedOut) {
      _paq.push(["forgetUserOptOut"]);
      _paq.push(["rememberConsentGiven"]);
      localStorage.setItem(CONSENT_KEY, "true");
      setOptedOut(false);
    } else {
      _paq.push(["forgetConsentGiven"]);
      _paq.push(["optUserOut"]);
      localStorage.setItem(CONSENT_KEY, "false");
      setOptedOut(true);
    }
  }, [optedOut]);

  if (!MATOMO_URL || !MATOMO_SITE_ID) return null;

  if (consentGiven === null && !dismissed) {
    return (
      <div className="fixed bottom-0 inset-x-0 z-50 border-t border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <div className="mx-auto max-w-4xl px-4 py-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            We use anonymized analytics to improve this site. No personal data is collected without your consent.
          </p>
          <div className="flex gap-2 shrink-0">
            <button
              onClick={denyConsent}
              className="rounded-md border border-neutral-300 px-3 py-1.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
            >
              Decline
            </button>
            <button
              onClick={grantConsent}
              className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-neutral-700 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-200"
            >
              Accept
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (dismissed) {
    return (
      <div className="fixed bottom-4 right-4 z-50">
        <button
          onClick={toggleOptOut}
          className="rounded-full border border-neutral-200 bg-white p-2.5 text-neutral-500 shadow-sm transition hover:text-neutral-900 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100"
          title={optedOut ? "Opt in to analytics tracking" : "Opt out of analytics tracking"}
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
            {optedOut ? (
              <>
                <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z" />
                <path d="M2 12h20" />
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" stroke="currentColor" strokeWidth={2} />
              </>
            ) : (
              <>
                <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z" />
                <path d="M2 12h20" />
                <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
              </>
            )}
          </svg>
        </button>
      </div>
    );
  }

  return null;
}
