FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --legacy-peer-deps || yarn || true
COPY . .
RUN npm run build
RUN mkdir -p .next/standalone/.next \
    && cp -R .next/static .next/standalone/.next/static \
    && if [ -d public ]; then cp -R public .next/standalone/public; fi
EXPOSE 3000
CMD ["node", ".next/standalone/server.js"]
