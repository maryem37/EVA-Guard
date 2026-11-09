# Réseau privé Ethereum (sans Docker)

Prérequis : Ubuntu (VM ou WSL2), Geth 1.13.15, jq, Python 3.

1. Installer Geth 1.13.15 :
   wget https://gethstore.blob.core.windows.net/builds/geth-linux-amd64-1.13.15-c5ba367e.tar.gz
   tar -xzf geth-linux-amd64-1.13.15-c5ba367e.tar.gz
   sudo cp geth-linux-amd64-1.13.15-c5ba367e/geth /usr/local/bin/
2. sudo apt install -y git curl jq python3-pip python3-venv
3. ./infra/setup_network.sh     # une seule fois
4. ./infra/start_network.sh     # démarre les 5 nœuds
5. ./infra/stop_network.sh      # arrête le réseau

Nœud victime = node2 (RPC 8546, métriques 6062). Données dans ~/eva-data (hors dépôt).
