FROM node:20-slim AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
# Compose's `web` service serves a static build with no dev-server proxy, so
# it needs the api's published host port baked in at build time.
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM node:20-slim
WORKDIR /app
RUN npm install -g serve
COPY --from=build /app/dist ./dist
EXPOSE 4173
CMD ["serve", "-s", "dist", "-l", "4173"]
