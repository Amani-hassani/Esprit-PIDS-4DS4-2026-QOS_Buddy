# Agent de Prédiction QoS

Pile de prédiction de risques QoS pour la télécommunication en production : charger les CSV QoS et incidents, créer 6 labels binaires sur horizon futur, entraîner XGBoost (par cible) + LSTM multi-cible, prédire avec fusion d'ensemble (0.55 XGB + 0.45 LSTM), prévoir l'ETA d'épuisement de capacité via Prophet, expliquer les prédictions avec SHAP, récupérer les incidents similaires de ChromaDB, et générer les alertes NOC via Ollama.

## Démarrage rapide

**Installation & configuration** (Python 3.10+)
```bash
pip install -r requirements.txt
```

**Placement des données**
- QoS : `data/raw/qos_timeseries_*.csv`
- Incidents: `data/incidents/incidents_*.csv`

**Entraîner les modèles**
```bash
python main.py
# ou
python scripts/train_all.py
```

**Évaluer les modèles**
```bash
python scripts/evaluate_models.py [--last-15pct] [--max-rows 500]
```

**Ingérer les incidents dans ChromaDB (optionnel)**
```bash
python scripts/ingest_incidents.py [--replace]
```

**Lancer l'interface Streamlit**
```bash
streamlit run app/streamlit_app.py
```

## Vue d'ensemble de l'architecture

| Composant | Rôle |
|-----------|------|
| **Labels** | 6 cibles binaires (call_drop, latence, débit, jitter, congestion, mos) calculées par node_id sur horizon 120 pas |
| **Features** | Colonnes du schéma + métriques ingéniérées (lags, stats glissantes) avec prévention de fuite |
| **XGBoost** | 6 classifieurs par cible, TimeSeriesSplit(5), scale_pos_weight + calibration isotonique |
| **LSTM** | RNN multi-cible, fenêtre=20 pas, MinMaxScaler fit sur données d'entraînement uniquement |
| **Ensemble** | Fusion d'inférence : 0.55×XGB + 0.45×LSTM (basée sur probabilités) |
| **Prophet** | ETA d'épuisement de capacité (séparé de la classification des risques) |
| **SHAP** | Importance des features par modèle et cible |
| **RAG** | Récupération d'incidents ChromaDB + génération d'alertes Ollama |

## Explication du modèle (présentation 1 minute)

1. **XGBoost** = risque instantané (détection via features courants)
2. **LSTM** = risque temporel (détection de tendance sur historique récent)
3. **Ensemble** = vue combinée (fusion pondérée des deux signaux)
4. **SHAP** = pourquoi le risque est élevé (features qui pilotent la prédiction)
5. **RAG + LLM** = opérationnaliser (récupérer incidents similaires → générer alerte NOC)

## Bandes de sévérité

Basé sur max(probabilité - seuil) :

- **normal** : marge < -0,15
- **watch** : -0,15 ≤ marge < -0,05
- **warning** : -0,05 ≤ marge < 0,05
- **high** : 0,05 ≤ marge < 0,15
- **critical** : marge ≥ 0,15

## Configuration clé (config.py)

**Chemins** : `DATA_RAW_DIR`, `DATA_INCIDENTS_DIR`, `SAVED_MODELS_DIR`, `RAG_CHROMA_DIR`

**Horizons** : `FUTURE_WINDOW_STEPS=120`, `LSTM_WINDOW=20`, `PROPHET_HORIZON_PERIODS=60`

**Seuils** : `LATENCY_THRESHOLD_MS`, `THROUGHPUT_THRESHOLD_MBPS`, `JITTER_THRESHOLD_MS`, `MOS_THRESHOLD`, `CONGESTION_THRESHOLD`

**Poids modèles** : `ENSEMBLE_XGB_WEIGHT=0.55`, `ENSEMBLE_LSTM_WEIGHT=0.45`

**LLM** : `OLLAMA_MODEL` (variable env ou config)

## Sortie d'inférence (PredictionResult)

- `risk_probs` : dictionnaire de 6 probabilités
- `capacity_exhaustion_eta_min` : minutes avant congestion (Prophet)
- `severity` : normal/watch/warning/high/critical
- `shap_features` : importance des features par cible
- `retrieved_incidents` : incidents similaires de ChromaDB
- `explanation` : texte d'alerte prêt pour NOC
- `eta_debug_status` : ok/no_crossing/prophet_error

## Configuration Ollama

```bash
ollama pull llama3  # ou votre modèle préféré
export OLLAMA_MODEL=llama3
# Assurez-vous qu'ollama serve s'exécute sur localhost:11434
```

## Points importants

- **Prévention de fuite de labels** : anomaly_flag, anomaly_type, anomaly_score exclus des inputs
- **Alignement des features** : XGB et LSTM utilisent les mêmes ensembles de features (resolve_feature_columns)
- **Intégrité des séries temporelles** : TimeSeriesSplit (sans mélange), MinMaxScaler fit sur entraînement uniquement
- **Limites de probabilité** : sorties clippées à [0,1] ; valeurs NaN/Inf imputées

## Tests

```bash
pytest -q  # Exécuter tous les tests
```

Inclut tests de fumée (imports), tests unitaires (phases de modélisation), et tests d'intégration.