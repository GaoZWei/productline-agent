FROM node:22-alpine

WORKDIR /app
COPY server.mjs .
COPY src ./src

EXPOSE 5173
CMD ["node", "server.mjs"]

