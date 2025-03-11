###############################################################################
# STAGE 1: Builder image (pour installer les dépendances)
###############################################################################
FROM python:3.10-slim-bullseye AS builder

# Définir des variables d'environnement pour Poetry
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.7.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_HOME="/opt/poetry" \
    PYSETUP_PATH="/opt/pysetup"

# Définir le répertoire de travail
WORKDIR $PYSETUP_PATH

# Installer les dépendances système nécessaires (curl pour installer Poetry)
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        curl \
        build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    # Installer Poetry - isolé dans son propre répertoire
    && curl -sSL https://install.python-poetry.org | python3 - \
    && cd /usr/local/bin \
    && ln -s /opt/poetry/bin/poetry

# Copier seulement les fichiers nécessaires à l'installation des dépendances
COPY app/pyproject.toml app/poetry.lock* ./

# Installer les dépendances runtime uniquement
RUN poetry export --without dev --without-hashes -f requirements.txt -o requirements.txt

# Créer une version dev séparée si nécessaire
RUN poetry export --with dev --without-hashes -f requirements.txt -o requirements-dev.txt

###############################################################################
# STAGE 2: Runtime image (image finale minimale)
###############################################################################
FROM python:3.10-slim-bullseye AS runtime

# Définir des variables d'environnement
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/code" \
    PATH="/code/.venv/bin:$PATH" \
    PORT=9090

WORKDIR /code

# Installer les dépendances système minimales requises pour l'exécution
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copier les requirements depuis l'étape builder
COPY --from=builder /opt/pysetup/requirements.txt ./requirements.txt

# Installer les dépendances dans un environnement virtuel léger
RUN python -m venv /code/.venv \
    && .venv/bin/pip install --upgrade pip \
    && .venv/bin/pip install --no-cache-dir -r requirements.txt

# Copier le code de l'application
COPY app /code/

# Créer et utiliser un utilisateur non-root
RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && chown -R app:app /code

USER app

# Exposer le port
EXPOSE $PORT

# Commande par défaut pour démarrer l'application
# Peut être remplacée par docker-compose ou par une commande au lancement
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9090"]

# Pour le débogage et les migrations, on peut préférer utiliser ces commandes:
# CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 9090"]

# HEALTHCHECK pour vérifier que l'application fonctionne
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:$PORT/ || exit 1
