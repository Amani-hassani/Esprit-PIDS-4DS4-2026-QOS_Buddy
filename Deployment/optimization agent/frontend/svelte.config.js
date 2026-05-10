import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      pages: '../deployment/static/app',
      assets: '../deployment/static/app',
      fallback: 'index.html',
      precompress: false,
      strict: true
    }),
    alias: {
      $lib: './src/lib'
    }
  }
};

export default config;
