import adapter from '@sveltejs/adapter-static';

export default {
  kit: {
    adapter: adapter({
      fallback: 'index.html'
    }),
    paths: {
      base: process.env.BASE_PATH || '',
    },
    alias: {
      $components: 'src/components',
      $lib: 'src/lib',
      $stores: 'src/stores',
      $types: 'src/types',
      $utils: 'src/utils',
      $api: 'src/api',
    },
  },
  vitePlugin: {
    inspector: true,
  },
};
