#!/bin/bash
# Usage : ./collect/run_normal.sh [durée_s] [label]
DURATION=${1:-1800}
LABEL=${2:-normal_mixed}
cd ~/EVA-Guard || exit 1
source .venv/bin/activate

BLK=$(curl -s -m 3 -X POST -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
  http://127.0.0.1:8546 | jq -r .result 2>/dev/null)
[[ "$BLK" == 0x* ]] || { echo "ERREUR : victime injoignable. Lancez infra/start_network.sh"; exit 1; }
PEERS=$(curl -s -m 3 -X POST -H "Content-Type: application/json" \
  --data '{"jsonrpc":"2.0","method":"net_peerCount","params":[],"id":1}' \
  http://127.0.0.1:8546 | jq -r .result)
echo "Victime : bloc=$((BLK)) pairs=$((PEERS))"
[ "$((PEERS))" -lt 4 ] && { echo "ERREUR : moins de 4 pairs, baseline non représentative."; exit 1; }

cleanup() { kill "$TPID" 2>/dev/null; wait "$TPID" 2>/dev/null; }
trap cleanup EXIT
python collect/traffic.py --profile mixed --duration $((DURATION + 20)) &
TPID=$!
sleep 10
python collect/collect.py --label "$LABEL" --duration "$DURATION"

echo "=== Terminé ==="
wc -l data/raw/run_${LABEL}_*.csv | tail -2
echo "--- Chronologie du trafic ---"
cat "$(ls -t data/raw/traffic_*.csv | head -1)"
