import type { Metadata } from 'next';
import Link from 'next/link';
import { Card, Cards } from 'fumadocs-ui/components/card';
import {
  GitBranch,
  Globe,
  MessageCircle,
  Cpu,
  ExternalLink,
} from 'lucide-react';
import { appName, gitConfig } from '@/lib/shared';

export const metadata: Metadata = {
  title: `${appName} - Hackathon Development Platform`,
};

export default function HomePage() {
  return (
    <div className="flex flex-col justify-center flex-1 max-w-4xl mx-auto px-6 py-16">
      <h1 className="text-4xl font-bold mb-4">{appName}</h1>
      <p className="text-lg text-fd-muted-foreground mb-8 max-w-2xl">
        THON is a hackathon-focused multi-instance development tool with nginx
        reverse proxy, SSL, groups support, persistent workspace bind mounts,
        and optional local LLM inference via Lemonade Server. Read the{' '}
        <Link href="/docs" className="font-medium underline">
          documentation
        </Link>{' '}
        to get started.
      </p>

      <h2 className="text-xl font-semibold mb-4">Community & Resources</h2>
      <Cards>
        <Card
          icon={<MessageCircle />}
          title="Discord"
          description="Join the community on Discord for help, updates, and discussion."
          href="https://discord.waterpistol.co"
          external
        />
        <Card
          icon={<Globe />}
          title="Water Pistol"
          description="Visit the Water Pistol website for more information about the team and projects."
          href="https://waterpistol.co"
          external
        />
        <Card
          icon={<GitBranch />}
          title="GitHub Repository"
          description="Browse the source code, open issues, and contribute."
          href={`https://github.com/${gitConfig.user}/${gitConfig.repo}`}
          external
        />
      </Cards>

      <h2 className="text-xl font-semibold mt-12 mb-4">
        Built for High-VRAM Hardware
      </h2>
      <p className="text-fd-muted-foreground mb-6 max-w-2xl">
        THON is designed for nodes and clusters with large-capacity VRAM,
        enabling local LLM inference at scale. If you need access to
        high-performance GPU hardware, check out these AMD developer programs
        and platforms:
      </p>
      <Cards>
        <Card
          icon={<ExternalLink />}
          title="AMD AI Developer Program"
          description="Apply for access to AMD Instinct accelerators and development resources for AI workloads."
          href="https://www.amd.com/en/developer/ai-dev-program.html"
          external
        />
        <Card
          icon={<Cpu />}
          title="AMD Developer Hub"
          description="Tools, SDKs, and documentation for building on AMD GPU architectures."
          href="https://developer.amd.com/"
          external
        />
        <Card
          icon={<Globe />}
          title="AMD DevCloud"
          description="Access AMD GPU droplets on Digital Ocean for on-demand high-VRAM instances."
          href="https://devcloud.amd.com/"
          external
        />
      </Cards>
    </div>
  );
}
