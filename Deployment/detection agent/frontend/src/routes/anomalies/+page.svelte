<script lang="ts">
    import { results, isAnalyzing, error, anomalyCount, normalCount, averageConfidence } from '$lib/stores';
    import { api } from '$lib/api';
    import type { AnomalyResult } from '$lib/types';
    
    let formData = {
        latency_ms: 50,
        jitter_ms: 10,
        packet_loss_pct: 0,
        throughput_mbps: 100,
        bandwidth_util_pct: 45,
        cpu_pct: 30,
        memory_pct: 60,
        active_connections: 50,
        queue_length: 10,
        traffic_confidence: 0.8,
        hour_of_day: new Date().getHours(),
        rssi_dbm: -65,
        signal_quality_pct: 85,
        channel: 6,
        channel_util_pct: 40,
        connected_stations: 15,
        tcp_retransmit_rate: 0.5,
        mos_estimate: 4.2,
        wifi_signal_score: 80,
        cellular_signal_score: 75,
        signal_health_score: 82,
        rsrp_dbm: -85,
        rsrq_db: -10,
        sinr_db: 15,
        cqi: 12,
        mcs: 7,
        bler_proxy_pct: 0.1,
        ho_success_rate_pct: 99.5,
        cssr_proxy_pct: 98.5,
        anomaly_rate_recent: 5
    };
    
    let singleResult: AnomalyResult | null = null;
    
    async function analyzeSingle() {
        isAnalyzing.set(true);
        error.set(null);
        
        try {
            const result = await api.detectSingle(formData);
            singleResult = result;
            results.set([result, ...$results].slice(0, 100));
        } catch (err) {
            error.set('Erreur lors de l\'analyse');
            console.error(err);
        } finally {
            isAnalyzing.set(false);
        }
    }
    
    function resetForm() {
        formData = {
            latency_ms: 50,
            jitter_ms: 10,
            packet_loss_pct: 0,
            throughput_mbps: 100,
            bandwidth_util_pct: 45,
            cpu_pct: 30,
            memory_pct: 60,
            active_connections: 50,
            queue_length: 10,
            traffic_confidence: 0.8,
            hour_of_day: new Date().getHours(),
            rssi_dbm: -65,
            signal_quality_pct: 85,
            channel: 6,
            channel_util_pct: 40,
            connected_stations: 15,
            tcp_retransmit_rate: 0.5,
            mos_estimate: 4.2,
            wifi_signal_score: 80,
            cellular_signal_score: 75,
            signal_health_score: 82,
            rsrp_dbm: -85,
            rsrq_db: -10,
            sinr_db: 15,
            cqi: 12,
            mcs: 7,
            bler_proxy_pct: 0.1,
            ho_success_rate_pct: 99.5,
            cssr_proxy_pct: 98.5,
            anomaly_rate_recent: 5
        };
        singleResult = null;
    }
</script>

