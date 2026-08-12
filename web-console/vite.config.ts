import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const businessApiUrl = env.VITE_BUSINESS_API_URL || "http://localhost:8080";
  const agentApiUrl = env.VITE_AGENT_API_URL || "http://localhost:8000";

  return {
    plugins: [vue()],
    server: {
      port: Number(env.PORT || 5173),
      proxy: {
        "/business-api": {
          target: businessApiUrl,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/business-api/, ""),
        },
        "/agent-api": {
          target: agentApiUrl,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/agent-api/, ""),
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
      css: true,
    },
  };
});
