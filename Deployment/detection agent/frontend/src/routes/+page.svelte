<script lang="ts">
    import { onMount } from 'svelte';
    import { 
        results, healthReport, systemMetrics, isAnalyzing, 
        anomalyCount, normalCount, averageConfidence, criticalCount,
        error
    } from '$lib/stores';
    import { api } from '$lib/api';
    
    let selectedFile: File | null = null;
    let autoRefresh = true;
    let refreshInterval: ReturnType<typeof setInterval> | undefined;
    
    onMount(() => {
        loadHealthReport();
        loadSystemMetrics();
        
        if (autoRefresh) {
            refreshInterval = setInterval(() => {
                loadHealthReport();
                loadSystemMetrics();
            }, 30000);
        }
        
        return () => {
            if (refreshInterval) clearInterval(refreshInterval);
        };
    });
    
    async function loadHealthReport() {
        try {
            const report = await api.getHealthReport();
            healthReport.set(report);
            error.set(null);
        } catch (err) {
            error.set('Erreur lors du chargement du rapport de santé');
            console.error(err);
        }
    }
    
    async function loadSystemMetrics() {
        try {
            const metrics = await api.getSystemMetrics();
            systemMetrics.set(metrics);
        } catch (err) {
            console.error(err);
        }
    }
    
    async function handleFileUpload() {
        if (!selectedFile) return;
        
        isAnalyzing.set(true);
        
        try {
            const text = await selectedFile.text();
            const data = JSON.parse(text);
            const resultsData = await api.detectAnomalies(data);
            results.set(resultsData);
        } catch (err) {
            error.set('Erreur lors de l\'analyse du fichier');
            console.error(err);
        } finally {
            isAnalyzing.set(false);
        }
    }
    
    function handleFileChange(event: Event) {
        const input = event.target as HTMLInputElement;
        if (input.files && input.files[0]) {
            selectedFile = input.files[0];
        }
    }
    
    function clearResults() {
        results.set([]);
    }
</script>

