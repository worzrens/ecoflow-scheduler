"""Read-only sharing of power history between installs.

Every install
  * writes ONLY its own files   <store>/ecoflow-history/<serial>/<machine id>/<chunk>.jsonl  and
  * merely READS the other installs' files into its local history (tagged with their id, never re-shared).
Both installs listen to the same unit, so their samples describe the same thing: where one has a gap the other
fills it, and where nobody recorded anything the gap stays empty ("no data"). Nothing is ever edited in two
places, so there is nothing to conflict.

The <store> is a pluggable transport:
  * FolderTransport  - a shared folder (OneDrive, Dropbox, Syncthing, NAS ...), day files, every 5 minutes.
  * GitHubTransport  - a PRIVATE GitHub repository through the REST Contents API (no git needed), hour files,
                       every 30 minutes. Refuses public repositories.

Command line:  python -m ecoflow_app.sync [--days 7] [--sync]   (coverage report of the merged history)
"""
from __future__ import annotations

import argparse
import base64
import calendar
import json
import os
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from .power import COVER_AFTER_SAMPLE, MAX_GAP
from .storage import KEEP_SECONDS, SRC_IDX, History

ROOT_NAME = "ecoflow-history"
FOLDER_EVERY = 300        # seconds between automatic syncs (shared folder)
GITHUB_EVERY = 1800       # ... GitHub: every sync is a commit, so keep it modest
SYNC_EVERY = FOLDER_EVERY
KEEP_DAYS = KEEP_SECONDS // 86400 + 1


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name) or "device"


def device_dir(root: str | Path, sn: str) -> Path:
    return Path(root) / ROOT_NAME / _safe(sn)


def own_dir(root: str | Path, sn: str, machine_id: str) -> Path:
    return device_dir(root, sn) / _safe(machine_id)


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def chunk_name(ts: float, period: str) -> str:
    return time.strftime("%Y-%m-%dT%H" if period == "hour" else "%Y-%m-%d", time.gmtime(ts))


def chunk_bounds(stem: str) -> tuple[int, int]:
    """[start, end) epoch seconds (UTC) of a chunk file name."""
    if len(stem) == 13:
        t0 = calendar.timegm(time.strptime(stem, "%Y-%m-%dT%H"))
        return t0, t0 + 3600
    t0 = calendar.timegm(time.strptime(stem[:10], "%Y-%m-%d"))
    return t0, t0 + 86400


# ================================================================== transports
class Transport:
    kind = ""
    chunk = "day"                 # "day" | "hour"
    interval = FOLDER_EVERY
    ident = ""                    # identifies the store in the local watermark table

    def check(self) -> None: ...
    def list_peers(self) -> list[str]: raise NotImplementedError
    def peer_label(self, peer: str) -> str: return peer
    def list_files(self, peer: str) -> dict[str, str]: raise NotImplementedError   # name -> change token
    def read(self, peer: str, name: str) -> bytes: raise NotImplementedError
    def own_files(self) -> list[str]: raise NotImplementedError
    def write(self, name: str, data: bytes) -> None: raise NotImplementedError     # create or replace, own folder only
    def delete(self, name: str) -> None: raise NotImplementedError


class FolderTransport(Transport):
    kind = "folder"
    chunk = "day"
    interval = FOLDER_EVERY

    def __init__(self, root: str | Path, sn: str, machine_id: str):
        self.base = device_dir(root, sn)
        self.own = self.base / _safe(machine_id)
        self.ident = f"{Path(root)}:{sn}"

    def list_peers(self):
        if not self.base.is_dir():
            return []
        return sorted(p.name for p in self.base.iterdir() if p.is_dir() and p.name != self.own.name)

    def peer_label(self, peer):
        try:
            return json.loads((self.base / peer / "peer.json").read_text("utf-8")).get("label", peer)
        except (OSError, ValueError):
            return peer

    def list_files(self, peer):
        out = {}
        for f in (self.base / peer).glob("*.jsonl"):
            try:
                st = f.stat()
                out[f.name] = f"{st.st_size}:{st.st_mtime_ns}"
            except OSError:
                continue
        return out

    def read(self, peer, name):
        return (self.base / peer / name).read_bytes()

    def own_files(self):
        return [f.name for f in self.own.glob("*.jsonl")] if self.own.is_dir() else []

    def write(self, name, data):
        self.own.mkdir(parents=True, exist_ok=True)
        tmp = self.own / f".{name}.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, self.own / name)      # readers never see a half-written file

    def delete(self, name):
        (self.own / name).unlink(missing_ok=True)


