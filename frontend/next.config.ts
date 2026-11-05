import type { NextConfig } from 'next';
const config: NextConfig = { async rewrites() { return process.env.NODE_ENV === 'development' ? [{ source: '/api/:path*', destination: 'http://127.0.0.1:8000/api/:path*' }] : []; } };
export default config;
