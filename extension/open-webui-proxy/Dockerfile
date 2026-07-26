FROM nginx:1.29.4-alpine@sha256:4870c12cd2ca986de501a804b4f506ad3875a0b1874940ba0a2c7f763f1855b2

RUN apk add --no-cache sqlite
COPY default.conf.template /etc/nginx/aetherstack.conf.template
COPY 40-aetherstack-local-user.sh /docker-entrypoint.d/40-aetherstack-local-user.sh
RUN chmod 755 /docker-entrypoint.d/40-aetherstack-local-user.sh
