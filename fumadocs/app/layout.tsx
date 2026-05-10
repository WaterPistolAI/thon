import { Suspense } from 'react';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { getMatomoScript, MatomoSpaTracker } from './matomo';
import './global.css';
import { Inter } from 'next/font/google';

const inter = Inter({
  subsets: ['latin'],
});

export default function Layout({ children }: LayoutProps<'/'>) {
  const matomoScript = getMatomoScript();

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
