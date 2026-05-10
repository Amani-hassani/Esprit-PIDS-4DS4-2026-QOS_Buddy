FROM node:20-slim AS builder

WORKDIR /app

# Copie des fichiers de dépendances
COPY package*.json .
RUN npm ci

# Copie du code source
COPY . .

# Build
RUN npm run build

# Stage de production
FROM nginx:alpine AS runner

COPY --from=builder /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]