class GitHubTransport(Transport):
    """A private repository used as a small shared store through the REST Contents API (HTTPS + token, no git)."""
    kind = "github"
    chunk = "hour"
    interval = GITHUB_EVERY
    API = "https://api.github.com"

    def __init__(self, repo: str, token: str, sn: str, machine_id: str, session=None):
        repo = repo.strip().strip("/")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise ValueError("Repository must look like owner/name")
        self.repo, self.token = repo, token
        self._base = f"{ROOT_NAME}/{_safe(sn)}"
        self._own = _safe(machine_id)
        self.ident = f"gh:{repo}:{sn}"
        self.session = session or requests.Session()
        self._own_sha: dict[str, str] | None = None

    # -- plumbing
    def _req(self, method: str, path: str, raw: bool = False, body: dict | None = None):
        headers = {"Authorization": f"Bearer {self.token}", "X-GitHub-Api-Version": "2022-11-28",
                   "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
                   "User-Agent": "ecoflow-scheduler"}
        return self.session.request(method, f"{self.API}/repos/{self.repo}{path}", headers=headers, json=body, timeout=20)

    @staticmethod
    def _fail(r) -> None:
        try:
            msg = r.json().get("message", "")
        except ValueError:
            msg = ""
        if r.status_code == 401:
            msg = "token rejected - create a new fine-grained token"
        elif r.status_code == 403 and "rate limit" in msg.lower():
            msg = "rate limit reached, will retry later"
        raise OSError(f"GitHub {r.status_code}: {msg or 'request failed'}")

    def check(self) -> None:
        r = self._req("GET", "")
        if r.status_code == 404:
            raise OSError("GitHub: repository not found, or the token has no access to it")
        if r.status_code != 200:
            self._fail(r)
        info = r.json()
        if not info.get("private", False):
            raise OSError("GitHub: the repository is PUBLIC - power data would be visible to everyone. "
                          "Use a private repository.")
        perms = info.get("permissions")
        if perms is not None and not perms.get("push", False):
            raise OSError("GitHub: the token cannot write to this repository (needs Contents: Read and write)")

    def _list(self, path: str) -> list[dict]:
        r = self._req("GET", f"/contents/{path}")
        if r.status_code == 404:
            return []
        if r.status_code != 200:
            self._fail(r)
        data = r.json()
        return data if isinstance(data, list) else []

    # -- Transport API
    def list_peers(self):
        return sorted(e["name"] for e in self._list(self._base) if e.get("type") == "dir" and e["name"] != self._own)

    def peer_label(self, peer):
        try:
            return json.loads(self.read(peer, "peer.json")).get("label", peer)
        except (OSError, ValueError):
            return peer

    def list_files(self, peer):
        return {e["name"]: e["sha"] for e in self._list(f"{self._base}/{peer}")
                if e.get("type") == "file" and e["name"].endswith(".jsonl")}

    def read(self, peer, name):
        r = self._req("GET", f"/contents/{self._base}/{peer}/{name}", raw=True)
        if r.status_code != 200:
            self._fail(r)
        return r.content

    def own_files(self):
        self._own_sha = {e["name"]: e["sha"] for e in self._list(f"{self._base}/{self._own}") if e.get("type") == "file"}
        return [n for n in self._own_sha if n.endswith(".jsonl")]

    def write(self, name, data):
        if self._own_sha is None:
            self.own_files()
        for attempt in (1, 2):
            body = {"message": f"sync {self._own}: {name}", "content": base64.b64encode(data).decode()}
            sha = self._own_sha.get(name)
            if sha:
                body["sha"] = sha
            r = self._req("PUT", f"/contents/{self._base}/{self._own}/{name}", body=body)
            if r.status_code in (200, 201):
                self._own_sha[name] = r.json()["content"]["sha"]
                return
            if r.status_code in (409, 422) and attempt == 1:
                self.own_files()                  # our cached sha was stale: refresh and retry once
                continue
            self._fail(r)

    def delete(self, name):
        if self._own_sha is None:
            self.own_files()
        sha = self._own_sha.get(name)
        if not sha:
            return
        r = self._req("DELETE", f"/contents/{self._base}/{self._own}/{name}",
                      body={"message": f"sync {self._own}: remove {name}", "sha": sha})
        if r.status_code in (200, 404):
            self._own_sha.pop(name, None)
        else:
            self._fail(r)