<div class="dashboard">
    <!-- Header -->
    <div class="dashboard-header">
        <h1>Tableau de Bord</h1>
        <p>Surveillance en temps réel de la qualité de service réseau</p>
    </div>
    
    <!-- Statistiques -->
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-icon">📊</div>
            <div class="stat-value">{$anomalyCount}</div>
            <div class="stat-label">Anomalies détectées</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon">✅</div>
            <div class="stat-value">{$normalCount}</div>
            <div class="stat-label">Échantillons normaux</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon">🎯</div>
            <div class="stat-value">{($averageConfidence ?? 0).toFixed(1)}%</div>
            <div class="stat-label">Confiance moyenne</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon">⚠️</div>
            <div class="stat-value">{$criticalCount}</div>
            <div class="stat-label">Critiques</div>
        </div>
    </div>
    
    <!-- Analyse de fichiers -->
    <div class="upload-section">
        <h2>Analyse de données réseau</h2>
        <div class="upload-area">
            <input type="file" accept=".json" on:change={handleFileChange} />
            <button 
                class="btn btn-primary" 
                on:click={handleFileUpload}
                disabled={!selectedFile || $isAnalyzing}
            >
                {#if $isAnalyzing}
                    ⏳ Analyse en cours...
                {:else}
                    🚀 Lancer l'analyse
                {/if}
            </button>
            <button class="btn btn-secondary" on:click={clearResults}>
                🗑️ Effacer
            </button>
        </div>
    </div>
    
    <!-- Erreur -->
    {#if $error}
        <div class="error-message">
            <span>❌</span>
            <span>{$error}</span>
        </div>
    {/if}
    
    <!-- Résultats -->
    {#if $results.length > 0}
        <div class="results-section">
            <h2>Résultats de l'analyse</h2>
            <div class="results-table">
                <table>
                    <thead>
                        <tr>
                            <th>Statut</th>
                            <th>Score d'anomalie</th>
                            <th>Sévérité</th>
                            <th>Confiance</th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each $results as result (result.score)}
                            <tr class={result.is_anomaly ? 'anomaly-row' : 'normal-row'}>
                                <td>{result.status}</td>
                                <td>{result.score.toFixed(4)}</td>
                                <td>
                                    <span class="severity-badge {result.severity.toLowerCase()}">
                                        {result.severity}
                                    </span>
                                </td>
                                <td>
                                    <div class="confidence-bar">
                                        <div class="confidence-fill" style="width: {result.confidence}%"></div>
                                        <span class="confidence-text">{result.confidence}%</span>
                                    </div>
                                </td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </div>
        </div>
    {/if}
</div>

<style>
    .dashboard {
        max-width: 1400px;
        margin: 0 auto;
    }
    
    .dashboard-header {
        margin-bottom: 2rem;
    }
    
    .dashboard-header h1 {
        font-size: 1.75rem;
        margin-bottom: 0.5rem;
    }
    
    .dashboard-header p {
        color: var(--text-secondary);
    }
    
    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 1rem;
        margin-bottom: 2rem;
    }
    
    .stat-card {
        background: var(--card-bg);
        border: 1px solid var(--border);
        border-radius: 1rem;
        padding: 1.25rem;
        text-align: center;
        transition: transform 0.2s, box-shadow 0.2s;
    }
    
    .stat-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.1);
    }
    
    .stat-icon {
        font-size: 2rem;
        margin-bottom: 0.5rem;
    }
    
    .stat-value {
        font-size: 2rem;
        font-weight: 700;
        color: var(--info);
    }
    
    .stat-label {
        font-size: 0.875rem;
        color: var(--text-secondary);
    }
    
    .upload-section {
        background: var(--card-bg);
        border: 1px solid var(--border);
        border-radius: 1rem;
        padding: 1.5rem;
        margin-bottom: 2rem;
    }
    
    .upload-section h2 {
        font-size: 1.25rem;
        margin-bottom: 1rem;
    }
    
    .upload-area {
        display: flex;
        gap: 1rem;
        align-items: center;
        flex-wrap: wrap;
    }
    
    .btn {
        padding: 0.625rem 1.25rem;
        border: none;
        border-radius: 0.5rem;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s;
    }
    
    .btn-primary {
        background: var(--info);
        color: white;
    }
    
    .btn-primary:hover:not(:disabled) {
        background: #2563eb;
        transform: translateY(-1px);
    }
    
    .btn-primary:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }
    
    .btn-secondary {
        background: var(--bg-primary);
        border: 1px solid var(--border);
        color: var(--text-primary);
    }
    
    .btn-secondary:hover {
        background: var(--border);
    }
    
    .error-message {
        background: rgba(239, 68, 68, 0.1);
        border: 1px solid var(--error);
        border-radius: 0.5rem;
        padding: 1rem;
        margin-bottom: 1rem;
        display: flex;
        gap: 0.5rem;
        align-items: center;
        color: var(--error);
    }
    
    .results-section {
        background: var(--card-bg);
        border: 1px solid var(--border);
        border-radius: 1rem;
        padding: 1.5rem;
    }
    
    .results-section h2 {
        font-size: 1.25rem;
        margin-bottom: 1rem;
    }
    
    .results-table {
        overflow-x: auto;
    }
    
    table {
        width: 100%;
        border-collapse: collapse;
    }
    
    th, td {
        padding: 0.75rem;
        text-align: left;
        border-bottom: 1px solid var(--border);
    }
    
    th {
        color: var(--text-secondary);
        font-weight: 500;
    }
    
    .anomaly-row {
        background: rgba(239, 68, 68, 0.05);
    }
    
    .normal-row {
        background: rgba(34, 197, 94, 0.05);
    }
    
    .severity-badge {
        display: inline-block;
        padding: 0.25rem 0.5rem;
        border-radius: 0.25rem;
        font-size: 0.75rem;
        font-weight: 500;
    }
    
    .severity-badge.critical {
        background: rgba(239, 68, 68, 0.2);
        color: var(--error);
    }
    
    .severity-badge.moderate {
        background: rgba(245, 158, 11, 0.2);
        color: var(--warning);
    }
    
    .severity-badge.light {
        background: rgba(59, 130, 246, 0.2);
        color: var(--info);
    }
    
    .severity-badge.na {
        background: rgba(148, 163, 184, 0.2);
        color: var(--text-secondary);
    }
    
    .confidence-bar {
        position: relative;
        background: var(--border);
        border-radius: 0.25rem;
        height: 1.5rem;
        width: 100%;
        overflow: hidden;
    }
    
    .confidence-fill {
        background: var(--info);
        height: 100%;
        border-radius: 0.25rem;
        transition: width 0.3s ease;
    }
    
    .confidence-text {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        font-size: 0.75rem;
        font-weight: 500;
        color: white;
        text-shadow: 0 1px 1px rgba(0, 0, 0, 0.2);
    }
</style>