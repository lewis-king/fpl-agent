# Decision refresh: connection, execution and status

Updated 9 September 2026 after the GW4 refresh UX incident.

## What the three timestamps mean

- **Last attempt:** when the latest decision job started. A failed/blocked attempt is not a successful validation.
- **GWn last validated:** the latest successfully published or revalidated decision for the actionable event. A GW3 result must not count as a validated GW4 result.
- **Next automatic check:** the scheduled cadence or retry time. If required manager information is missing or evidence is deterministically blocked, show a waiting/paused state instead of pretending work is running.

The banner shows actual server status, its explanation, and start/finish times. Detailed failure codes/run IDs remain expandable. The normal cadence is six hours, tightening to two hours in the final day and thirty minutes in the final three hours; material changes can trigger earlier checks.

## Connection is not the same as squad sync

MCP authentication alone does not archive a current manager snapshot. The required sequence is:

1. Authenticate through the local MCP login service.
2. Call `/api/v1/integrations/fpl/sync` to archive the private squad and derive the current manager contract.
3. Request `/api/v1/workspace/refresh` using the current event.
4. Observe `/api/v1/workspace/refresh` until the server reports a terminal state.
5. Fetch the workspace again to display the validated result.

The profile dialog now distinguishes a completed authenticated sync from simply saving a public manager ID. A successful sync requests the decision run and returns to the workspace immediately; it does not wait inside the login modal for the whole simulation.

Manual **Refresh decisions / Sync FPL & retry** checks the actual MCP session, not a possibly stale workspace connection flag, before reading the current squad. App-open recovery also retries a previously missing/blocked input after a successful sync, even when the 15 player IDs have not changed.

## Background jobs and progress

The API owns a single-flight worker; closing the browser does not cancel it. The app polls persisted run status and schedule every three seconds, using sequential read requests. It follows jobs started by the scheduler or another tab, not just jobs launched by that browser. Polling itself never starts jobs.

Weekly pipeline progress is persisted at five boundaries:

1. Refresh official data, markets, lineup evidence and forecasts.
2. Validate manager squad, bank, free transfers and chips.
3. Compare transfers, XI/bench/captaincy and chip policies.
4. Audit the candidate against deadline evidence.
5. Publish, recheck and archive the recommendation.

The stage count is **not a time-based ETA**: simulation normally dominates runtime. On 9 September the first successful GW4 run took approximately 101 seconds, from 08:11:50 to 08:13:32 BST. That is an observation, not a fixed runtime guarantee.

Missing manager state pauses unattended retries until a newer private sync arrives. The scheduler resumes on that sync, even if a frontend completion callback was missed. Temporary failures retain their retry time in the schedule response; deterministic evidence blocks remain paused until resolved or explicitly retried. No gate is bypassed.

The server must remain running for jobs to finish. Stopping the API interrupts its in-process worker; previously published artifacts remain recoverable.

## Regression coverage

```bash
.venv/bin/python -m pytest tests/test_engine_deadline_pipeline.py tests/test_web_decision_refresh.py tests/test_web_deadline_scheduler.py -q
cd web
npm test
npm run test:ui
npm run build
npm run lint
```

The browser test needs the local API/Vite running and Playwright Chromium installed (or `CHROMIUM_EXECUTABLE_PATH`). It reads a workspace fixture, then intercepts API calls: no real login credentials, manager syncs, FPL writes or decision refreshes are submitted. It tests login → sync → decision start → publication, external-run detection, exact blockers, timestamps and mobile overflow. Screenshots are placed in the system temporary directory for review.