def make_transport(s) -> Transport | None:
    """Transport for the configured sync mode (Settings), or None when sync is off / incomplete."""
    if not s.sn:
        return None
    mode = s.sync_mode or ("folder" if s.sync_dir else "")
    if mode == "folder" and s.sync_dir:
        return FolderTransport(s.sync_dir, s.sn, s.machine_id)
    if mode == "github" and s.github_repo:
        from .settings import get_github_token
        token = get_github_token()
        if token:
            try:
                return GitHubTransport(s.github_repo, token, s.sn, s.machine_id)
            except ValueError:
                return None
    return None


# ================================================================== export / import
def _encode(rows: list[tuple]) -> bytes:
    return ("\n".join(json.dumps(list(r[:9]), separators=(",", ":")) for r in rows) + "\n").encode("utf-8")


def export_new(history: History, tr: Transport, label: str | None = None) -> int:
    """Write our own samples (whole chunk files, replaced atomically). Returns the number of new samples shared."""
    label = label or socket.gethostname()
    meta_key = f"peerjson:{tr.ident}"
    if history.meta_get(meta_key) != label:
        tr.write("peer.json", json.dumps({"label": label}).encode("utf-8"))
        history.meta_set(meta_key, label)
    key = f"export:{tr.ident}"
    watermark = float(history.meta_get(key, "0") or 0)
    new = history.local_since(watermark)
    if not new:
        return 0
    for stem in sorted({chunk_name(r[0], tr.chunk) for r in new}):
        t0, t1 = chunk_bounds(stem)
        tr.write(f"{stem}.jsonl", _encode(history.local_between(t0, t1)))
    history.meta_set(key, str(new[-1][0]))
    cutoff = _day(time.time() - KEEP_DAYS * 86400)
    for name in [n for n in tr.own_files() if n[:10] < cutoff][:30]:    # drop our own files past the retention
        try:
            tr.delete(name)
        except OSError:
            break
    return len(new)


def import_peers(history: History, tr: Transport) -> dict[str, tuple[str, int]]:
    """Read the other installs' changed files into the local history. {peer id: (label, new rows)}."""
    cutoff = _day(time.time() - KEEP_DAYS * 86400)
    result: dict[str, tuple[str, int]] = {}
    for peer in tr.list_peers():
        added = 0
        for name, token in sorted(tr.list_files(peer).items()):
            if not name.endswith(".jsonl") or name[:10] < cutoff:
                continue
            key = f"import:{peer}:{name}"
            if history.meta_get(key) == token:      # unchanged since the last import
                continue
            rows = []
            for line in tr.read(peer, name).splitlines():
                try:                                # a half-written last line simply fails to parse and is read next time
                    arr = json.loads(line)
                    if isinstance(arr, list) and len(arr) >= 9:
                        rows.append(tuple(arr[:9]))
                except ValueError:
                    continue
            added += history.add_peer_rows(rows, peer)
            history.meta_set(key, token)
        result[peer] = (tr.peer_label(peer), added)
    return result


@dataclass
class SyncResult:
    at: float = 0.0
    exported: int = 0
    imported: int = 0
    peers: list[str] = field(default_factory=list)
    error: str = ""

    def text(self) -> str:
        when = datetime.fromtimestamp(self.at).strftime("%H:%M")
        if self.error:
            return f"Sync problem at {when}: {self.error}"
        peers = ", ".join(self.peers) if self.peers else "no other device found yet"
        return f"Last sync {when} · sent {self.exported} · received {self.imported} · {peers}"


