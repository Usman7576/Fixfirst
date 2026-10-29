# Local development image for the SPA (production builds are served by Vercel).
# Build from the repo root: docker build -f infra/docker/web.Dockerfile .
FROM node:24-alpine
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY apps/web ./
RUN chown -R node:node /app
USER node
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
