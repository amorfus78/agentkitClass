import withPWA from 'next-pwa';
import withBundleAnalyzer from '@next/bundle-analyzer';

// Only run bundle analyzer when ANALYZE is set to true
const bundleAnalyzerConfig = {
  enabled: process.env.ANALYZE === 'true',
};

/** @type {import("next").NextConfig} */
const config = {
  reactStrictMode: true,
  output: 'standalone',
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    domains: ['github.com', '127.0.0.1', 'localhost', 'oaidalleapiprodscus.blob.core.windows.net'],
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'oaidalleapiprodscus.blob.core.windows.net',
        port: '',
        pathname: '/**',
      },
    ],
  },
  i18n: {
    locales: ['en'],
    defaultLocale: 'en',
  },
  rewrites: async () => [
    { source: '/health', destination: '/api/health' },
    { source: '/healthz', destination: '/api/health' },
    { source: '/api/healthz', destination: '/api/health' },
    { source: '/ping', destination: '/api/health' },
  ],
  pwa: {
    dest: 'public',
    register: true,
    skipWaiting: true,
    manifest: '/manifest.json',
  },
};

export default withBundleAnalyzer(bundleAnalyzerConfig)(withPWA(config));
