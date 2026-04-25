from storage.integration import PredictionLogger
from pathlib import Path

print("\n=== RESULTS DATABASE ===\n")

logger = PredictionLogger()

# Get system health
health = logger.get_system_health(days_back=7)
print(f"Total predictions: {health['total_predictions']}")
print(f"System health: {health['health_status']}")
print(f"Critical: {health['critical_percentage']:.1f}%")
print(f"High: {health['high_percentage']:.1f}%")

if health['total_predictions'] > 0:
    # Export to files
    logger.export_session_results('results', format='both')
    
    print(f"\nExported to:")
    print(f"  • results/predictions_*.csv (spreadsheet)")
    print(f"  • results/predictions_*.json (full data)")
    
    top_nodes = health.get('top_affected_nodes', {})
    if top_nodes:
        if isinstance(top_nodes, dict):
            print(f"\nTop nodes: {list(top_nodes.keys())[:5]}")
        else:
            print(f"\nTop nodes: {top_nodes[:5]}")
else:
    print("\nNo predictions stored yet.")
    print("\nTo store predictions, use:")
    print("  from storage.integration import PredictionLogger")
    print("  logger = PredictionLogger()")
    print("  logger.log_prediction(result)")

# Database info
print(f"\n=== DATABASE ===")
db_path = Path("storage/predictions.db")
if db_path.exists():
    size_mb = db_path.stat().st_size / (1024*1024)
    print(f"Location: {db_path}")
    print(f"Size: {size_mb:.2f} MB")
else:
    print(f"Location: {db_path}")
    print("Status: Will be created on first use")
print()
