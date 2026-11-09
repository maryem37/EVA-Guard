#!/usr/bin/env python3
"""EVA-Guard - collecte multi-couches (P2P / hôte / API) sur le nœud victime (node2)."""
import argparse, csv, os, re, time
from datetime import datetime
import psutil, requests

VICTIM_RPC = "http://127.0.0.1:8546"
REF_RPC = "http://127.0.0.1:8545"                 # node1 = référence de sync
VICTIM_METRICS = "http://127.0.0.1:6062/debug/metrics/prometheus"
VICTIM_TAG = "eva-data/node2"
VICTIM_P2P_PORT = 30302
P2P_PORTS = set(range(30301, 30306))
LOG_PATH = os.path.expanduser("~/eva-data/logs/node2.log")

FIELDS = [
    "timestamp",
    # --- couche réseau P2P ---
    "p2p_n_peers", "p2p_n_inbound", "p2p_n_outbound", "p2p_joined", "p2p_left", "p2p_churn",
    "p2p_sync_lag", "p2p_in_kbps", "p2p_out_kbps",
    "p2p_tcp_established", "p2p_tcp_syn_recv", "p2p_tcp_time_wait",
    "p2p_log_warn", "p2p_log_error", "p2p_log_peer_search",
    # --- couche hôte ---
    "host_cpu_geth", "host_rss_geth_mb", "host_threads_geth", "host_fds_geth",
    "host_cpu_sys", "host_mem_sys_pct", "host_load1", "host_lo_kbps",
    # --- couche API (RPC) ---
    "api_lat_blocknumber_ms", "api_lat_peercount_ms", "api_lat_getblock_ms",
    "api_lat_peers_ms", "api_ok_ratio", "api_block", "api_is_syncing",
    "api_txpool_pending", "api_txpool_queued",
    "label"]


def call(url, method, params=None, timeout=3):
    """Appel RPC chronométré -> (résultat, latence_ms, succès)."""
    t0 = time.time()
    try:
        r = requests.post(url, timeout=timeout, json={
            "jsonrpc": "2.0", "method": method, "params": params or [], "id": 1}).json()
        return r.get("result"), (time.time() - t0) * 1000, ("result" in r and "error" not in r)
    except Exception:
        return None, (time.time() - t0) * 1000, False


def to_int(x):
    try:
        return int(x, 16)
    except Exception:
        return None


