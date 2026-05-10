# QoS Buddy SSD Restore Notes

Project copy:

```powershell
cd "E:\PI-Qos Buddy"
.\START-HERE.ps1
```

Docker image archive:

```powershell
docker load -i "E:\PI-Qos Buddy\docker-export\qos-buddy-images.tar"
```

The full restore helper wraps image loading and volume restore:

```powershell
cd "E:\PI-Qos Buddy"
.\RESTORE-DOCKER-ASSETS.ps1
```

Existing volumes are skipped by default. Use `-OverwriteVolumes` only when you intentionally want to replace an existing Docker volume with the backup contents.

Volume backups are in:

```text
E:\PI-Qos Buddy\docker-export\volumes
```

To restore a named volume on another machine, create it and untar its matching
archive, for example:

```powershell
docker volume create qos-buddy_redis-data
docker run --rm -v qos-buddy_redis-data:/volume -v "E:\PI-Qos Buddy\docker-export\volumes:/backup" alpine:3.20 sh -c "cd /volume && tar xzf /backup/qos-buddy_redis-data.tar.gz"
```

Repeat for each `qos-buddy_*.tar.gz` archive you need.

Qdrant is not part of the active SSD compose stack. The old exported Docker
volume may still exist for backup purposes, but the live prediction/RAG memory
uses ChromaDB.

Inspect prediction ChromaDB:

```powershell
docker exec -it qos-prediction python
```

```python
import chromadb
client = chromadb.PersistentClient(path="/app/rag/chroma_db")
client.list_collections()
col = client.get_collection("qos_incidents")
col.count()
col.peek(5)
```
