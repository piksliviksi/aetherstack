#!/bin/sh
set -eu

database=/data/webui.db
email=${AETHER_LOCAL_WEBUI_EMAIL:-}

if [ -z "$email" ] && [ -f "$database" ]; then
  admin_count=$(sqlite3 -readonly "$database" "SELECT count(*) FROM user WHERE role = 'admin';" 2>/dev/null || true)
  if [ "$admin_count" = "1" ]; then
    email=$(sqlite3 -readonly "$database" "SELECT email FROM user WHERE role = 'admin' ORDER BY created_at LIMIT 1;" 2>/dev/null || true)
  elif [ "$admin_count" != "0" ]; then
    echo "AetherStack local UI cannot choose between multiple Open WebUI admins. Set AETHER_LOCAL_WEBUI_EMAIL to the existing admin email." >&2
    exit 1
  fi
fi

if [ -z "$email" ]; then
  email=local@aetherstack.invalid
fi

if ! printf '%s' "$email" | grep -Eq '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$'; then
  echo "AETHER_LOCAL_WEBUI_EMAIL is not a safe email value." >&2
  exit 1
fi

escaped_email=$(printf '%s' "$email" | sed 's/[&|]/\\&/g')
sed "s|__AETHER_LOCAL_EMAIL__|$escaped_email|g" \
  /etc/nginx/aetherstack.conf.template \
  > /etc/nginx/conf.d/default.conf
chmod 600 /etc/nginx/conf.d/default.conf