def find_geth():
    for p in psutil.process_iter(["cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if "geth" in cmd and VICTIM_TAG in cmd:
            return p
    return None


def geth_metrics():
    out = {"p2p_ingress": None, "p2p_egress": None}
    try:
        for line in requests.get(VICTIM_METRICS, timeout=3).text.splitlines():
            m = re.match(r"^(p2p_ingress|p2p_egress)(?:_total)?\s+([0-9.eE+-]+)$", line)
            if m:
                out[m.group(1)] = float(m.group(2))
    except Exception:
        pass
    return out


def tcp_stats(vpid):
    """États TCP du port P2P de la victime, lus dans le noyau (indépendant de Geth)."""
    est = syn = tw = 0
    try:
        for c in psutil.net_connections(kind="tcp"):
            lp = c.laddr.port if c.laddr else None
            rp = c.raddr.port if c.raddr else None
            if lp == VICTIM_P2P_PORT:                      # connexions entrantes
                if c.status == "ESTABLISHED": est += 1
                elif c.status == "SYN_RECV": syn += 1
                elif c.status == "TIME_WAIT": tw += 1
            elif c.pid == vpid and rp in P2P_PORTS and c.status == "ESTABLISHED":
                est += 1                                   # connexions sortantes
    except Exception:
        pass
    return est, syn, tw


class LogTail:
    def __init__(self, path):
        self.path = path
        self.pos = os.path.getsize(path) if os.path.exists(path) else 0

    def read_new(self):
        try:
            size = os.path.getsize(self.path)
            if size < self.pos:
                self.pos = 0
            with open(self.path, "r", errors="ignore") as f:
                f.seek(self.pos); txt = f.read(); self.pos = f.tell()
        except OSError:
            return 0, 0, 0
        return txt.count("WARN ["), txt.count("ERROR ["), txt.count("Looking for peers")


def lo_bytes():
    n = psutil.net_io_counters(pernic=True).get("lo")
    return (n.bytes_sent + n.bytes_recv) if n else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="normal", help="normal / benign / eclipse / dos_p2p")
    ap.add_argument("--duration", type=int, default=1800)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--outdir", default="data/raw")
    args = ap.parse_args()

    proc = find_geth()
    if proc is None:
        print("ERREUR : processus Geth de node2 introuvable. Réseau démarré ?")
        return
    os.makedirs(args.outdir, exist_ok=True)
    path = os.path.join(args.outdir, f"run_{args.label}_{datetime.now():%Y%m%d_%H%M%S}.csv")
    print(f"Écriture dans {path} (Ctrl+C pour arrêter)")

    # Amorçage (évite une première ligne fausse)
    proc.cpu_percent(None); psutil.cpu_percent(None)
    logtail = LogTail(LOG_PATH)
    p0, _, _ = call(VICTIM_RPC, "admin_peers")
    prev_ids = {p["id"] for p in (p0 or [])}
    prev_lo, prev_met = lo_bytes(), geth_metrics()
    prev_t = start = time.time()
    k = 0

    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        try:
            while True:
                k += 1
                target = start + k * args.interval
                if target - start > args.duration:
                    break
                time.sleep(max(0, target - time.time()))
                now = time.time(); dt = now - prev_t

                # ===== Couche API (RPC) : sondes chronométrées =====
                blk, l_blk, ok1 = call(VICTIM_RPC, "eth_blockNumber")
                _,   l_pc,  ok2 = call(VICTIM_RPC, "net_peerCount")
                _,   l_gb,  ok3 = call(VICTIM_RPC, "eth_getBlockByNumber", ["latest", False])
                peers, l_pe, ok4 = call(VICTIM_RPC, "admin_peers")
                syncing, _, ok5 = call(VICTIM_RPC, "eth_syncing")
                txp, _, ok6 = call(VICTIM_RPC, "txpool_status")
                ref, _, _ = call(REF_RPC, "eth_blockNumber")
                blk_i, ref_i = to_int(blk), to_int(ref)
                txp = txp or {}

                # ===== Couche P2P =====
                peers = peers or []
                ids = {p["id"] for p in peers}
                n_in = sum(1 for p in peers if p.get("network", {}).get("inbound"))
                est, syn, tw = tcp_stats(proc.pid)
                lw, le, lps = logtail.read_new()
                met = geth_metrics()

                def mrate(key):
                    if met[key] is None or prev_met[key] is None:
                        return None
                    return round((met[key] - prev_met[key]) * 8 / 1000 / dt, 2)

                # ===== Couche hôte =====
                if not proc.is_running():
                    proc = find_geth()
                    if proc is None:
                        print("Processus Geth perdu, arrêt."); break
                    proc.cpu_percent(None)
                try:
                    cpu_g = proc.cpu_percent(None)
                    rss = round(proc.memory_info().rss / 1e6, 1)
                    thr, fds = proc.num_threads(), proc.num_fds()
                except Exception:
                    cpu_g = rss = thr = fds = None
                lo = lo_bytes()
                lo_kbps = round((lo - prev_lo) * 8 / 1000 / dt, 1) if (lo and prev_lo) else None

                row = {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "p2p_n_peers": len(peers), "p2p_n_inbound": n_in,
                    "p2p_n_outbound": len(peers) - n_in,
                    "p2p_joined": len(ids - prev_ids), "p2p_left": len(prev_ids - ids),
                    "p2p_churn": len(ids - prev_ids) + len(prev_ids - ids),
                    "p2p_sync_lag": (ref_i - blk_i) if (blk_i is not None and ref_i is not None) else None,
                    "p2p_in_kbps": mrate("p2p_ingress"), "p2p_out_kbps": mrate("p2p_egress"),
                    "p2p_tcp_established": est, "p2p_tcp_syn_recv": syn, "p2p_tcp_time_wait": tw,
                    "p2p_log_warn": lw, "p2p_log_error": le, "p2p_log_peer_search": lps,
                    "host_cpu_geth": cpu_g, "host_rss_geth_mb": rss,
                    "host_threads_geth": thr, "host_fds_geth": fds,
                    "host_cpu_sys": psutil.cpu_percent(None),
                    "host_mem_sys_pct": psutil.virtual_memory().percent,
                    "host_load1": round(os.getloadavg()[0], 2), "host_lo_kbps": lo_kbps,
                    "api_lat_blocknumber_ms": round(l_blk, 1), "api_lat_peercount_ms": round(l_pc, 1),
                    "api_lat_getblock_ms": round(l_gb, 1), "api_lat_peers_ms": round(l_pe, 1),
                    "api_ok_ratio": round(sum([ok1, ok2, ok3, ok4, ok5, ok6]) / 6, 2),
                    "api_block": blk_i, "api_is_syncing": int(syncing not in (False, None)),
                    "api_txpool_pending": to_int(txp.get("pending")),
                    "api_txpool_queued": to_int(txp.get("queued")),
                    "label": args.label,
                }
                w.writerow(row); f.flush()
                print(f"{row['timestamp']} pairs={len(peers)} tcp={est} lag={row['p2p_sync_lag']} "
                      f"cpu_geth={cpu_g} api={row['api_lat_blocknumber_ms']}ms ok={row['api_ok_ratio']}")

                prev_ids, prev_t, prev_lo, prev_met = ids, now, lo, met
        except KeyboardInterrupt:
            print("\nArrêt demandé.")
    print(f"Terminé : {path}")


if __name__ == "__main__":
    main()
