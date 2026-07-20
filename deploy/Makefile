# AIOS production management
.PHONY: install start stop restart status logs update

install: ## First-time setup - install systemd service + log dir
	mkdir -p /var/log/aios
	cp deploy/aios-server.service /etc/systemd/system/
	systemctl daemon-reload
	@echo "Run 'make start' to start the server"

start: ## Start AIOS daemon
	systemctl start aios-server
	systemctl enable aios-server
	@echo "AIOS started - status: $$(systemctl is-active aios-server)"

stop: ## Stop AIOS daemon
	systemctl stop aios-server || true

restart: stop start ## Restart AIOS daemon

status: ## Show AIOS daemon status
	systemctl status aios-server --no-pager

logs: ## Tail AIOS logs
	journalctl -u aios-server -f -n 50 --no-pager

logs-all: ## Full AIOS logs
	journalctl -u aios-server --no-pager

caddy-install: ## Install Caddy reverse proxy
	cp deploy/Caddyfile /etc/caddy/Caddyfile
	systemctl restart caddy
	@echo "Caddy restarted - https://178.105.181.38:443"

caddy-logs: ## Tail Caddy logs
	journalctl -u caddy -f -n 30 --no-pager

update: ## Pull latest code and restart
	git pull origin main
	pip3 install --break-system-packages -e . 2>&1 | tail -3
	make restart
	@echo "Updated and restarted"
