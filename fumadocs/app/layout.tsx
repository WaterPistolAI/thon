import { Suspense } from 'react';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { MatomoAnalytics, MatomoSpaTracker } from './matomo';
import './global.css';
import { Inter } from 'next/font/google';

const inter = Inter({
  subsets: ['latin'],
});

export default function Layout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="en" className={inter.className} suppressHydrationWarning>
      <body className="flex flex-col min-h-screen">
        <MatomoAnalytics />
        <RootProvider>{children}</RootProvider>
        <Suspense fallback={null}>
          <MatomoSpaTracker />
        </Suspense>
      </body>
    </html>
  );
}
