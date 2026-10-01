#!/usr/bin/env bash
# Reach the Coolify-managed Kokoro TTS container from this host on port 8880.
#
# Loopback only. Kokoro-FastAPI serves an OpenAI-compatible endpoint with NO
# authentication, so binding 0.0.0.0 here would put an open TTS endpoint on the
# public internet. UFW currently denies 8880, but this binds loopback explicitly
# so a later firewall change cannot silently publish it.
#
# Why a forwarder at all: the container publishes no ports (Coolify stack), so it
# is only reachable on the docker bridge at a dynamic IP. The bridge IS routable
# from the host, so this is a resolver + forwarder, not a proxy in the network
# sense.
#
# Why not edit the compose: Coolify owns docker-compose.coolify.one-click.yml and
# would revert the change (and drop the container) on the next deploy.
#
# The target IP is looked up by container name each time, so a restart that
# changes the bridge IP is picked up on the next reconnect instead of pinning a
# stale address.
#
# The app does NOT depend on this: it reaches Kokoro directly over the docker
# bridge at voice-tts-kokoro:8880. This serves local tools and the test suite.
set -uo pipefail

LOCAL_PORT="${KOKORO_LOCAL_PORT:-8880}"
NAME_FILTER="${KOKORO_CONTAINER:-voice-tts-kokoro}"

target_ip() {
  docker ps -q --filter "name=$NAME_FILTER" | head -1 | xargs -r \
    docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null
}

wait_for_target() {
  for _ in $(seq 1 60); do
    ip="$(target_ip)"
    [ -n "$ip" ] && { echo "$ip"; return 0; }
    sleep 2
  done
  return 1
}

main() {
  if ! ip="$(wait_for_target)"; then
    echo "kokoro: no container matching '$NAME_FILTER' is running" >&2
    exit 1
  fi
  echo "kokoro: forwarding 127.0.0.1:$LOCAL_PORT -> $ip:8880 (loopback only)"
  # Re-resolve on every outer loop so an IP change recovers automatically.
  while true; do
    ip="$(target_ip)"
    if [ -z "$ip" ]; then
      echo "kokoro: target gone, waiting for it to come back" >&2
      sleep 10
      continue
    fi
    # bind=127.0.0.1 is the security control: not a default to be relied on.
    socat -T30 TCP4-LISTEN:"$LOCAL_PORT",bind=127.0.0.1,reuseaddr,fork \
                TCP4:"$ip":8880 2>&1 | sed "s/^/kokoro: /"
    echo "kokoro: forwarder dropped, re-establishing in 5s" >&2
    sleep 5
  done
}

main "$@"
