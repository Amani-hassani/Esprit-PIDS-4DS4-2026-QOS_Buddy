"""Test predictions with different data amounts"""

from agent.prediction_agent import PredictionAgent
from data_pipeline.loader import load_qos
from storage.integration import PredictionLogger
from pathlib import Path

print("\n" + "="*70)
print("TEST PREDICTIONS WITH DIFFERENT DATA AMOUNTS")
print("="*70)

# Step 1: Load data
print("\n[1/4] Loading QoS data...")
try:
    df = load_qos()
    print(f"  OK - Loaded {len(df):,} total rows from node(s): {df['node_id'].unique()}")
except Exception as e:
    print(f"  ERROR: {e}")
    exit(1)

# Step 2: Initialize agent
print("\n[2/4] Loading prediction models...")
try:
    agent = PredictionAgent()
    print(f"  OK - Models loaded")
except Exception as e:
    print(f"  ERROR: {e}")
    exit(1)

# Step 3: Initialize logger
print("\n[3/4] Initializing storage...")
logger = PredictionLogger()
print(f"  OK - Database ready")

# Step 4: Test with different data amounts
print("\n[4/4] Testing with different data amounts...")
node_id = df['node_id'].unique()[0]

# Test different data sizes
data_sizes = [500, 1000, 1500, 2000, len(df)]
results_summary = []

for size in data_sizes:
    if size > len(df):
        size = len(df)
    
    try:
        # Use first N rows
        df_subset = df.iloc[:size].copy()
        
        print(f"\n  Testing with {size:,} rows ({size/len(df)*100:.1f}% of data):")
        
        result = agent.predict(
            node_id=str(node_id),
            history_raw=df_subset,
            generate_llm=False
        )
        
        # Store in database
        logger.log_prediction(result)
        
        # Show results
        print(f"    Severity: {result.severity}")
        print(f"    Top risk: {max(result.risk_probs, key=result.risk_probs.get)} = {max(result.risk_probs.values()):.3f}")
        print(f"    Risks: {', '.join(f'{k}={v:.2f}' for k,v in result.risk_probs.items())}")
        
        results_summary.append({
            'rows': size,
            'severity': result.severity,
            'top_risk': max(result.risk_probs.values())
        })
        
    except Exception as e:
        print(f"    ERROR: {str(e)[:80]}")

# Step 5: Show comparison
print("\n" + "="*70)
print("COMPARISON RESULTS")
print("="*70)
print("\nRows      | Severity  | Top Risk")
print("-" * 40)
for r in results_summary:
    print(f"{r['rows']:8,} | {r['severity']:9s} | {r['top_risk']:.3f}")

print("\n" + "="*70)
health = logger.get_system_health(days_back=7)
print(f"Total predictions stored: {health['total_predictions']}")
print(f"\nTo export all results, run:")
print(f"  python export_results.py")
print("="*70 + "\n")
