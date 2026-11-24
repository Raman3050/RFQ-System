# Dev image: Vite dev server with HMR. A multi-stage Nginx image is added in Phase 7.
FROM node:24-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]
