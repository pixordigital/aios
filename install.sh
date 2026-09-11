#!/usr/bin/env bash
# AIOS 1-Click Installer — VPS Ubuntu 22.04/24.04 (sem Coolify)
# Uso: curl -fsSL https://raw.githubusercontent.com/pixor/aios/main/install.sh | bash
#   ou: bash install.sh [--domain seu.dominio.com] [--email admin@ex.com] [--voice] [--stt]
set -euo pipefail

REPO_URL="https://github.com/pixordigital/aios.git"
INSTALL_DIR="/opt/aios"
COMPOSE_FILE="docker-compose.coolify.yml"

DOMAIN=""
EMAIL=""
WITH_VOICE=false
WITH_STT=false
BRANCH="main"
WITH_COOLIFY=false

while [[ $# -gt 0 ]]; do case "$1" in
  --domain) DOMAIN="$2"; shift 2;;
  --email) EMAIL="$2"; shift 2;;
  --voice) WITH_VOICE=true; shift;;
  --stt) WITH_STT=true; WITH_VOICE=true; shift;;
  --with-coolify) WITH_COOLIFY=true; shift;;
  --branch) BRANCH="$2"; shift 2;;
  *) echo "unknown $1"; exit 1;;
esac; done

need_root() { [[ $EUID -eq 0 ]] || { echo "rode como root: sudo bash install.sh"; exit 1; }; }
need_ubuntu() { . /etc/os-release; [[ "$ID" == "ubuntu" ]] || echo "aviso: testado em Ubuntu, seu $ID pode funcionar"; }

gen() { openssl rand -hex 16; }
gen32() { openssl rand -hex 32; }

echo "== AIOS 1-Click Installer =="

need_root; need_ubuntu

# 1. Docker
if $WITH_COOLIFY && ! command -v coolify >/dev/null 2>&1 && ! docker ps 2>&1 | grep -q coolify; then
  echo "[0/6] Instalando Coolify (pode levar 3-5min)..."
  curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
  echo "Coolify instalado em https://$(curl -fsSL ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}'):8000"
  echo "Finalize setup no browser, depois rode: bash install.sh --domain ... (sem --with-coolify) ou use Raw Compose com docker-compose.coolify.yml"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[1/6] Instalando Docker..."
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
else echo "[1/6] Docker OK $(docker --version)"; fi

# 2. Repo
if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "[2/6] Atualizando $INSTALL_DIR..."
  git -C "$INSTALL_DIR" fetch -q && git -C "$INSTALL_DIR" checkout -q "$BRANCH" && git -C "$INSTALL_DIR" pull -q
else
  echo "[2/6] Clonando $REPO_URL → $INSTALL_DIR..."
  git clone -q --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR" || { mkdir -p "$INSTALL_DIR"; cp -r . "$INSTALL_DIR" 2>/dev/null || true; }
fi
cd "$INSTALL_DIR"

