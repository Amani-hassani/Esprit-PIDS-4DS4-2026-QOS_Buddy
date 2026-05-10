<script lang="ts">
  import AuthPanel from '../lib/components/AuthPanel.svelte';
  import '../lib/theme.css';
  import { auth } from '../lib/api';
  import { page } from '$app/stores';

  const links = [
    { href: '/', label: 'Command' },
    { href: '/review', label: 'Review' },
    { href: '/approvals', label: 'Approvals' },
    { href: '/tickets', label: 'Tickets' },
    { href: '/audit', label: 'Audit' },
    { href: '/ops', label: 'Ops' }
  ];

  let { children } = $props();

  const current = $derived($auth);
  const path = $derived($page.url.pathname);

  function isActive(href: string): boolean {
    if (href === '/') return path === '/';
    return path.startsWith(href);
  }
</script>

<header class="app-header">
  <div class="brand">
    <span class="dot pulse"></span>
    <div class="brand-text">
      <div class="brand-name">QoS Buddy</div>
      <div class="brand-sub">Monitoring + Diagnostic Operations Console</div>
    </div>
  </div>
  <nav class="nav">
    {#each links as link (link.href)}
      <a href={link.href} class:active={isActive(link.href)}>{link.label}</a>
    {/each}
  </nav>
  <div class="status">
    {#if current.token}
      <span class="pill ok">online</span>
    {:else}
      <span class="pill warn">unauthenticated</span>
    {/if}
    <AuthPanel />
  </div>
</header>

<main class="app-main">
  {@render children?.()}
</main>

<footer class="app-footer">
  <span class="mono">QoS Buddy | command | review | approvals | tickets | audit | ops</span>
</footer>

<style>
  .app-header {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 24px;
    padding: 14px 24px;
    border-bottom: 1px solid var(--stroke);
    background: linear-gradient(180deg, rgba(15, 20, 27, 0.92), rgba(11, 15, 20, 0.85));
    position: sticky;
    top: 0;
    z-index: 50;
    backdrop-filter: blur(8px);
  }
  .brand { display: flex; align-items: center; gap: 10px; }
  .brand .dot {
    width: 10px;
    height: 10px;
    border-radius: 999px;
    background: var(--accent);
    box-shadow: 0 0 12px var(--accent);
  }
  .brand-name { font-size: 15px; font-weight: 700; letter-spacing: 0.04em; }
  .brand-sub {
    font-size: 10px;
    color: var(--text-2);
    letter-spacing: 0.18em;
    text-transform: uppercase;
  }
  .nav { display: flex; gap: 4px; }
  .nav a {
    padding: 8px 14px;
    border-radius: var(--radius-sm);
    color: var(--text-2);
    font-size: 13px;
    font-weight: 500;
    border: 1px solid transparent;
    transition: color 0.15s ease, background 0.15s ease, border-color 0.15s ease;
  }
  .nav a:hover {
    color: var(--text-0);
    background: var(--bg-2);
  }
  .nav a.active {
    color: var(--text-0);
    background: var(--bg-2);
    border-color: var(--stroke-strong);
  }
  .status { display: flex; align-items: center; gap: 12px; }
  .app-main {
    padding: 20px 24px 60px 24px;
    max-width: 1600px;
    margin: 0 auto;
  }
  .app-footer {
    text-align: center;
    padding: 24px;
    color: var(--text-3);
    border-top: 1px solid var(--stroke);
  }
  @media (max-width: 1100px) {
    .app-header { grid-template-columns: 1fr; }
    .status { justify-content: space-between; flex-wrap: wrap; }
  }
</style>
