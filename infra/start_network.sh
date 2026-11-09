#!/bin/bash
# Démarre le réseau privé EVA-Guard (5 nœuds Geth, Clique)
BASE=~/eva-data
LOG=$BASE/logs
mkdir -p "$LOG"
ADDR=$(cat "$BASE/addr.txt")

rpc() { curl -s -X POST -H "Content-Type: application/json" --data "$2" "http://127.0.0.1:$1"; }
get_enode() {
  rpc "$1" '{"jsonrpc":"2.0","method":"admin_nodeInfo","params":[],"id":1}' \
    | jq -r .result.enode 2>/dev/null | sed 's/@[^:]*:/@127.0.0.1:/; s/?.*//'
}

COMMON="--networkid 12345 --nat none --netrestrict 127.0.0.0/8 \
  --http --http.addr 127.0.0.1 --http.api eth,net,web3,admin,txpool \
  --metrics --metrics.addr 127.0.0.1"

echo "Démarrage du nœud 1 (signataire)..."
nohup geth --datadir "$BASE/node1" $COMMON \
  --port 30301 --http.port 8545 --authrpc.port 8551 --metrics.port 6061 \
  --unlock "0x$ADDR" --password "$BASE/pwd.txt" \
  --mine --miner.etherbase "0x$ADDR" --allow-insecure-unlock \
  > "$LOG/node1.log" 2>&1 &

# Attendre que le RPC du nœud 1 réponde
for t in $(seq 1 30); do
  ENODE=$(get_enode 8545)
  [[ "$ENODE" == enode://* ]] && break
  sleep 1
done
[[ "$ENODE" == enode://* ]] || { echo "Échec : nœud 1 injoignable, voir $LOG/node1.log"; exit 1; }
echo "$ENODE" > "$BASE/enode.txt"

for i in 2 3 4 5; do
  echo "Démarrage du nœud $i..."
  nohup geth --datadir "$BASE/node$i" $COMMON \
    --port $((30300+i)) --http.port $((8544+i)) --authrpc.port $((8550+i)) \
    --metrics.port $((6060+i)) --bootnodes "$ENODE" \
    > "$LOG/node$i.log" 2>&1 &
done

sleep 8
# Maillage : les nœuds 2 à 5 se connectent entre eux
for i in 2 3 4 5; do
  for j in 2 3 4 5; do
    [ "$i" = "$j" ] && continue
    E=$(get_enode $((8544+j)))
    rpc $((8544+i)) "{\"jsonrpc\":\"2.0\",\"method\":\"admin_addPeer\",\"params\":[\"$E\"],\"id\":1}" > /dev/null
  done
done

sleep 3
echo "=== État du réseau ==="
for i in 1 2 3 4 5; do
  P=$(rpc $((8544+i)) '{"jsonrpc":"2.0","method":"net_peerCount","params":[],"id":1}' | jq -r .result)
  B=$(rpc $((8544+i)) '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' | jq -r .result)
  echo "node$i : pairs=$((P)) bloc=$((B))"
done
