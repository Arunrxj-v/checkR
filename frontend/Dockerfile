# ============================================================================
# CheckR frontend — development image (Vite dev server).
#
# For production builds use `npm run build` and serve `dist/` from any static
# host (or a multi-stage nginx image); this image intentionally runs the dev
# server so `docker compose up` gives a live-reloading workspace.
# ============================================================================
FROM node:22-alpine

WORKDIR /app

# Install dependencies first so the layer is cached between code changes.
COPY package.json package-lock.json* ./
RUN npm install

# Copy the rest of the app (overlaid by a bind mount during development).
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
