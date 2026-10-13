#!/usr/bin/env bash
# Compuerta automática de calidad (spec infraestructura/0011, sección 4).
# Se corre antes de cada commit y en la CI. Se detiene en el primer fallo.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
[[ -x "$PY" ]] || PY=python

paso() { printf '\n== %s\n' "$1"; }

paso "ruff: lint"
"$PY" -m ruff check .

paso "ruff: formato"
"$PY" -m ruff format --check .

paso "bandit: análisis estático de seguridad"
"$PY" -m bandit -c pyproject.toml -r app migrations scripts -q

paso "pip-audit: vulnerabilidades en dependencias"
"$PY" -m pip_audit -r requirements-dev.txt --progress-spinner off

paso "gitleaks: secretos en el historial y en el árbol de trabajo"
gitleaks git --no-banner --redact --config .gitleaks.toml .
gitleaks dir --no-banner --redact --config .gitleaks.toml .

paso "migraciones: bajar todo y volver a subir en la base de prueba"
BASE_PRUEBA="${DB_NAME_TEST:-lablinea_test}"
"$PY" -m alembic -x "base=$BASE_PRUEBA" downgrade base
"$PY" -m alembic -x "base=$BASE_PRUEBA" upgrade head

paso "pytest: pruebas, guardián de RLS, fuzzing y cobertura (mínimo 85%)"
"$PY" -m pytest -q --cov --cov-report=term

printf '\nOK: compuerta automática en verde.\n'
