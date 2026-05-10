#!/bin/sh
set -eu

missing=""
for name in KEYCLOAK_ADMIN KEYCLOAK_ADMIN_PASSWORD POSTGRES_PASSWORD; do
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then
    missing="$missing $name"
  fi
done

if [ "${QOS_JIRA_ENABLED:-false}" = "true" ]; then
  for name in JIRA_EMAIL JIRA_TOKEN JIRA_URL JIRA_PROJECT_KEY; do
    eval "value=\${$name:-}"
    if [ -z "$value" ]; then
      missing="$missing $name"
    fi
  done
fi

if [ -n "$missing" ]; then
  echo "Missing required environment variables:$missing" >&2
  echo "Copy .env.example to .env, fill the values, and run docker compose again." >&2
  exit 1
fi

exec "$@"
