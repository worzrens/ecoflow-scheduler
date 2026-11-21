"""History sync through a (fake) GitHub Contents API: private repo only, own files only, no token on disk."""
import base64
import hashlib
import json
import re
import time

import pytest

from ecoflow_app import settings as settings_mod
from ecoflow_app import sync
from ecoflow_app.api import Telemetry
from ecoflow_app.storage import SRC_IDX, History

SN = "DCEBTEST0001"
REPO = "someone/ecoflow-data"


class Resp:
    def __init__(self, status, payload=None, raw=None):
        self.status_code, self._payload = status, payload
        self.content = raw if raw is not None else json.dumps(payload).encode()

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeGitHub:
    """Just enough of the REST API: repo info, contents listing/raw read, PUT with sha check, DELETE."""

    def __init__(self, private=True, push=True):
        self.files: dict[str, bytes] = {}
        self.private, self.push = private, push
        self.calls: list[tuple[str, str]] = []

    @staticmethod
    def _sha(data: bytes) -> str:
        return hashlib.sha1(data).hexdigest()

    def request(self, method, url, headers=None, json=None, timeout=None):   # noqa: A002 - mirrors requests
        assert headers["Authorization"].startswith("Bearer ")
        m = re.match(r"https://api\.github\.com/repos/([^/]+/[^/]+)(.*)$", url)
        repo, rest = m.group(1), m.group(2)
        self.calls.append((method, rest))
        if repo != REPO:
            return Resp(404, {"message": "Not Found"})
        if rest == "":
            return Resp(200, {"private": self.private, "permissions": {"push": self.push}})
        path = rest.removeprefix("/contents/")
        if method == "GET":
            if path in self.files:
                raw = "raw" in headers["Accept"]
                data = self.files[path]
                return Resp(200, None if raw else {"sha": self._sha(data)}, raw=data if raw else None)
            kids: dict[str, dict] = {}
            for p, data in self.files.items():
                if p.startswith(path + "/"):
                    name, *tail = p[len(path) + 1:].split("/")
                    kids[name] = {"name": name, "type": "dir" if tail else "file", "sha": self._sha(data), "size": len(data)}
            return Resp(200, list(kids.values())) if kids else Resp(404, {"message": "Not Found"})
        if method == "PUT":
            cur = self.files.get(path)
            if cur is not None and json.get("sha") != self._sha(cur):
                return Resp(409, {"message": f"{path} does not match sha"})
            if cur is None and json.get("sha"):
                return Resp(422, {"message": "sha was supplied but the file does not exist"})
            data = base64.b64decode(json["content"])
            self.files[path] = data
            return Resp(200 if cur is not None else 201, {"content": {"sha": self._sha(data)}})
        if method == "DELETE":
            cur = self.files.get(path)
            if cur is None:
                return Resp(404, {"message": "Not Found"})
            if json["sha"] != self._sha(cur):
                return Resp(409, {"message": "sha mismatch"})
            del self.files[path]
            return Resp(200, {})
        return Resp(405, {"message": "method not allowed"})


def tel(soc=80.0, grid=True):
    return Telemetry(0, soc, 250, 250, 250, 250, 300, 28, 900, 0, grid=grid)


def fill(h: History, start: float, end: float, step: int = 40, **kw):
    t = start
    while t <= end:
        h.add(tel(**kw), ts=t)
        h._last_ts = 0
        t += step


def transport(gh: FakeGitHub, machine: str, repo: str = REPO) -> sync.GitHubTransport:
    return sync.GitHubTransport(repo, "ghp_fake", SN, machine, session=gh)


def test_two_installs_fill_each_others_gaps_through_github(tmp_path):
    now = time.time()
    gh = FakeGitHub()
    a, b = History(tmp_path / "a.db"), History(tmp_path / "b.db")
    fill(a, now - 6 * 3600, now - 3 * 3600)
    fill(a, now - 3600, now)
    fill(b, now - 4 * 3600 + 7, now - 1.5 * 3600, soc=70.0)
    ta, tb = transport(gh, "A"), transport(gh, "B")
    assert sync.sync_once(a, ta).exported > 0 and sync.sync_once(b, tb).exported > 0
    res = sync.sync_once(a, ta)
    assert res.error == "" and res.imported > 0 and res.peers
    assert sync.coverage(a, 1, now)["filled_by_peers_h"] > 1.3
    names = sorted(p.rsplit("/", 1)[1] for p in gh.files if p.endswith(".jsonl"))
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d\.jsonl", n) for n in names)        # hour chunks
    assert {p.split("/")[2] for p in gh.files} == {"A", "B"}                          # each writes only its own folder
    assert {r[SRC_IDX] for r in a.range(0)} == {None, "B"}


