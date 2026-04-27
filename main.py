from data_loader import load_timeseries, load_incidents
from sample_selector import pick_most_interesting_sample, top_interesting_samples
from usecase_1_narrative import generate_narrative
from usecase_2_qa import answer_question
from usecase_3_root_cause import classify_root_cause


def main():
    print("Chargement des données...")
    df = load_timeseries()
    incidents_df = load_incidents()

    print(f"Nombre de lignes timeseries : {len(df)}")
    print(f"Nombre d'incidents : {len(incidents_df)}")

    sample_row = pick_most_interesting_sample(df)
    top_rows = top_interesting_samples(df, n=5)

    if sample_row is None:
        print("Aucune donnée disponible.")
        return

    print("\n==============================")
    print("LIGNE LA PLUS INTERESSANTE")
    print("==============================")
    for k, v in sample_row.items():
        if k in [
            "timestamp", "latency_ms", "jitter_ms", "packet_loss_pct",
            "throughput_mbps", "traffic_type", "anomaly_type",
            "anomaly_score", "source_file", "interest_score"
        ]:
            print(f"{k}: {v}")

    print("\n==============================")
    print("USAGE 1 - NARRATIVE INTELLIGENTE")
    print("==============================")
    print(generate_narrative(sample_row))

    print("\n==============================")
    print("USAGE 2 - Q&A")
    print("==============================")
    question = "Quel est le problème le plus critique observé dans les données et pourquoi ?"
    print(answer_question(question, df, incidents_df, top_rows=top_rows))

    print("\n==============================")
    print("USAGE 3 - CAUSE RACINE")
    print("==============================")
    print(classify_root_cause(sample_row))


if __name__ == "__main__":
    main()