import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { checkFrontendEnvironment } from '../deployment/frontend_config.mjs';

export default defineConfig(({mode}) => {
  const values={...loadEnv(mode,process.cwd(),'VITE_'),...process.env};
  checkFrontendEnvironment(values,{hosted:Boolean(process.env.VERCEL)||['production','staging'].includes(process.env.APP_ENV)});
  return {
  plugins: [react()],
  // Router 7's conditional CJS exports need bundling in the existing SSR test runner.
  ssr: { noExternal: ['react-router', 'react-router-dom'], resolve: { conditions: ['module-sync', 'module', 'node'] } },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
};});
