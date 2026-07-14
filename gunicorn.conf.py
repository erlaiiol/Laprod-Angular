"""
Gunicorn configuration — LaProd production
Fix critique: dispose SQLAlchemy pool après fork (--preload safety)
"""

# ── Connexion ──────────────────────────────────────────────────────────────────
bind = "0.0.0.0:5000"
# workers: passé via --workers dans entrypoint.sh (2*nproc+1)
timeout = 120
worker_tmp_dir = "/dev/shm"

# ── Concurrence (anti slow-read / slow-loris applicatif) ──────────────────────
# Sans worker_class, gunicorn utilise des workers SYNCHRONES : 1 worker = 1
# requête à la fois. Sur un 2 vCPU (5 workers), 5 connexions lentes suffisaient
# à bloquer 100 % de l'API — sans aucun volume, donc sans jamais déclencher
# l'anti-DDoS OVH (qui n'agit qu'en L3/L4 volumétrique).
#
# gthread (et non gevent) : pas de monkey-patching, donc aucun risque pour
# psycopg2/SQLAlchemy et le code CPU-bound (audio). Capacité de front :
#   workers × threads = (2*nproc+1) × 4  → 20 requêtes concurrentes sur 2 vCPU.
worker_class = "gthread"
threads = 4

# Fenêtre de lecture de la requête par gunicorn. Nginx tamponne déjà (proxy_
# buffering on), c'est une seconde barrière si un client parle à gunicorn en direct.
graceful_timeout = 30

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
    try:
        from app import app
        with app.app_context():
            from extensions import db
            db.engine.dispose(close=False)
        server.log.info(f"[gunicorn] worker {worker.pid}: SQLAlchemy pool disposé (post_fork)")
    except Exception as exc:
        server.log.warning(f"[gunicorn] post_fork dispose failed: {exc}")
