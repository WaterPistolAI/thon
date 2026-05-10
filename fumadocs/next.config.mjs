import { createMDX } from 'fumadocs-mdx/next';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Define __dirname for ES Modules
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const withMDX = createMDX();


/** @type {import('next').NextConfig} */
const config = {
  reactStrictMode: true,
};

const nextConfig = {
  experimental: {
    // This allows Next.js to "see" the docs folder in the parent
    outputFileTracingRoot: path.join(__dirname, '../../'),
  },
};

export default withMDX(config);
