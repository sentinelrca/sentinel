/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  env: {
    SENTINEL_API_URL: process.env.SENTINEL_API_URL ?? "http://localhost:8000",
    SENTINEL_API_KEY: process.env.SENTINEL_API_KEY ?? "",
  },
};

export default nextConfig;
