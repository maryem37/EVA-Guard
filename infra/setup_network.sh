#!/bin/bash
# Prépare le réseau privé EVA-Guard sur CETTE machine (compte, genesis, init des 5 nœuds)
set -e
BASE=~/eva-data

command -v geth >/dev/null || { echo "ERREUR : geth n'est pas installé (voir le guide)"; exit 1; }
command -v jq   >/dev/null || { echo "ERREUR : jq n'est pas installé (sudo apt install jq)"; exit 1; }
geth version | grep -q "Version: 1.13" || { echo "ERREUR : il faut Geth 1.13.x"; geth version | grep Version; exit 1; }

mkdir -p "$BASE"/node{1,2,3,4,5} "$BASE/logs"

# 1. Compte signataire (créé une seule fois)
[ -f "$BASE/pwd.txt" ] || echo "motdepasse" > "$BASE/pwd.txt"
if [ -z "$(ls -A "$BASE/node1/keystore" 2>/dev/null)" ]; then
  geth --datadir "$BASE/node1" account new --password "$BASE/pwd.txt" > /dev/null 2>&1
fi
ADDR=$(ls "$BASE/node1/keystore" | head -1 | sed 's/.*--//' | tr 'A-F' 'a-f')
echo "$ADDR" > "$BASE/addr.txt"
echo "Adresse signataire : 0x$ADDR"

# 2. genesis.json
Z64=$(printf '0%.0s' {1..64})
Z130=$(printf '0%.0s' {1..130})
cat > "$BASE/genesis.json" <<EOF
{
  "config": {
    "chainId": 12345,
    "homesteadBlock": 0, "eip150Block": 0, "eip155Block": 0, "eip158Block": 0,
    "byzantiumBlock": 0, "constantinopleBlock": 0, "petersburgBlock": 0,
    "istanbulBlock": 0, "berlinBlock": 0, "londonBlock": 0,
    "clique": { "period": 5, "epoch": 30000 }
  },
  "difficulty": "1",
  "gasLimit": "8000000",
  "extradata": "0x${Z64}${ADDR}${Z130}",
  "alloc": { "${ADDR}": { "balance": "1000000000000000000000" } }
}
EOF
jq . "$BASE/genesis.json" > /dev/null && echo "genesis.json OK"

# 3. Initialisation des nœuds
for i in 1 2 3 4 5; do
  if [ -d "$BASE/node$i/geth/chaindata" ]; then
    echo "node$i déjà initialisé, on passe"
  else
    geth --datadir "$BASE/node$i" init "$BASE/genesis.json" > "$BASE/logs/init_node$i.log" 2>&1
    echo "node$i initialisé"
  fi
done
echo "Installation terminée. Lancez : infra/start_network.sh"
