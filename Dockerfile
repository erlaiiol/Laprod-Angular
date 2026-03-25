FROM python:3.12.10-slim

WORKDIR /usr/src/app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# UV_COMPILE_BYTECODE : compile les .py en .pyc pendant le build → démarrage plus rapide
ENV UV_COMPILE_BYTECODE=1
# UV_LINK_MODE=COPY : copie les fichiers dans le venv au lieu de faire des symlinks
#   (symlinks ne fonctionnent pas bien en Docker avec certains systèmes de fichiers)
ENV UV_LINK_MODE=copy
# UV_CACHE_DIR : dossier cache de uv (nettoyé après uv sync pour réduire la taille de l'image)
ENV UV_CACHE_DIR=/tmp/uv-cache

# Dépendances système requises par les librairies Python
# libmagic1 : python-magic (validation des types MIME des fichiers uploadés)
# ffmpeg    : pydub + ffmpeg-python (traitement audio)
# curl      : healthcheck Docker (docker compose ps vérifie /health avec curl)
# Note : psycopg2-binary embarque le driver PostgreSQL pré-compilé → pas besoin de libpq-dev/gcc
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    libmagic1 \
    ffmpeg \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# uv depuis l'image officielle Astral (recommandé en Docker)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copier les fichiers de dépendances EN PREMIER (avant le code source)
# Astuce cache Docker : ces fichiers changent rarement → cette couche est réutilisée
# entre les builds si pyproject.toml et uv.lock n'ont pas changé.
# Sans cette astuce, uv sync se relancerait à chaque `git pull` même sans nouvelle dépendance.
COPY ./pyproject.toml ./uv.lock /usr/src/app/

# Installer les dépendances dans le venv
# --frozen  : utilise exactement ce qu'il y a dans uv.lock (pas de résolution, reproductible)
# --no-dev  : exclut les dépendances de développement (tests, linters, etc.)
RUN uv sync --frozen --no-dev && rm -rf /tmp/uv-cache

# Copier le reste du code source
# (après uv sync → si le code change, seule cette couche et les suivantes sont reconstruites)
COPY . /usr/src/app/

# Sécurité : exécuter le container en utilisateur non-root
# Par défaut Docker tourne en root → mauvaise pratique, dangereux si évasion de container
# useradd -m : crée l'utilisateur appuser avec son home /home/appuser
# chown -R   : donne la propriété du dossier de l'app à appuser (nécessaire pour uv run, logs)
# useradd -m : crée l'utilisateur appuser (UID 1000) pour l'exécution de l'app
# Le chown couvre uniquement les fichiers de l'image (pas les volumes montés)
# La bascule vers appuser se fait dans entrypoint.sh via gosu (après fix des permissions)
RUN useradd -m appuser && chown -R appuser:appuser /usr/src/app

# Point d'entrée : tourne en root pour corriger les permissions des volumes,
# puis bascule vers appuser via gosu avant de lancer gunicorn
ENTRYPOINT ["/bin/bash", "/usr/src/app/entrypoint.sh"]
