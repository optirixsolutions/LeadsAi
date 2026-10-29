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
ENV NEXT_TELEMETRY_DISABLED=1 SALESIQ_STANDALONE=1
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
