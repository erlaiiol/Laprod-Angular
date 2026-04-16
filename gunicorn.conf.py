"""
Gunicorn configuration — LaProd production
Fix critique: dispose SQLAlchemy pool après fork (--preload safety)
"""

# ── Connexion ──────────────────────────────────────────────────────────────────
bind = "0.0.0.0:5000"
# workers: passé via --workers dans entrypoint.sh (2*nproc+1)
timeout = 120
worker_tmp_dir = "/dev/shm"

# ── Requests ───────────────────────────────────────────────────────────────────
max_requests = 1000
max_requests_jitter = 50

# ── Logs ───────────────────────────────────────────────────────────────────────
accesslog  = "-"   # stdout → docker compose logs
errorlog   = "-"   # stderr → docker compose logs
loglevel   = "info"

# ── Fork safety (CRITIQUE avec --preload) ────────────────────────────────────
# Après le fork de chaque worker, on libère toutes les connexions SQLAlchemy
# héritées du processus parent. Chaque worker créera ses propres connexions
# propres, évitant les transactions zombies inter-workers.
def post_fork(server, worker):
    from extensions import db
    try:
        db.engine.dispose(close=False)
        server.log.info(f"[gunicorn] worker {worker.pid}: SQLAlchemy pool disposé (post_fork)")
    except Exception as exc:
        server.log.warning(f"[gunicorn] post_fork dispose failed: {exc}")
