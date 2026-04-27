import pandas as pd
from pathlib import Path
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

print(" Lancement K-Means...")

DATA_DIR = Path("data")

files = list(DATA_DIR.glob("incidents_*.csv"))

if not files:
    print(" Aucun fichier incidents trouvé")
    exit()

dfs = [pd.read_csv(f) for f in files]
df = pd.concat(dfs)

print("Nombre d'incidents :", len(df))

# features simples
df["duration_sec"] = pd.to_numeric(df["duration_sec"], errors="coerce")
df["max_score"] = pd.to_numeric(df["max_score"], errors="coerce")

df = df.dropna()

X = df[["duration_sec", "max_score"]]

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

kmeans = KMeans(n_clusters=3, random_state=42)
df["cluster"] = kmeans.fit_predict(X_scaled)

print("\nRésultat clustering :")
print(df["cluster"].value_counts())