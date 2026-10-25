"""User-approved local runtime actions. Never execute pasted provider commands."""

import os
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from forge.policy import PolicyError


class DeviceSetup:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    @staticmethod
    def executable():
        found = shutil.which("ollama")
        if found:
            return found
        if os.name == "nt":
            path = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe"
            if path.is_file():
                return str(path)
        return None

    def status(self):
        return {
            "ollama_installed": bool(self.executable()),
            "can_install": os.name == "nt" and bool(shutil.which("winget")),
            "jobs": [{k: v for k, v in job.items() if k != "process"} for job in self.jobs.values()],
        }

    def start(self, action, consent, model=""):
        if not consent:
            raise PolicyError("Approve the displayed local setup action before changing this device.")
        runtime = self.executable()
        if action == "install_ollama":
            if os.name != "nt" or not shutil.which("winget"):
                raise PolicyError(
                    "Automatic installation currently requires Windows and WinGet. Install Ollama from its official site, then retry."
                )
            command = [
                shutil.which("winget"),
                "install",
                "--id",
                "Ollama.Ollama",
                "--exact",
                "--source",
                "winget",
                "--silent",
                "--accept-source-agreements",
                "--accept-package-agreements",
                "--disable-interactivity",
            ]
        elif action == "start_ollama":
            if not runtime:
                raise PolicyError("Install Ollama first.")
            command = [runtime, "serve"]
        elif action == "pull_model":
            if not runtime or not re.fullmatch(r"[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+)?", model):
                raise PolicyError("Use a valid Ollama model tag after installing the runtime.")
            if model.endswith("-cloud"):
                raise PolicyError("Cloud model downloads are not part of local runtime setup.")
            command = [runtime, "pull", model]
        else:
            raise PolicyError("Unsupported setup action. No command was executed.")
        with self.lock:
            if any(j["status"] == "running" for j in self.jobs.values()):
                raise PolicyError("Another local setup action is still running.")
            jid = uuid.uuid4().hex
            self.jobs[jid] = {
                "id": jid,
                "action": action,
                "model": model,
                "status": "running",
                "message": "Setup in progress",
            }

        def run():
            try:
                options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
                # No model keys or GitHub credentials enter installer/runtime environments.
                env = {
                    k: v
                    for k, v in os.environ.items()
                    if k.upper()
                    in {
                        "PATH",
                        "SYSTEMROOT",
                        "WINDIR",
                        "TEMP",
                        "TMP",
                        "USERPROFILE",
                        "LOCALAPPDATA",
                        "APPDATA",
                        "HOME",
                        "PROGRAMFILES",
                        "PROGRAMFILES(X86)",
                        "PROGRAMDATA",
                    }
                }
                if action == "start_ollama":
                    process = subprocess.Popen(
                        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, **options
                    )
                    self.jobs[jid].update(
                        status="started",
                        message="Local Ollama server launched. Retry connection to verify readiness.",
                        process=process,
                    )
                else:
                    result = subprocess.run(command, capture_output=True, timeout=1800, env=env, **options)
                    self.jobs[jid].update(
                        status="complete" if result.returncode == 0 else "failed",
                        message="Setup completed. Retry the model connection."
                        if result.returncode == 0
                        else "Setup did not complete. Check disk space, runtime requirements, or install from the official site.",
                    )
            except (OSError, subprocess.SubprocessError):
                self.jobs[jid].update(
                    status="failed", message="Setup failed or timed out. No provider example was executed."
                )

        threading.Thread(target=run, daemon=True).start()
        return {"job_id": jid, **self.status()}
