#!/bin/bash
# Rebuild AIOS app container with updated website/index.html
# Execute NO SERVIDOR COOLIFY (onde o docker compose roda)

set -e

echo "🔄 Rebuilding AIOS app container..."

cd /root/ai_projects/claude_projects/pixor_aios  # Ajuste se path diferente

# 1. Parar container app
docker compose -f docker-compose.coolify.yml stop app

# 2. Rebuild sem cache
docker compose -f docker-compose.coolify.yml build --no-cache app

# 3. Subir novamente
docker compose -f docker-compose.coolify.yml up -d app

# 4. Aguardar health check
echo "⏳ Aguardando health check..."
for i in {1..30}; do
    if curl -sf http://localhost:8777/health/live > /dev/null 2>&1; then
        echo "✅ App saudável!"
        break
    fi
    sleep 2
done

# 5. Verificar conteúdo
echo "🔍 Verificando home page..."
curl -s http://localhost:8777/ | grep -oP '(?<=Evolution API instances: ).*?(?=</li>)' | head -3

echo "✅ Deploy concluído! Acesse http://178.105.181.38:8777/"
