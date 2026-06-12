from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from fastapi.testclient import TestClient

from backend.main import app


@dataclass
class ApiResult:
    name: str
    method: str
    path: str
    status_code: int
    seconds: float
    ok: bool
    detail: str = ""


class ApiBench:
    def __init__(self, threshold: float) -> None:
        self.client = TestClient(app)
        self.threshold = threshold
        self.results: list[ApiResult] = []
        self.token = ""

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def call(self, name: str, method: str, path: str, *, expected: set[int] | None = None, **kwargs):
        expected = expected or {200}
        started = time.perf_counter()
        response = self.client.request(method, path, headers={**self.headers, **kwargs.pop("headers", {})}, **kwargs)
        seconds = time.perf_counter() - started
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = str(body.get("detail") or body.get("message") or "")
        except ValueError:
            detail = response.text[:160]
        self.results.append(
            ApiResult(
                name=name,
                method=method,
                path=path,
                status_code=response.status_code,
                seconds=seconds,
                ok=response.status_code in expected,
                detail=detail,
            )
        )
        return response

    def run(self) -> None:
        suffix = int(time.time() * 1000)
        email = f"perf_{suffix}@example.com"
        password = "Password123!"

        self.call("health", "GET", "/health")
        register = self.call("auth.register", "POST", "/auth/register", json={"email": email, "password": password})
        if register.status_code == 200:
            self.token = register.json()["data"]["access_token"]
        login = self.call("auth.login", "POST", "/auth/login", json={"email": email, "password": password})
        if login.status_code == 200:
            self.token = login.json()["data"]["access_token"]

        self.call("auth.me", "GET", "/auth/me")
        self.call("auth.logout", "POST", "/auth/logout")
        self.call("users.stats", "GET", "/users/me/stats")
        self.call("users.profile.patch", "PATCH", "/users/me/profile", json={"displayName": "Perf User"})

        self.call("dashboard", "GET", "/dashboard")

        missions = self.call("missions.all", "GET", "/missions")
        daily = self.call("missions.daily", "GET", "/missions?type=daily")
        self.call("missions.weekly", "GET", "/missions?type=weekly")
        self.call("missions.achievement", "GET", "/missions?type=achievement")
        try:
            daily_items = daily.json()["data"]
            mission_id = daily_items[0]["id"] if daily_items else missions.json()["data"][0]["id"]
            self.call("missions.complete", "POST", f"/missions/{mission_id}/complete")
            self.call("missions.claim", "POST", f"/missions/{mission_id}/claim", expected={200, 400, 409})
        except Exception as exc:
            self.results.append(ApiResult("missions.write.setup", "N/A", "N/A", 0, 0.0, False, str(exc)))

        self.call("quizzes.list", "GET", "/quizzes")
        generated = self.call("quizzes.generate", "GET", "/quizzes/generate?count=10&difficulty=beginner&questionTypes=meaning,reverse,pronunciation,type,fill_blank")
        try:
            quiz = generated.json()["data"]
            answers = [{"questionId": question["id"], "selectedOptionId": question["options"][0]["id"]} for question in quiz["questions"]]
            attempt = self.call("quizzes.generated.submit", "POST", "/quizzes/generated/attempts", json={"quizId": quiz["quizId"], "answers": answers})
            if attempt.status_code == 200:
                attempt_id = attempt.json()["data"]["attemptId"]
                self.call("quizzes.attempt.get", "GET", f"/quizzes/attempts/{attempt_id}")
        except Exception as exc:
            self.results.append(ApiResult("quizzes.generated.setup", "N/A", "N/A", 0, 0.0, False, str(exc)))

        self.call("progress.summary", "GET", "/progress/summary")
        self.call("progress.activity", "GET", "/progress/activity")

        buddies = self.call("buddies.list", "GET", "/buddies")
        self.call("buddies.active", "GET", "/buddies/active")
        try:
            buddies_data = buddies.json()["data"]
            if buddies_data:
                self.call("buddies.active.put", "PUT", "/buddies/active", json={"buddyId": buddies_data[0]["id"]})
        except Exception as exc:
            self.results.append(ApiResult("buddies.write.setup", "N/A", "N/A", 0, 0.0, False, str(exc)))

        models = self.call("buddy3d.models", "GET", "/buddy-3d/models")
        backgrounds = self.call("buddy3d.backgrounds", "GET", "/buddy-3d/backgrounds")
        self.call("buddy3d.settings", "GET", "/buddy-3d/settings")
        try:
            model_data = models.json()["data"]
            if model_data:
                self.call("buddy3d.equip_model", "PUT", "/buddy-3d/equipped-model", json={"modelId": model_data[0]["id"]})
            background_data = backgrounds.json()["data"]
            if background_data:
                self.call("buddy3d.background.put", "PUT", "/buddy-3d/room-background", json={"backgroundId": background_data[0]["id"]})
        except Exception as exc:
            self.results.append(ApiResult("buddy3d.write.setup", "N/A", "N/A", 0, 0.0, False, str(exc)))

        self.call("achievements.list", "GET", "/achievements")
        self.call("rewards.list", "GET", "/rewards")

    def print_report(self) -> None:
        print("API performance smoke report")
        print(f"threshold={self.threshold:.2f}s")
        for result in sorted(self.results, key=lambda item: item.seconds, reverse=True):
            mark = "SLOW" if result.seconds > self.threshold else "OK"
            status = "PASS" if result.ok else "FAIL"
            print(f"{mark:4} {status:4} {result.seconds:6.2f}s {result.status_code:3} {result.method:6} {result.path:72} {result.name} {result.detail}")

        failed = [item for item in self.results if not item.ok]
        slow = [item for item in self.results if item.seconds > self.threshold]
        print(f"total={len(self.results)} failed={len(failed)} slow={len(slow)}")
        if failed:
            raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=2.0)
    args = parser.parse_args()

    bench = ApiBench(threshold=args.threshold)
    bench.run()
    bench.print_report()


if __name__ == "__main__":
    main()
