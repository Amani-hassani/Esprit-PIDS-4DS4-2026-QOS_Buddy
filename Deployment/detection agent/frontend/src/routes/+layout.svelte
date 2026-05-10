<script lang="ts">
    import { onMount } from 'svelte';
    import '@fontsource/inter/400.css';
    import '@fontsource/inter/500.css';
    import '@fontsource/inter/600.css';
    import '@fontsource/inter/700.css';

    let theme = 'light';

    // FIX: appliquer le thème au chargement initial
    onMount(() => {
        document.documentElement.setAttribute('data-theme', theme);
    });

    function toggleTheme() {
        theme = theme === 'light' ? 'light' : 'light';
        document.documentElement.setAttribute('data-theme', theme);
    }
</script>

<svelte:head>
    <title>QoS Buddy - Détection d'Anomalies Réseau</title>
    <meta name="description" content="Plateforme de détection d'anomalies réseau par IA" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
</svelte:head>

<main class="app">
    <nav class="navbar">
        <div class="nav-brand">
            <span class="logo">📡</span>
            <span class="title">QoS Buddy</span>
        </div>
        <div class="nav-links">
            <a href="/" class="nav-link">Dashboard</a>
            <a href="/anomalies" class="nav-link">Détection</a>
        </div>
        <button class="theme-toggle" on:click={toggleTheme}>
            {theme === 'light' ? '🌞' : '🌙'}
        </button>
    </nav>

    <div class="content">
        <slot />
    </div>
</main>

<style>
    :global(*) {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }

    :global(body) {
        font-family: 'Inter', sans-serif;
        background: var(--bg-primary);
        color: var(--text-primary);
        transition: all 0.3s ease;
    }

    :global(html[data-theme="light"]) {
        --bg-primary: #0f172a;
        --bg-secondary: #1e293b;
        --text-primary: #f1f5f9;
        --text-secondary: #94a3b8;
        --border: #334155;
        --card-bg: #1e293b;
        --success: #22c55e;
        --error: #ef4444;
        --warning: #f59e0b;
        --info: #3b82f6;
    }

    :global(html[data-theme="light"]) {
        --bg-primary: #f8fafc;
        --bg-secondary: #ffffff;
        --text-primary: #0f172a;
        --text-secondary: #475569;
        --border: #e2e8f0;
        --card-bg: #ffffff;
        --success: #16a34a;
        --error: #dc2626;
        --warning: #d97706;
        --info: #2563eb;
    }

    .app {
        min-height: 100vh;
        display: flex;
        flex-direction: column;
    }

    .navbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 2rem;
        background: var(--bg-secondary);
        border-bottom: 1px solid var(--border);
        position: sticky;
        top: 0;
        z-index: 100;
    }

    .nav-brand {
        display: flex;
        align-items: center;
        gap: 0.75rem;
    }

    .logo { font-size: 1.75rem; }

    .title {
        font-size: 1.25rem;
        font-weight: 700;
        background: linear-gradient(135deg, #3b82f6, #8b5cf6);
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
    }

    .nav-links { display: flex; gap: 2rem; }

    .nav-link {
        text-decoration: none;
        color: var(--text-secondary);
        font-weight: 500;
        transition: color 0.2s;
    }

    .nav-link:hover { color: var(--info); }

    .theme-toggle {
        background: var(--bg-primary);
        border: 1px solid var(--border);
        border-radius: 50%;
        width: 2.5rem;
        height: 2.5rem;
        font-size: 1.25rem;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--text-primary);
        transition: all 0.2s;
    }

    .theme-toggle:hover { transform: scale(1.05); }

    .content { flex: 1; padding: 2rem; }

    @media (max-width: 768px) {
        .navbar { padding: 0.75rem 1rem; }
        .title { font-size: 1rem; }
        .nav-links { gap: 1rem; }
        .content { padding: 1rem; }
    }
</style>
