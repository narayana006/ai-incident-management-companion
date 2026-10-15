#!/usr/bin/env python3
"""K8S-01 automated trial runner (package §4.3-4.5).
Treatments: direct_write (A) | setpoint_override (B) | ttl_override (C)
Per-second sampling of HPA status, deployment replicas, events -> trials.csv + raw event logs.
Usage: ./runner.py --treatment A|B|C --run-id R01 [--settle 330]
"""
raise SystemExit(
    "K8S-01 legacy runner is a preserved evidence artifact and must not be executed. "
    "It is pinned by hash as part of the Chapter 6 record. See labs/controller_conflict/LIVE-PROTOCOL.md."
)

import argparse, csv, json, subprocess, time, os, sys, hashlib
from datetime import datetime, timezone

NS="k8s01"; DEP="cpu-svc"; HPA="cpu-svc"
def k(*args, capture=True):
    r=subprocess.run(["kubectl","-n",NS,*args], capture_output=True, text=True)
    return r.stdout.strip() if capture else r.returncode

def jget(kind,name):
    out=k("get",kind,name,"-o","json")
    return json.loads(out) if out else {}

def snapshot():
    hpa=jget("hpa",HPA); dep=jget("deployment",DEP)
    st=hpa.get("status",{})
    cur=st.get("currentMetrics") or []
    util=None
    for m in cur:
        if m.get("type")=="Resource": util=m["resource"]["current"].get("averageUtilization")
    return {
        "t": time.monotonic(), "utc": datetime.now(timezone.utc).isoformat(),
        "desired": st.get("desiredReplicas"), "current": st.get("currentReplicas"),
        "dep_spec": dep.get("spec",{}).get("replicas"),
        "dep_ready": dep.get("status",{}).get("readyReplicas"),
        "util": util, "hpa_max": hpa.get("spec",{}).get("maxReplicas"),
    }

def wait_stable(target_max, seconds=60):
    stable_since=None
    while True:
        s=snapshot()
        ok = s["dep_spec"] is not None and s["dep_spec"]<=target_max and (s["desired"] or 0)<=target_max
        if ok:
            stable_since = stable_since or s["t"]
            if s["t"]-stable_since>=seconds: return
        else:
            stable_since=None
        time.sleep(2)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--treatment", required=True, choices=["A","B","C"])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--ttl", type=int, default=120)
    ap.add_argument("--sample-hz", type=float, default=1.0)
    ap.add_argument("--observe", type=int, default=420, help="post-action observation seconds")
    a=ap.parse_args()
    outdir=os.path.join(os.path.dirname(__file__),"events",a.run_id); os.makedirs(outdir,exist_ok=True)
    samples=[]; treatment={"A":"direct_write","B":"setpoint_override","C":"ttl_override"}[a.treatment]
    cluster=subprocess.run(["kubectl","version","-o","json"],capture_output=True,text=True).stdout

    pre=snapshot()
    t_action=time.monotonic()
    if a.treatment=="A":
        k("scale","deployment",DEP,"--replicas","24")
        requested=24
    elif a.treatment=="B":
        k("patch","hpa",HPA,"--type","merge","-p",'{"spec":{"maxReplicas":30}}')
        requested=30
    else:
        k("patch","hpa",HPA,"--type","merge","-p",'{"spec":{"maxReplicas":30}}')
        requested=30
    t_first_react=None; t_settle=None; last=None; osc=0
    end=t_action+a.observe
    while time.monotonic()<end:
        s=snapshot(); s["dt"]=round(s["t"]-t_action,2); samples.append(s)
        if a.treatment=="A" and t_first_react is None and s["dep_spec"] is not None and s["dep_spec"]<24 and s["dt"]>0:
            t_first_react=s["dt"]   # HPA clamped the direct write back
        if a.treatment in "BC" and t_settle is None and s["dep_ready"] and s["dep_ready"]>=20:
            t_settle=s["dt"]        # converged near recommendation (~23)
        if last is not None and s["dep_spec"] is not None and s["dep_spec"]!=last: osc+=1
        last=s["dep_spec"] if s["dep_spec"] is not None else last
        # TTL restore for treatment C
        if a.treatment=="C" and s["dt"]>=a.ttl and jget("hpa",HPA).get("spec",{}).get("maxReplicas")==30:
            k("patch","hpa",HPA,"--type","merge","-p",'{"spec":{"maxReplicas":15}}')
        time.sleep(max(0.0,1.0/a.sample_hz))
    ttl_cleanup = "n/a"
    if a.treatment=="C":
        ttl_cleanup = "automatic" if jget("hpa",HPA).get("spec",{}).get("maxReplicas")==15 else "failed"
    # restore baseline
    k("patch","hpa",HPA,"--type","merge","-p",'{"spec":{"maxReplicas":15}}')
    events=k("get","events","--sort-by",".lastTimestamp")
    open(os.path.join(outdir,"events.txt"),"w").write(events)
    open(os.path.join(outdir,"samples.json"),"w").write(json.dumps(samples))
    open(os.path.join(outdir,"cluster.json"),"w").write(cluster)
    row={"run_id":a.run_id,"treatment":treatment,
         "requested_value":requested,"replicas_before":pre["dep_spec"],
         "observed_utilization":pre["util"],"hpa_max_before":pre["hpa_max"],
         "time_to_first_reconcile_s":t_first_react,"time_to_revert_or_converge_s":t_first_react if a.treatment=="A" else t_settle,
         "ttl_seconds":a.ttl if a.treatment=="C" else "", "ttl_cleanup_result":ttl_cleanup,
         "oscillation_count":osc,"utc":datetime.now(timezone.utc).isoformat()}
    csvp=os.path.join(os.path.dirname(__file__),"trials.csv")
    exists=os.path.exists(csvp)
    with open(csvp,"a",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(row.keys()))
        if not exists: w.writeheader()
        w.writerow(row)
    print("TRIAL DONE:",json.dumps(row,indent=1))
    wait_stable(15, seconds=90)

if __name__=="__main__": main()