<div class="anomalies-page">
    <div class="page-header">
        <h1>Détection d'Anomalies</h1>
        <p>Analyse en temps réel de la qualité de service réseau</p>
    </div>
    
    <div class="two-columns">
        <div class="form-card">
            <h2>📝 Paramètres réseau</h2>
            <form on:submit|preventDefault={analyzeSingle}>
                <div class="form-grid">
                    <div class="form-group">
                        <label>Latence (ms)</label>
                        <input type="number" bind:value={formData.latency_ms} step="1" />
                    </div>
                    <div class="form-group">
                        <label>Gigue (ms)</label>
                        <input type="number" bind:value={formData.jitter_ms} step="1" />
                    </div>
                    <div class="form-group">
                        <label>Perte de paquets (%)</label>
                        <input type="number" bind:value={formData.packet_loss_pct} step="0.1" />
                    </div>
                    <div class="form-group">
                        <label>Débit (Mbps)</label>
                        <input type="number" bind:value={formData.throughput_mbps} step="1" />
                    </div>
                    <div class="form-group">
                        <label>Utilisation bande passante (%)</label>
                        <input type="number" bind:value={formData.bandwidth_util_pct} step="1" />
                    </div>
                    <div class="form-group">
                        <label>CPU (%)</label>
                        <input type="number" bind:value={formData.cpu_pct} step="1" />
                    </div>
                    <div class="form-group">
                        <label>Mémoire (%)</label>
                        <input type="number" bind:value={formData.memory_pct} step="1" />
                    </div>
                    <div class="form-group">
                        <label>Connexions actives</label>
                        <input type="number" bind:value={formData.active_connections} step="1" />
                    </div>
                </div>
                
                <div class="form-actions">
                    <button type="submit" class="btn btn-primary" disabled={$isAnalyzing}>
                        {#if $isAnalyzing}
                            ⏳ Analyse...
                        {:else}
                            🔍 Détecter
                        {/if}
                    </button>
                    <button type="button" class="btn btn-secondary" on:click={resetForm}>
                        🔄 Réinitialiser
                    </button>
                </div>
            </form>
        </div>
        
        <div class="result-card">
            <h2>📊 Résultat de l'analyse</h2>
            
            {#if $isAnalyzing}
                <div class="loading">
                    <div class="spinner"></div>
                    <p>Analyse en cours...</p>
                </div>
            {:else if singleResult}
                <div class="result-detail {singleResult.is_anomaly ? 'anomaly' : 'normal'}">
                    <div class="result-status">
                        <span class="status-icon">{singleResult.status === '✅ NORMAL' ? '✅' : '🔴'}</span>
                        <span class="status-text">{singleResult.status}</span>
                    </div>
                    <div class="result-metrics">
                        <div class="metric">
                            <span class="metric-label">Score d'anomalie</span>
                            <span class="metric-value">{singleResult.score.toFixed(4)}</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Sévérité</span>
                            <span class="metric-value severity-{singleResult.severity.toLowerCase()}">
                                {singleResult.severity}
                            </span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Confiance</span>
                            <span class="metric-value">{singleResult.confidence}%</span>
                        </div>
                    </div>
                </div>
            {:else}
                <div class="empty-state">
                    <span class="empty-icon">🔍</span>
                    <p>Aucune analyse effectuée</p>
                    <p class="empty-hint">Remplissez le formulaire et cliquez sur "Détecter"</p>
                </div>
            {/if}
        </div>
    </div>
    
    {#if $error}
        <div class="error-message">
            <span>❌</span>
            <span>{$error}</span>
        </div>
    {/if}
    
    {#if $results.length > 0}
        <div class="history-section">
            <h2>📜 Historique récent</h2>
            <div class="results-table">
                <table>
                    <thead>
                        <tr>
                            <th>Statut</th>
                            <th>Score</th>
                            <th>Sévérité</th>
                            <th>Confiance</th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each $results.slice(0, 10) as result, i (i)}
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
    .anomalies-page {
        max-width: 1400px;
        margin: 0 auto;
    }

    .page-header {
        margin-bottom: 2rem;
    }

    .page-header h1 {
        font-size: 1.75rem;
        margin-bottom: 0.5rem;
    }

    .page-header p {
        color: var(--text-secondary);
    }

    .two-columns {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 1.5rem;
        margin-bottom: 2rem;
    }

    .form-card, .result-card {
        background: var(--card-bg);
        border: 1px solid var(--border);
        border-radius: 1rem;
        padding: 1.5rem;
    }

    .form-card h2, .result-card h2, .history-section h2 {
        font-size: 1.25rem;
        margin-bottom: 1rem;
    }

    .form-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 1rem;
        margin-bottom: 1.5rem;
    }

    .form-group {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .form-group label {
        font-size: 0.75rem;
        font-weight: 500;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .form-group input {
        padding: 0.5rem;
        border: 1px solid var(--border);
        border-radius: 0.375rem;
        background: var(--bg-primary);
        color: var(--text-primary);
        font-size: 0.875rem;
    }

    .form-group input:focus {
        outline: none;
        border-color: var(--info);
    }

    .form-actions {
        display: flex;
        gap: 1rem;
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

    .loading {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 3rem;
    }

    .spinner {
        width: 40px;
        height: 40px;
        border: 3px solid var(--border);
        border-top-color: var(--info);
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    .result-detail {
        padding: 1rem;
        border-radius: 0.5rem;
    }

    .result-detail.anomaly {
        background: rgba(239, 68, 68, 0.1);
        border: 1px solid var(--error);
    }

    .result-detail.normal {
        background: rgba(34, 197, 94, 0.1);
        border: 1px solid var(--success);
    }

    .result-status {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 1rem;
        font-size: 1.25rem;
        font-weight: 600;
    }

    .status-icon {
        font-size: 1.5rem;
    }

    .result-metrics {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }

    .metric {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.5rem;
        background: var(--bg-primary);
        border-radius: 0.375rem;
    }

    .metric-label {
        color: var(--text-secondary);
        font-size: 0.875rem;
    }

    .metric-value {
        font-weight: 600;
        color: var(--text-primary);
    }

    .severity-critical {
        color: var(--error);
    }

    .severity-moderate {
        color: var(--warning);
    }

    .severity-light {
        color: var(--info);
    }

    .severity-na {
        color: var(--success);
    }

    .empty-state {
        text-align: center;
        padding: 3rem;
        color: var(--text-secondary);
    }

    .empty-icon {
        font-size: 3rem;
        display: block;
        margin-bottom: 1rem;
    }

    .empty-hint {
        font-size: 0.875rem;
        margin-top: 0.5rem;
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

    .history-section {
        background: var(--card-bg);
        border: 1px solid var(--border);
        border-radius: 1rem;
        padding: 1.5rem;
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
        width: 120px;
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

    @media (max-width: 768px) {
        .two-columns {
            grid-template-columns: 1fr;
        }
        
        .form-grid {
            grid-template-columns: 1fr;
        }
    }
</style>