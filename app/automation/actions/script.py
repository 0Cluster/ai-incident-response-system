import subprocess

from sqlalchemy.orm import Session

from app.automation.base import AutomationAction
from app.models.incident import Incident
from app.services.automation_run import AutomationRunService


class ScriptAction(AutomationAction):
    _FORBIDDEN_CHARS = (";", "|", "&", "$", "`", "\n", "\r")

    def __init__(
        self,
        action_name: str,
        script_path: str,
        timeout: int = 60,
    ) -> None:
        if not script_path or not script_path.strip():
            raise ValueError("script_path must be a non-empty string")
        if any(c in script_path for c in self._FORBIDDEN_CHARS):
            raise ValueError("script_path contains forbidden shell characters")
        if timeout is not None and (not isinstance(timeout, int) or timeout < 1 or timeout > 600):
            raise ValueError("timeout must be an int between 1 and 600")
        self.action_name = action_name
        self.script_path = script_path
        self.timeout = timeout

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
                timeout=self.timeout,
            )

            print("Exit Code:", result.returncode)

            if result.stdout:
                print("\n----- STDOUT -----")
                print(result.stdout)

            if result.stderr:
                print("\n----- STDERR -----")
                print(result.stderr)

            AutomationRunService(db).log(
                tenant_id=incident.tenant_id,
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
                tenant_id=incident.tenant_id,
                incident_id=incident.id,
                action_name=self.action_name,
                status="FAILED",
                message=f"Exit code {e.returncode}",
            )
            raise

        except FileNotFoundError:

            print(f"Script not found: {self.script_path}")

            AutomationRunService(db).log(
                tenant_id=incident.tenant_id,
                incident_id=incident.id,
                action_name=self.action_name,
                status="FAILED",
                message="Script file not found.",
            )
            raise

        except subprocess.TimeoutExpired:

            print(f"Script timed out: {self.script_path}")

            AutomationRunService(db).log(
                tenant_id=incident.tenant_id,
                incident_id=incident.id,
                action_name=self.action_name,
                status="FAILED",
                message="Script timed out after 60s.",
            )
            raise

        except Exception as e:

            print(e)

            AutomationRunService(db).log(
                tenant_id=incident.tenant_id,
                incident_id=incident.id,
                action_name=self.action_name,
                status="FAILED",
                message=str(e),
            )
            raise

        print("=" * 50)