def test_second_sync_changes_nothing_and_rewrites_only_the_current_hour(tmp_path):
    now = time.time()
    gh = FakeGitHub()
    a = History(tmp_path / "a.db")
    fill(a, now - 3 * 3600, now - 2 * 3600)
    ta = transport(gh, "A")
    sync.sync_once(a, ta)
    puts_first = sum(1 for m, _ in gh.calls if m == "PUT")
    gh.calls.clear()
    again = sync.sync_once(a, ta)
    assert again.exported == 0 and not [c for c in gh.calls if c[0] == "PUT"]          # nothing new -> no commit
    fill(a, now - 2 * 3600 + 60, now - 2 * 3600 + 600)                                # a few new samples in one hour
    gh.calls.clear()
    assert sync.sync_once(a, ta).exported > 0
    puts = [c for c in gh.calls if c[0] == "PUT"]
    assert 1 <= len(puts) <= 2 and puts_first >= 2                                     # only the touched hour file(s)
    last = max(p for p in gh.files if p.endswith(".jsonl"))
    assert len(gh.files[last].decode().splitlines()) == len(a.local_between(*sync.chunk_bounds(last.rsplit("/", 1)[1][:-6])))


def test_public_repo_and_read_only_token_are_refused_and_nothing_is_written(tmp_path):
    a = History(tmp_path / "a.db")
    fill(a, time.time() - 600, time.time())
    pub = FakeGitHub(private=False)
    res = sync.sync_once(a, transport(pub, "A"))
    assert "PUBLIC" in res.error and not pub.files
    ro = FakeGitHub(push=False)
    assert "cannot write" in sync.sync_once(a, transport(ro, "A")).error and not ro.files
    assert "not found" in sync.sync_once(a, transport(FakeGitHub(), "A", repo="other/repo")).error


def test_stale_sha_is_refreshed_and_retried(tmp_path):
    gh = FakeGitHub()
    t = transport(gh, "A")
    t.write("2026-11-21T10.jsonl", b"[1]\n")
    t._own_sha["2026-11-21T10.jsonl"] = "stale"          # e.g. the file was replaced from another session
    t.write("2026-11-21T10.jsonl", b"[1]\n[2]\n")
    assert gh.files[f"ecoflow-history/{SN}/A/2026-11-21T10.jsonl"] == b"[1]\n[2]\n"


def test_old_own_files_are_removed_on_github_too(tmp_path):
    gh = FakeGitHub()
    t = transport(gh, "A")
    old = time.strftime("%Y-%m-%dT00.jsonl", time.gmtime(time.time() - 20 * 86400))
    t.write(old, b"[1]\n")
    a = History(tmp_path / "a.db")
    fill(a, time.time() - 600, time.time())
    sync.sync_once(a, t)
    assert not any(p.endswith(old) for p in gh.files) and any(p.endswith("peer.json") for p in gh.files)


def test_bad_repo_name_is_rejected():
    with pytest.raises(ValueError):
        sync.GitHubTransport("not-a-repo", "t", SN, "A", session=FakeGitHub())


def test_token_goes_to_the_credential_store_never_to_settings_json(tmp_path, monkeypatch):
    store = {}

    class FakeKeyring:
        @staticmethod
        def set_password(service, user, pw): store[(service, user)] = pw
        @staticmethod
        def get_password(service, user): return store.get((service, user))
        @staticmethod
        def delete_password(service, user): store.pop((service, user), None)

    monkeypatch.setattr(settings_mod, "keyring", FakeKeyring)
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "settings.json")
    settings_mod.set_github_token("ghp_SECRET123")
    s = settings_mod.Settings(email="a@b.c", sn=SN, password="pw", sync_mode="github", github_repo=REPO)
    settings_mod.save_settings(s)
    text = (tmp_path / "settings.json").read_text("utf-8")
    assert "ghp_SECRET123" not in text and "pw" not in json.loads(text).values() and REPO in text
    assert settings_mod.get_github_token() == "ghp_SECRET123"
    assert sync.make_transport(s).repo == REPO
    settings_mod.set_github_token("")
    assert settings_mod.get_github_token() == "" and sync.make_transport(s) is None
