# ── Stage 1: deps ─────────────────────────────────────────────────────────────
FROM node:20-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --omit=dev

# ── Stage 2: build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# BACKEND_URL is consumed at build time by next.config.mjs for rewrites.
# Pass it in with --build-arg or via the compose build.args block.
ARG BACKEND_URL=http://localhost:8000
ENV BACKEND_URL=$BACKEND_URL

# NEXT_PUBLIC_* vars must be present at build time to be baked into the bundle.
ARG NEXT_PUBLIC_BACKEND_URL=
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL

RUN npm run build

# ── Stage 3: runner ───────────────────────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
# next start respects PORT; default 3000
ENV PORT=3000

RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs

# Standalone output (smaller image); falls back to full .next if not enabled.
# Copy only what next start needs.
COPY --from=builder /app/public        ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder /app/node_modules  ./node_modules
COPY --from=builder /app/package.json  ./package.json

USER nextjs

EXPOSE 3000

CMD ["npm", "run", "start"]
