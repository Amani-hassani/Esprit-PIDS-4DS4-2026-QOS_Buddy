/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  experimental: {
    optimizePackageImports: ["lucide-react", "echarts-for-react"],
  },
  poweredByHeader: false,
};

export default nextConfig;
