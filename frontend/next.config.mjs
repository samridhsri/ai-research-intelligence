import { withSentryConfig } from "@sentry/nextjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  devIndicators: {
    appIsrStatus: false,
    buildActivity: false,
  },
};

export default withSentryConfig(nextConfig, {
  silent: true,
  org: "none",
  project: "none",
}, {
  widenClientFileUpload: true,
  hideSourceMaps: true,
  disableLogger: true,
});
