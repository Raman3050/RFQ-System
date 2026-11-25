# syntax=docker/dockerfile:1.7
# Targets:
#   dev  — Vite dev server with HMR (docker-compose.yml)
#   prod — static build served by unprivileged Nginx, which also proxies /api, /health
#          and the /ws WebSocket to the API (docker-compose.prod.yml)

FROM node:24-alpine AS dev
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]


FROM dev AS build
RUN npm run build


FROM nginxinc/nginx-unprivileged:1.27-alpine AS prod
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
