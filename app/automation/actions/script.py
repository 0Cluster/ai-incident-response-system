import subprocess

from sqlalchemy.orm import Session

from app.automation.base import AutomationAction
from app.models.incident import Incident
from app.services.automation_run import AutomationRunService


class ScriptAction(AutomationAction):
    def __init__(
        self,
        action_name: str,
        script_path: str,
    ) -> None:
        self.action_name = action_name
        self.script_path = script_path

    def execute(
        self,
        incident: Incident,
        db: Session,
    ) -> None:

        print("=" * 50)
        print("[SCRIPT ACTION]")
        print(f"Action: {self.action_name}")
        print(f"Incident: {incident.id}")
        print(f"Running: {self.script_path}")
        print("=" * 50)

        try:
            result = subprocess.run(
                [self.script_path],
                capture_output=True,
                text=True,
                check=True,
            )

            print("Exit Code:", result.returncode)

            if result.stdout:
                print("\n----- STDOUT -----")
                print(result.stdout)

            if result.stderr:
                print("\n----- STDERR -----")
                print(result.stderr)

            AutomationRunService(db).log(
                incident_id=incident.id,
                action_name=self.action_name,
                status="SUCCESS",
                message="Script executed successfully.",
            )

        except subprocess.CalledProcessError as e:

            print("\nScript execution failed.")

            if e.stdout:
                print(e.stdout)

            if e.stderr:
                print(e.stderr)

            AutomationRunService(db).log(
                incident_id=incident.id,
                action_name=self.action_name,
                status="FAILED",
                message=f"Exit code {e.returncode}",
            )

        except FileNotFoundError:

            print(f"Script not found: {self.script_path}")

            AutomationRunService(db).log(
                incident_id=incident.id,
                action_name=self.action_name,
                status="FAILED",
                message="Script file not found.",
            )

        except Exception as e:

            print(e)

            AutomationRunService(db).log(
                incident_id=incident.id,
                action_name=self.action_name,
                status="FAILED",
                message=str(e),
            )

        print("=" * 50)
