import time
import random
import threading
from datetime import datetime, timezone

QUESTS_BASE = "https://discord.com/api/v9"


class QuestSystem:
    def __init__(self, api_client):
        self.api = api_client
        self.quests = {}          # quest_id (str) -> raw quest dict from API
        self.excluded = set()     # quest_ids to skip
        self.auto_complete = False
        self._task_thread = None
        self.last_fetch = 0
        self.refresh_interval = 30 * 60  # 30 minutes

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self):
        return self.api.header_spoofer.get_protected_headers(self.api.token)

    def _expired(self, iso) -> bool:
        if not iso:
            return False
        try:
            return datetime.now(timezone.utc) > datetime.fromisoformat(
                str(iso).replace("Z", "+00:00")
            )
        except Exception:
            return False

    def _tasks_map(self, q: dict) -> dict:
        config = q.get("config", {}) or {}
        for key in ("task_config_v2", "task_config"):
            tc = config.get(key, {})
            if isinstance(tc, dict):
                tasks = tc.get("tasks", {})
                if tasks:
                    return tasks
        return {}

    def _task_type(self, q: dict) -> str:
        names = [str(k).lower() for k in self._tasks_map(q).keys()]
        if any("watch" in n for n in names):
            return "watch"
        if any("play" in n for n in names):
            return "play"
        if any("stream" in n for n in names):
            return "stream"
        return "unknown"

    def _quest_name(self, q: dict) -> str:
        config = q.get("config", {}) or {}
        msgs = config.get("messages", {}) or {}
        app = (config.get("application", {}) or {}).get("name", "Unknown")
        if self._task_type(q) == "watch":
            vm = config.get("video_metadata", {}) or {}
            title = (vm.get("messages", {}) or {}).get("video_title")
            if title:
                return title
        return msgs.get("quest_name") or msgs.get("game_title") or f"Quest by {app}"

    def _get_progress(self, q: dict):
        """Returns (event_name, done, total)."""
        tasks = self._tasks_map(q)
        progress = (q.get("user_status") or {}).get("progress") or {}
        done = 0
        event_name = None

        if isinstance(progress, dict):
            for _, val in progress.items():
                if not isinstance(val, dict):
                    continue
                v = int(float(val.get("value", 0) or 0))
                if v >= done:
                    done = v
                    event_name = val.get("event_name")

        total = 100
        if event_name:
            for _, task in tasks.items():
                if isinstance(task, dict) and task.get("event_name") == event_name:
                    total = int(float(task.get("target", 100) or 100))
                    break
        elif tasks:
            smallest = None
            for _, task in tasks.items():
                if isinstance(task, dict):
                    target = int(float(task.get("target", 100) or 100))
                    if smallest is None or target < smallest:
                        smallest = target
                        event_name = task.get("event_name") or event_name
            total = smallest if smallest is not None else 100

        return str(event_name or "Unknown"), max(0, done), max(1, total)

    def _is_enrollable(self, q: dict) -> bool:
        config = q.get("config", {}) or {}
        return not q.get("user_status") and not self._expired(config.get("expires_at"))

    def _is_completeable(self, q: dict) -> bool:
        config = q.get("config", {}) or {}
        status = q.get("user_status") or {}
        return bool(
            status
            and status.get("enrolled_at")
            and not status.get("completed_at")
            and not self._expired(config.get("expires_at"))
        )

    def _is_claimable(self, q: dict) -> bool:
        config = q.get("config", {}) or {}
        rewards_cfg = config.get("rewards_config", {}) or {}
        status = q.get("user_status") or {}
        return bool(
            status
            and status.get("completed_at")
            and not status.get("claimed_at")
            and not self._expired(config.get("expires_at"))
            and rewards_cfg.get("rewards_expire_at")
            and not self._expired(rewards_cfg.get("rewards_expire_at"))
        )

    def _is_worthy(self, q: dict) -> bool:
        config = q.get("config", {}) or {}
        if self._expired(config.get("expires_at")):
            return False
        rewards = (config.get("rewards_config", {}) or {}).get("rewards", []) or []
        return any(isinstance(r, dict) and r.get("type") in (3, 4) for r in rewards)

    def _reward_names(self, q: dict) -> list:
        rewards = ((q.get("config", {}) or {}).get("rewards_config", {}) or {}).get("rewards", []) or []
        names = []
        for r in rewards:
            if not isinstance(r, dict):
                continue
            label = ((r.get("messages", {}) or {}).get("name_with_article") or "").strip()
            if label:
                names.append(label.title())
        return names

    # ------------------------------------------------------------------
    # API calls
    # ------------------------------------------------------------------

    def fetch_quests(self):
        """Fetch and cache quests. Returns (success, message)."""
        try:
            resp = self.api.session.get(
                f"{QUESTS_BASE}/quests/@me",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}"

            data = resp.json()
            if isinstance(data, dict) and data.get("quest_enrollment_blocked_until"):
                return False, f"Blocked until {data['quest_enrollment_blocked_until']}"

            raw = []
            if isinstance(data, dict):
                raw = data.get("quests", []) or []
                for eq in data.get("excluded_quests", []) or []:
                    eid = eq.get("id")
                    if eid:
                        self.excluded.add(str(eid))
            elif isinstance(data, list):
                raw = data

            self.quests = {}
            for qd in raw:
                if not isinstance(qd, dict):
                    continue
                qid = str(qd.get("id", ""))
                if not qid or qid in self.excluded:
                    continue
                self.quests[qid] = qd

            self.last_fetch = time.time()
            return True, f"Fetched {len(self.quests)} quests"
        except Exception as e:
            return False, str(e)

    def enroll(self, q: dict):
        """Enroll in a single quest. Returns updated user_status dict or None."""
        if not self._is_enrollable(q):
            return None
        qid = q.get("id")
        try:
            resp = self.api.session.post(
                f"{QUESTS_BASE}/quests/{qid}/enroll",
                headers=self._headers(),
                json={"is_targeted": False, "location": 11, "metadata_raw": None},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    def _send_progress(self, q: dict):
        """Send one progress tick. Returns (success, completed, done, total)."""
        qid = str(q.get("id", ""))
        qtype = self._task_type(q)
        _, done, total = self._get_progress(q)
        headers = self._headers()

        try:
            if qtype == "watch":
                enrolled_raw = (q.get("user_status") or {}).get("enrolled_at")
                try:
                    enrolled_ts = datetime.fromisoformat(
                        str(enrolled_raw).replace("Z", "+00:00")
                    ).timestamp()
                except Exception:
                    enrolled_ts = datetime.now(timezone.utc).timestamp()

                max_allowed = int(datetime.now(timezone.utc).timestamp() - enrolled_ts) + 10
                speed = 7
                if max_allowed - done < speed:
                    return True, False, done, total

                new_val = min(done + speed + random.random(), max_allowed)
                resp = self.api.session.post(
                    f"{QUESTS_BASE}/quests/{qid}/video-progress",
                    headers=headers,
                    json={"timestamp": new_val},
                    timeout=10,
                )
            elif qtype == "play":
                resp = self.api.session.post(
                    f"{QUESTS_BASE}/quests/{qid}/heartbeat",
                    headers=headers,
                    json={"application_id": qid, "terminal": False},
                    timeout=10,
                )
            else:
                return False, False, done, total

            if resp.status_code not in (200, 204):
                if resp.status_code in (401, 404):
                    self.excluded.add(qid)
                return False, False, done, total

            if resp.status_code == 204:
                return True, False, done, total

            rdata = resp.json()

            # Completed?
            if rdata.get("completed_at"):
                us = q.get("user_status") or {}
                us["completed_at"] = rdata["completed_at"]
                q["user_status"] = us
                return True, True, total, total

            # Parse updated progress
            prog = rdata.get("progress") or {}
            for _, pv in prog.items():
                if isinstance(pv, dict):
                    try:
                        v = int(float(pv.get("value", done)))
                        if v > done:
                            done = v
                    except Exception:
                        pass
            sps = rdata.get("streamProgressSeconds")
            if sps is not None:
                try:
                    done = max(done, int(float(sps)))
                except Exception:
                    pass

            return True, False, done, total
        except Exception:
            return False, False, done, total

    # ------------------------------------------------------------------
    # Background runner
    # ------------------------------------------------------------------

    def _run_auto_complete(self):
        # Auto-enroll first
        for q in list(self.quests.values()):
            if not self.auto_complete:
                return
            if self._is_enrollable(q):
                status = self.enroll(q)
                if status:
                    q["user_status"] = status
                time.sleep(0.8)

        while self.auto_complete:
            try:
                if time.time() - self.last_fetch > self.refresh_interval:
                    self.fetch_quests()

                to_process = [
                    q for q in self.quests.values()
                    if self._is_completeable(q) and str(q.get("id", "")) not in self.excluded
                ]
                to_process.sort(key=lambda q: 0 if self._is_worthy(q) else 1)

                for q in to_process:
                    if not self.auto_complete:
                        break
                    self._send_progress(q)

                time.sleep(random.randint(45, 60))
            except Exception:
                time.sleep(30)

    def start(self):
        if self.auto_complete:
            return False, "Already running"
        self.auto_complete = True
        self._task_thread = threading.Thread(target=self._run_auto_complete, daemon=True)
        self._task_thread.start()
        return True, "Started"

    def stop(self):
        if not self.auto_complete:
            return False, "Not running"
        self.auto_complete = False
        self._task_thread = None
        return True, "Stopped"

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self):
        enrollable, completeable, claimable, completed, expired = [], [], [], [], []
        for q in self.quests.values():
            config = q.get("config", {}) or {}
            if self._expired(config.get("expires_at")):
                expired.append(q)
            elif self._is_claimable(q):
                claimable.append(q)
            elif self._is_completeable(q):
                completeable.append(q)
            elif self._is_enrollable(q):
                enrollable.append(q)
            else:
                completed.append(q)
        return {
            "running": self.auto_complete,
            "total": len(self.quests),
            "enrollable": enrollable,
            "completeable": completeable,
            "claimable": claimable,
            "completed": completed,
            "expired": expired,
            "last_fetch": self.last_fetch,
        }
