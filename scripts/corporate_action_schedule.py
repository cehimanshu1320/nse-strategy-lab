"""Install or remove the local macOS LaunchAgent for action discovery."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys


LABEL = "com.nse-strategy-lab.corporate-actions"


def _paths() -> tuple[Path, Path, Path]:
    project_root = Path(__file__).resolve().parents[1]
    launch_agent = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    data_dir = project_root / "data"
    return project_root, launch_agent, data_dir


def install() -> None:
    project_root, launch_agent, data_dir = _paths()
    script = project_root / "scripts" / "corporate_action_refresh.sh"
    if not script.is_file():
        raise SystemExit(f"Refresh script is missing: {script}")
    if launch_agent.exists():
        current = plistlib.loads(launch_agent.read_bytes())
        current_args = current.get("ProgramArguments", [])
        if str(script) not in current_args:
            raise SystemExit(
                f"Refusing to replace an unrelated LaunchAgent: {launch_agent}"
            )

    launch_agent.parent.mkdir(parents=True, exist_ok=True)
    (data_dir / "incoming").mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LABEL,
        "ProgramArguments": ["/bin/bash", str(script)],
        "WorkingDirectory": str(project_root),
        "RunAtLoad": False,
        "StartCalendarInterval": [
            {"Weekday": weekday, "Hour": 18, "Minute": 30}
            for weekday in range(1, 6)
        ],
        "StandardOutPath": str(data_dir / "logs" / "corporate-actions-schedule.log"),
        "StandardErrorPath": str(data_dir / "logs" / "corporate-actions-schedule-error.log"),
    }
    temporary = launch_agent.with_suffix(".plist.tmp")
    temporary.write_bytes(plistlib.dumps(payload, sort_keys=True))
    temporary.replace(launch_agent)

    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(launch_agent)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["launchctl", "bootstrap", domain, str(launch_agent)], check=True)
    print(f"Installed weekday 18:30 local schedule: {launch_agent}")
    print("Source: NSE public Corporate Actions CSV export")
    print("Results: raw archive and review candidates under the project data directory")
    print(f"Logs: {data_dir / 'logs'}")


def uninstall() -> None:
    _, launch_agent, _ = _paths()
    if not launch_agent.exists():
        print("Corporate-actions schedule is not installed.")
        return
    current = plistlib.loads(launch_agent.read_bytes())
    if current.get("Label") != LABEL:
        raise SystemExit(f"Refusing to remove an unrelated LaunchAgent: {launch_agent}")
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}", str(launch_agent)],
        check=False,
    )
    launch_agent.unlink()
    print("Removed the corporate-actions LaunchAgent.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall"))
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("This installer targets macOS launchd. Use cron or a hosted worker elsewhere.")
    if args.action == "install":
        install()
    else:
        uninstall()


if __name__ == "__main__":
    main()
