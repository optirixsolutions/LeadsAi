# Build context: repository root (the web app depends on workspace packages)
FROM node:22-alpine AS deps
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY packages/contracts/package.json packages/contracts/
RUN pnpm install --frozen-lockfile --filter @salesiq/web...

FROM deps AS build
COPY packages/contracts packages/contracts
COPY apps/web apps/web
# API rewrites are resolved at build time; override for other topologies.
ARG SALESIQ_API_URL=http://api:8000
ENV NEXT_TELEMETRY_DISABLED=1 SALESIQ_STANDALONE=1 SALESIQ_API_URL=$SALESIQ_API_URL
RUN pnpm --filter @salesiq/web build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN adduser -S -u 10001 salesiq
COPY --from=build --chown=salesiq /repo/apps/web/.next/standalone ./
COPY --from=build --chown=salesiq /repo/apps/web/.next/static ./apps/web/.next/static
USER salesiq
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
