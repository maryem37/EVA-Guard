#!/usr/bin/env python3
"""EVA-Guard - générateur de trafic légitime variable (transactions + lectures RPC)."""
import argparse, csv, os, random, sys, threading, time
from datetime import datetime
import requests

PORTS = {1: 8545, 2: 8546, 3: 8547, 4: 8548, 5: 8549}
PROFILES = {                     # événements par seconde
    "idle":   {"tx": 0.05, "read": 0.3},
    "low":    {"tx": 0.3,  "read": 1.5},
    "medium": {"tx": 1.0,  "read": 5.0},
    "high":   {"tx": 2.5,  "read": 12.0},
}
ADDR = open(os.path.expanduser("~/eva-data/addr.txt")).read().strip()

stop = threading.Event()
state = {"profile": "low", "mult": 1.0}
stats = {"tx_ok": 0, "tx_err": 0, "rd_ok": 0, "rd_err": 0}
lock = threading.Lock()


def rpc(port, method, params=None):
    try:
        r = requests.post(f"http://127.0.0.1:{port}", timeout=3,
                          json={"jsonrpc": "2.0", "method": method,
                                "params": params or [], "id": 1}).json()
        return ("error" not in r), r
    except Exception as e:
        return False, {"error": str(e)}


def rand_addr():
    return "0x" + "".join(random.choice("0123456789abcdef") for _ in range(40))


def send_tx():
    return rpc(PORTS[1], "eth_sendTransaction", [{
        "from": "0x" + ADDR, "to": rand_addr(),
        "value": hex(random.randint(1, 10**9)), "gas": "0x5208"}])


def rate(kind):
    return PROFILES[state["profile"]][kind] * state["mult"]


def tx_loop():
    while not stop.is_set():
        time.sleep(random.expovariate(max(rate("tx"), 0.01)))
        if stop.is_set():
            break
        ok, _ = send_tx()
        with lock:
            stats["tx_ok" if ok else "tx_err"] += 1


def read_loop():
    calls = [("eth_blockNumber", lambda: []),
             ("eth_getBalance", lambda: ["0x" + ADDR, "latest"]),
             ("eth_getBlockByNumber", lambda: ["latest", False]),
             ("eth_gasPrice", lambda: []),
             ("eth_getTransactionCount", lambda: ["0x" + ADDR, "latest"]),
             ("net_peerCount", lambda: []),
             ("eth_chainId", lambda: [])]
    while not stop.is_set():
        time.sleep(random.expovariate(max(rate("read"), 0.01)))
        if stop.is_set():
            break
        m, p = random.choice(calls)
        port = PORTS[random.choices([2, 1, 3, 4, 5], weights=[40, 15, 15, 15, 15])[0]]
        ok, _ = rpc(port, m, p())
        with lock:
            stats["rd_ok" if ok else "rd_err"] += 1


def build_plan(duration):
    """Segments de 2 à 5 min ; les 4 profils apparaissent au moins une fois."""
    base = list(PROFILES); random.shuffle(base)
    plan, total, prev = [], 0, None
    while total < duration:
        p = base.pop() if base else random.choice([x for x in PROFILES if x != prev])
        d = random.randint(120, 300)
        plan.append((p, d)); total += d; prev = p
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="mixed", choices=list(PROFILES) + ["mixed"])
    ap.add_argument("--duration", type=int, default=1800)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    # Test préalable : une transaction doit passer
    ok, r = send_tx()
    if not ok:
        print("ERREUR : transaction refusée :", r.get("error"))
        print("Vérifiez que node1 tourne avec --unlock (infra/start_network.sh).")
        sys.exit(1)
    print("Test transaction OK")

    os.makedirs("data/raw", exist_ok=True)
    tl_path = f"data/raw/traffic_{datetime.now():%Y%m%d_%H%M%S}.csv"
    tl = open(tl_path, "w", newline=""); tw = csv.writer(tl)
    tw.writerow(["timestamp", "event", "profile", "mult"])

    def log(event):
        tw.writerow([datetime.now().isoformat(timespec="seconds"), event,
                     state["profile"], round(state["mult"], 2)]); tl.flush()

    for t in (tx_loop, read_loop):
        threading.Thread(target=t, daemon=True).start()

    plan = ([(args.profile, args.duration)] if args.profile != "mixed"
            else build_plan(args.duration))
    print("Plan :", " | ".join(f"{p} {d}s" for p, d in plan))

    start = time.time(); last_stat = start
    try:
        for prof, dur in plan:
            state["profile"], state["mult"] = prof, 1.0
            log("segment")
            seg_end = min(time.time() + dur, start + args.duration)
            next_jitter, burst_end = time.time() + 20, 0
            while time.time() < seg_end and not stop.is_set():
                time.sleep(1); now = time.time()
                if burst_end and now >= burst_end:          # fin de rafale
                    state["mult"] = random.uniform(0.7, 1.3); burst_end = 0; log("fin_rafale")
                elif now >= next_jitter and not burst_end:  # variation de charge
                    next_jitter = now + 20
                    if random.random() < 0.10:
                        state["mult"] = 2.5; burst_end = now + 10; log("rafale")
                    else:
                        state["mult"] = random.uniform(0.7, 1.3)
                if now - last_stat >= 60:
                    last_stat = now
                    with lock:
                        print(f"{datetime.now():%H:%M:%S} profil={state['profile']} "
                              f"x{state['mult']:.1f} {stats}")
    except KeyboardInterrupt:
        print("\nArrêt demandé.")
    stop.set(); log("fin"); tl.close()
    print("Trafic terminé :", stats, "→", tl_path)


if __name__ == "__main__":
    main()
