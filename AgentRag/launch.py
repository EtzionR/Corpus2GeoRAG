"""What RUN_GEORAG.bat (in the repo root) runs: sets up the app's Python environment once, checks the
graph and the OpenRouter key, then starts the map app and opens it in the browser.

    python AgentRag/launch.py        # any Python 3.10+; it switches to AgentRag/venv by itself

The key is asked once and kept in AgentRag/.env, which git ignores, so it is never uploaded and never
printed. The app is our copy of the UI with the UI_TEAM_NOTES fixes (AgentRag/ui_mvp) until the UI
team's own ui/ has them; delete ui_mvp and this runs ui/ instead.
"""
import getpass
import os
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent
VENV = AGENT / "venv"
VENV_PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
ENV_FILE = AGENT / ".env"
KEY_NAME = "OPENROUTER_API_KEY"
GRAPH = ROOT / "Graph_n_Geocoding" / "knowledge_graph.json.gz"
APP_DIR = next(d for d in (AGENT / "ui_mvp", ROOT / "ui") if (d / "app.py").is_file())


def in_venv() -> bool:
    return Path(sys.prefix).resolve() == VENV.resolve()


def setup_venv() -> None:
    if not VENV_PYTHON.is_file():
        print("Setting up GeoRAG on this computer (once; a few minutes)...")
        venv.create(VENV, with_pip=True)


def install_packages() -> None:
    print("Checking packages...")
    # pandas 3 is blocked by Windows Smart App Control on some PCs (UI_TEAM_NOTES 1)
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                    "-r", str(APP_DIR / "requirements.txt"), "pandas<3"], check=True)


def saved_key() -> str:
    if not ENV_FILE.is_file():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        name, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        if name.strip() == KEY_NAME and value.startswith("sk-"):
            return value
    return ""


def ask_key() -> str:
    print("\nThe app needs an OpenRouter key (you got it from the team; it starts with sk-or-).")
    print("Paste it and press Enter. It stays hidden while you paste.")
    while True:
        key = getpass.getpass("Key: ").strip()
        if key.startswith("sk-or-") and len(key) > 20:
            return key
        print("That doesn't look like an OpenRouter key (sk-or-...). Try again, or close this window.")


def save_key(key: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines() if ENV_FILE.is_file() else []
    lines = [ln for ln in lines if ln.partition("=")[0].strip() != KEY_NAME] + [f"{KEY_NAME}={key}"]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Key saved in {ENV_FILE} (git ignores this file: it is never uploaded).")


def free_port(start: int = 8501) -> int:
    for port in range(start, start + 20):
        with socket.socket() as s:
            if s.connect_ex(("localhost", port)) != 0:
                return port
    return start


def wait_until_up(url: str, seconds: int = 90) -> bool:
    for _ in range(seconds):
        try:
            urllib.request.urlopen(f"{url}/_stcore/health", timeout=2)
            return True
        except OSError:
            time.sleep(1)
    return False


def main() -> int:
    if not in_venv():
        setup_venv()
        return subprocess.call([str(VENV_PYTHON), __file__])
    try:
        install_packages()
    except subprocess.CalledProcessError:
        print("\nInstalling the packages failed (see above). Check the internet connection and try again.")
        return 1
    if not GRAPH.is_file():
        print(f"\nThe knowledge graph is missing ({GRAPH}). Get the whole repository with git clone / git pull.")
        return 1
    key = saved_key()
    if not key:
        key = ask_key()
        save_key(key)
    port = free_port()
    url = f"http://localhost:{port}"
    env = {**os.environ, KEY_NAME: key, "AGENT_RAG_PATH": str(AGENT)}
    app = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port),
                            "--server.address", "localhost", "--browser.gatherUsageStats", "false"],
                           cwd=APP_DIR, env=env)
    print(f"\nStarting the app ({APP_DIR.relative_to(ROOT)})...")
    if wait_until_up(url):
        print(f"\nGeoRAG is running at {url}\nKeep this window open while you use it; close it to stop the app.")
        if not os.environ.get("GEORAG_NO_BROWSER"):
            webbrowser.open(url)
    try:
        return app.wait()
    except KeyboardInterrupt:
        app.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
