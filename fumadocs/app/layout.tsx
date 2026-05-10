import { Suspense } from 'react';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { MatomoSpaTracker } from './matomo';
import './global.css';
import { Inter } from 'next/font/google';

const inter = Inter({
  subsets: ['latin'],
});

const MATOMO_URL = process.env.NEXT_PUBLIC_MATOMO_URL;
const MATOMO_SITE_ID = process.env.NEXT_PUBLIC_MATOMO_SITE_ID;
const MATOMO_DOMAINS = process.env.NEXT_PUBLIC_MATOMO_DOMAINS;

function buildMatomoScript(): string | null {
  if (!MATOMO_URL || !MATOMO_SITE_ID) return null;
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
_paq.push(["setTrackerUrl", ${JSON.stringify(MATOMO_URL)}matomo.php]);
_paq.push(["setSiteId", ${JSON.stringify(MATOMO_SITE_ID)}]);
var d=document, g=d.createElement('script'), s=d.getElementsByTagName('script')[0];
g.async=true; g.src=${JSON.stringify(MATOMO_URL + "matomo.js")}; s.parentNode.insertBefore(g,s);
`;
}

export default function Layout({ children }: LayoutProps<'/'>) {
  const matomoScript = buildMatomoScript();

  return (
    <html lang="en" className={inter.className} suppressHydrationWarning>
      <head>
        {matomoScript && (
          <script dangerouslySetInnerHTML={{ __html: matomoScript }} />
        )}
      </head>
      <body className="flex flex-col min-h-screen">
        <RootProvider>{children}</RootProvider>
        <Suspense fallback={null}>
          <MatomoSpaTracker />
        </Suspense>
      </body>
    </html>
  );
}
