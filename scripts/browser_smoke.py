"""Verify the local workbench through an isolated headless browser."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    root = Path(__file__).resolve().parent.parent
    credentials = (root / "data/admin-initial.txt").read_text(encoding="utf-8").splitlines()
    password = credentials[1].split(" ", 1)[1]
    evidence = root / "evidence"
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            headless=True,
        )
        context = browser.new_context(viewport={"width": 1500, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8000", wait_until="networkidle")
        page.get_by_role("heading", name="管理员登录").wait_for()
        page.screenshot(path=str(evidence / "workbench-login.png"), full_page=True)
        page.locator('input[autocomplete="username"]').fill("admin")
        page.locator('input[autocomplete="current-password"]').fill(password)
        page.get_by_role("button", name="进入工作台").click()
        page.get_by_role("heading", name="商机审核", exact=True).wait_for()
        with page.expect_response(lambda response: "/imports/experiments" in response.url, timeout=60000) as imported:
            page.get_by_role("button", name="导入采集结果").click()
        assert imported.value.status == 200
        page.get_by_text("导入完成，新增", exact=False).wait_for()
        page.wait_for_load_state("networkidle")
        page.locator(".el-loading-mask").wait_for(state="hidden")
        page.locator(".el-message").wait_for(state="hidden")
        page.screenshot(path=str(evidence / "workbench-candidates.png"), animations="disabled")
        page.locator(".el-table__body tbody tr").first.click()
        page.get_by_role("dialog").wait_for()
        page.get_by_text("判断依据或跟进记录（必填）", exact=True).wait_for()
        page.screenshot(path=str(evidence / "workbench-detail.png"), animations="disabled")
        page.get_by_role("button", name="取消", exact=True).click()
        with page.expect_response(lambda response: "/leads?" in response.url and "candidate_only=false" in response.url) as all_posts:
            page.locator(".el-switch__core").click()
        assert all_posts.value.status == 200
        all_count = all_posts.value.json()["total"]
        page.get_by_role("button", name="采集覆盖", exact=True).click()
        page.get_by_role("heading", name="完整日采集记录", exact=True).wait_for()
        page.screenshot(path=str(evidence / "workbench-coverage.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(evidence / "workbench-mobile.png"), animations="disabled")
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        assert not overflow, "Mobile page overflows horizontally"
        dashboard = context.request.get("http://127.0.0.1:8000/api/v1/dashboard").json()
        jobs = context.request.get("http://127.0.0.1:8000/api/v1/scan-jobs").json()
        assert not errors, errors
        result = {"browser": "isolated headless Edge", "javascript_errors": errors,
                  "all_posts": all_count, "scan_records": len(jobs["items"]), "dashboard": dashboard,
                  "mobile_horizontal_overflow": overflow, "import_result": imported.value.json()}
        (evidence / "workbench-browser-check.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(json.dumps({key: value for key, value in result.items() if key != "dashboard"}, ensure_ascii=False))
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
