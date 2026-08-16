# Base: deps + source (shared by dev and prod builds)
FROM node:22-alpine AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .

# Prod build (future deployment phase: docker build --target prod)
FROM base AS builder
RUN npm run build

FROM node:22-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /app/next.config.mjs ./next.config.mjs
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
EXPOSE 3000
CMD ["npm", "run", "start"]

# Default dev target: `next dev` with hot reload (docker compose dev bring-up)
FROM base AS dev
EXPOSE 3000
CMD ["npm", "run", "dev"]