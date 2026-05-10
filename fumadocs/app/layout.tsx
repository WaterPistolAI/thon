import { Suspense } from 'react';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { MatomoAnalytics } from './matomo';
import './global.css';
import { Inter } from 'next/font/google';

const inter = Inter({
  subsets: ['latin'],
});

export default function Layout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="en" className={inter.className} suppressHydrationWarning>
      <head>
        <Suspense fallback={null}>
          <MatomoAnalytics />
        </Suspense>
      </head>
      <body className="flex flex-col min-h-screen">
        <RootProvider>{children}</RootProvider>
      </body>
    </html>
  );
}
