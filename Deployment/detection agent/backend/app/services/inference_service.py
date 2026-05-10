import numpy as np
import pandas as pd
from typing import List, Dict, Any

from app.core.model_loader import get_model_manager

class InferenceService:
    """Service d'inférence pour la détection d'anomalies"""
    
    def __init__(self):
        self.model_manager = get_model_manager()
        self.features = [
            'latency_ms', 'jitter_ms', 'packet_loss_pct', 'throughput_mbps',
            'bandwidth_util_pct', 'cpu_pct', 'memory_pct', 'active_connections',
            'queue_length', 'traffic_confidence', 'hour_of_day', 'rssi_dbm',
            'signal_quality_pct', 'channel', 'channel_util_pct', 'connected_stations',
            'tcp_retransmit_rate', 'mos_estimate', 'wifi_signal_score',
            'cellular_signal_score', 'signal_health_score', 'rsrp_dbm',
            'rsrq_db', 'sinr_db', 'cqi', 'mcs', 'bler_proxy_pct',
            'ho_success_rate_pct', 'cssr_proxy_pct', 'anomaly_rate_recent'
        ]
    
    def analyze(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Analyse un DataFrame et retourne les résultats de détection
        """
        # Perception : extraction des features
        perceived = df[self.features].fillna(0)
        
        # Normalisation
        scaled = self.model_manager.scaler.transform(perceived)
        
        # Inférence
        reconstructed = self.model_manager.model.predict(scaled, verbose=0)
        
        # Calcul MAE
        mae_scores = np.mean(np.abs(scaled - reconstructed), axis=1)
        
        # Décision pour chaque échantillon
        results = []
        for score in mae_scores:
            is_anomaly = score > self.model_manager.threshold
            ratio = score / self.model_manager.threshold
            
            if is_anomaly:
                status = "🔴 ALERT"
                severity = "CRITICAL" if ratio > 2.5 else "MODERATE" if ratio > 1.5 else "LIGHT"
                confidence = min(100, ratio * 40)
            else:
                status = "✅ NORMAL"
                severity = "N/A"
                # FIX: confiance proportionnelle à la distance au seuil
                margin = (self.model_manager.threshold - score) / self.model_manager.threshold
                confidence = min(100, 50 + margin * 50)
                
            results.append({
                "status": status,
                "is_anomaly": bool(is_anomaly),
                "score": float(score),
                "severity": severity,
                "confidence": float(confidence)
            })
        
        return results
    
    def get_health_report(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Génère un rapport de santé basé sur l'historique"""
        if not results:
            return {"error": "No data available"}
        
        anomalies = sum(1 for r in results if r["is_anomaly"])
        anomaly_rate = anomalies / len(results)
        health_index = (1 - anomaly_rate) * 100
        
        return {
            "stability_index": round(health_index, 1),
            "trend": "⚠️ UNSTABLE" if anomaly_rate > 0.2 else "✅ STABLE",
            "total_samples": len(results),
            "anomaly_rate": round(anomaly_rate * 100, 2),
            "avg_confidence": sum(r["confidence"] for r in results) / len(results)
        }