def sync_once(history: History, store, sn: str | None = None, machine_id: str | None = None) -> SyncResult:
    """One round: check the store, share our new samples, read the others'. `store` is a Transport or a folder path."""
    tr = store if isinstance(store, Transport) else FolderTransport(store, sn, machine_id)
    res = SyncResult(at=time.time())
    try:
        tr.check()
        res.exported = export_new(history, tr)
        got = import_peers(history, tr)
        res.imported = sum(n for _, n in got.values())
        res.peers = [label for label, _ in got.values()]
    except (OSError, ValueError, KeyError) as e:     # requests' errors are OSErrors too
        res.error = str(e)
    return res


# ================================================================== analysis: who covered which time
def _intervals(times: list[float]) -> list[tuple[float, float]]:
    """Time spans one source actually recorded (a sample covers up to the next one, or briefly if recording stopped)."""
    out: list[tuple[float, float]] = []
    for i, t in enumerate(times):
        nxt = times[i + 1] if i + 1 < len(times) else None
        end = nxt if nxt is not None and nxt - t <= MAX_GAP else t + COVER_AFTER_SAMPLE
        if out and t <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((t, end))
    return out


def _union(*lists: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for a, b in sorted(x for lst in lists for x in lst):
        if merged and a <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _clip_len(iv: list[tuple[float, float]], t0: float, t1: float) -> float:
    return sum(max(0.0, min(b, t1) - max(a, t0)) for a, b in iv)


def coverage(history: History, days: int = 7, now: float | None = None) -> dict:
    """How much of the last `days` days is covered by this install, by the other devices, by both, or by nobody."""
    now = now or time.time()
    t0 = now - days * 86400
    rows = history.range(t0 - MAX_GAP)
    local_t = [r[0] for r in rows if r[SRC_IDX] is None]
    peer_t = [r[0] for r in rows if r[SRC_IDX] is not None]
    by_peer: dict[str, list[float]] = {}
    for r in rows:
        if r[SRC_IDX] is not None:
            by_peer.setdefault(r[SRC_IDX], []).append(r[0])
    local = _intervals(local_t)
    peers = _union(*[_intervals(ts) for ts in by_peer.values()]) if by_peer else []
    both_cov = _union(local, peers)
    total = now - t0
    loc, per, uni = _clip_len(local, t0, now), _clip_len(peers, t0, now), _clip_len(both_cov, t0, now)
    return {
        "days": days, "window_h": total / 3600, "local_h": loc / 3600, "peers_h": per / 3600,
        "filled_by_peers_h": (uni - loc) / 3600, "both_h": (loc + per - uni) / 3600,
        "empty_h": (total - uni) / 3600, "covered_pct": 100 * uni / total if total else 0.0,
        "local_pct": 100 * loc / total if total else 0.0, "peer_samples": len(peer_t), "local_samples": len(local_t),
    }


def format_coverage(c: dict) -> str:
    return (f"Last {c['days']} days: {c['covered_pct']:.0f}% covered "
            f"(this device {c['local_pct']:.0f}%, +{100 * c['filled_by_peers_h'] / c['window_h']:.0f}% filled from other devices, "
            f"{c['empty_h']:.1f} h empty)")


def main(argv: list[str] | None = None) -> int:
    from .paths import DB_PATH
    from .settings import load_settings
    ap = argparse.ArgumentParser(description="Coverage report for the merged power history")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--sync", action="store_true", help="run a sync with the configured store first")
    args = ap.parse_args(argv)
    history = History(DB_PATH)
    s = load_settings()
    if args.sync:
        tr = make_transport(s)
        print(sync_once(history, tr).text() if tr else "Sync is not configured (Settings > Sync between devices).")
    c = coverage(history, args.days)
    print(format_coverage(c))
    print(f"  window {c['window_h']:.1f} h | this device {c['local_h']:.1f} h ({c['local_samples']} samples) | "
          f"other devices {c['peers_h']:.1f} h ({c['peer_samples']} samples) | both {c['both_h']:.1f} h | "
          f"filled by others {c['filled_by_peers_h']:.1f} h | empty {c['empty_h']:.1f} h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