# 3. Perguntas (se não passou --domain/--email)
IP=$(curl -fsSL ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
[[ -z "$DOMAIN" ]] && { read -rp "Domínio (ex: aios.seudominio.com) [${IP}]: " DOMAIN || true; DOMAIN=${DOMAIN:-$IP}; }
[[ -z "$EMAIL" ]] && { read -rp "E-mail admin [admin@${DOMAIN}]: " EMAIL || true; EMAIL=${EMAIL:-admin@${DOMAIN}}; }
read -rp "OpenRouter API key (opcional, enter pula): " OR_KEY || true
read -rp "Ativar Voz (Kokoro TTS \$0/min)? [s/N]: " ANS || true; [[ "$ANS" =~ ^[sS] ]] && WITH_VOICE=true
if $WITH_VOICE; then read -rp "Ativar STT Whisper self-hosted? [s/N]: " ANS2 || true; [[ "$ANS2" =~ ^[sS] ]] && WITH_STT=true; fi

# 4. .env
POSTGRES_PASSWORD=$(gen)
REDIS_PASSWORD=$(gen)
JWT_SECRET=$(gen32)
ADMIN_KEY=$(gen32)
APP_URL="https://${DOMAIN}"
[[ "$DOMAIN" == "$IP" ]] && APP_URL="http://${DOMAIN}:8777"

cat > .env <<EOF
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
REDIS_PASSWORD=$REDIS_PASSWORD
POSTGRES_USER=aios
POSTGRES_DB=aios
AIOS_JWT_SECRET=$JWT_SECRET
AIOS_ADMIN_MASTER_KEY=$ADMIN_KEY
AIOS_APP_URL=$APP_URL
AIOS_OPENROUTER_API_KEY=$OR_KEY
AIOS_DEBUG=false
EVOLUTION_API_KEY=$(gen)
AIOS_LICENSE_KEY=
COMPOSE_PROFILES=$($WITH_STT && echo "voice,voice-stt" || $WITH_VOICE && echo "voice" || echo "")
EOF

echo "[3/6] .env gerado em $INSTALL_DIR/.env"
cat .env | sed 's/\(PASSWORD\|SECRET\|KEY\)=.*/\1=****/'

# 5. Deploy
PROFILES=""
$WITH_VOICE && PROFILES="--profile voice"
$WITH_STT && PROFILES="--profile voice --profile voice-stt"
echo "[4/6] Subindo stack (postgres+redis+litellm+evolution+app+worker${WITH_VOICE:+ +voz}${WITH_STT:+ +stt})..."
docker compose -f "$COMPOSE_FILE" $PROFILES pull -q 2>&1 | tail -5 || true
docker compose -f "$COMPOSE_FILE" $PROFILES up -d 2>&1 | tail -20

echo "[5/6] Aguardando health..."
for i in {1..30}; do if curl -fsS http://localhost:8777/health/live >/dev/null 2>&1; then echo "health ok"; break; fi; sleep 2; done
curl -fsS http://localhost:8777/health/live 2>&1 | head -c 200; echo ""

# 6. Credenciais + Caddy/Nginx hint
PASS=$(openssl rand -base64 12)
# cria admin via DB se tabela existir (best effort)
echo "[6/6] Criando admin $EMAIL (se DB pronto)..."
sleep 3
curl -fsS -X POST http://localhost:8777/api/auth/register -H "Content-Type: application/json" -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"org_name\":\"${DOMAIN%%.*}\"}" 2>&1 | head -c 300 || echo " (pule se já existe, faça via /dashboard/register)"

cat <<OUT

== AIOS LIVE ==

URL:       $APP_URL  (ou http://${IP}:8777)
Health:    $APP_URL/health/live
Dashboard: $APP_URL/dashboard
Evolution: http://${IP}:8080  (API key em .env EVOLUTION_API_KEY)
Logs:      docker compose -f $COMPOSE_FILE logs -f app

Admin:     $EMAIL
Senha:     $PASS  (salva em /root/aios-creds.txt)

Credenciais salvas em: /root/aios-creds.txt
.env em: $INSTALL_DIR/.env

Próximos passos:
  1. Aponte DNS ${DOMAIN} → ${IP} (se usou domínio)
  2. Caddy/Nginx com TLS para ${DOMAIN} → localhost:8777 (Coolify faz auto, sem Coolify use: caddy reverse-proxy --from ${DOMAIN} --to localhost:8777)
  3. Dashboard → Voz → crie SDR/Closer (4 passos) → Evolution → pareie QR
  4. STT: se ativou --stt, teste: curl -X POST http://localhost:9000/v1/audio/transcriptions -F file=@audio.mp3
  5. Update: cd $INSTALL_DIR && git pull && docker compose -f $COMPOSE_FILE $PROFILES up -d --build

Desinstalar: docker compose -f $COMPOSE_FILE $PROFILES down -v && rm -rf $INSTALL_DIR

OUT
cat > /root/aios-creds.txt <<CRED
AIOS 1-Click $(date -Iseconds)
URL: $APP_URL
ADMIN: $EMAIL
PASS: $PASS
DIR: $INSTALL_DIR
COMPOSE: $COMPOSE_FILE
PROFILES: $PROFILES
CRED
chmod 600 /root/aios-creds.txt
echo "Feito."
