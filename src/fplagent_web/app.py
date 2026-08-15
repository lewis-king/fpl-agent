from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from fplagent_data.live_snapshots import SnapshotValidationError
from fplagent_data.manager_snapshots import archive_manager_snapshot
from fplagent_engine.manager_state_store import (
    ManagerStateContractError,
    current_actionable_event,
    derive_latest_manager_state,
)

from .chat_gateway import ChatGateway, ChatGatewayError, LocalQwenGateway
from .deadline_scheduler import DeadlineRefreshScheduler
from .decision_change_probe import DecisionChangeProbe
from .decision_refresh import WorkspaceRefreshCoordinator
from .market_telemetry_scheduler import MarketTelemetryScheduler
from .mcp_gateway import FplMcpError, LocalFplMcpGateway
from .models import (
    ChatRequest,
    ChatResponse,
    DeadlineScheduleView,
    GenerateSquadRequest,
    GenerateSquadResponse,
    ManagerProfileRequest,
    ManagerProfileView,
    MarketTelemetryView,
    McpConnectionView,
    McpLoginStarted,
    McpLoginStatus,
    McpSyncResult,
    PreseasonOptions,
    UploadAccepted,
    UploadAnalysisStarted,
    UploadConfirmed,
    UploadStatus,
    WorkspaceRefreshRequest,
    WorkspaceRefreshView,
    WorkspaceView,
)
from .preseason import PreseasonSquadError, PreseasonSquadService
from .profile import ManagerProfileStore
from .uploads import UploadStore, UploadStoreError
from .workspace import DEFAULT_REFRESH_STATE, WorkspaceBuilder, WorkspaceBuildError


@lru_cache(maxsize=1)
def workspace_builder() -> WorkspaceBuilder:
    return WorkspaceBuilder(refresh_state_path=DEFAULT_REFRESH_STATE)


@lru_cache(maxsize=1)
def upload_store() -> UploadStore:
    return UploadStore()


@lru_cache(maxsize=1)
def chat_gateway() -> LocalQwenGateway:
    return LocalQwenGateway()


@lru_cache(maxsize=1)
def preseason_service() -> PreseasonSquadService:
    return PreseasonSquadService()


@lru_cache(maxsize=1)
def manager_profile_store() -> ManagerProfileStore:
    return ManagerProfileStore()


@lru_cache(maxsize=1)
def fpl_mcp_gateway() -> LocalFplMcpGateway:
    return LocalFplMcpGateway()


@lru_cache(maxsize=1)
def workspace_refresh_coordinator() -> WorkspaceRefreshCoordinator:
    return WorkspaceRefreshCoordinator()


@lru_cache(maxsize=1)
def deadline_refresh_scheduler() -> DeadlineRefreshScheduler:
    return DeadlineRefreshScheduler(
        workspace_loader=lambda: workspace_builder().build(),
        profile_loader=lambda: manager_profile_store().get(),
        refresh_coordinator=workspace_refresh_coordinator(),
        material_probe=DecisionChangeProbe(
            event_resolver=current_actionable_event,
        ).probe,
    )


@lru_cache(maxsize=1)
def market_telemetry_scheduler() -> MarketTelemetryScheduler:
    return MarketTelemetryScheduler()


def create_app(
    *,
    workspace_factory: Callable[[], WorkspaceBuilder] = workspace_builder,
    uploads_factory: Callable[[], UploadStore] = upload_store,
    chat_factory: Callable[[], ChatGateway] = chat_gateway,
    preseason_factory: Callable[[], PreseasonSquadService] = preseason_service,
    profile_factory: Callable[[], ManagerProfileStore] = manager_profile_store,
    mcp_factory: Callable[[], LocalFplMcpGateway] = fpl_mcp_gateway,
    refresh_factory: Callable[[], WorkspaceRefreshCoordinator] = workspace_refresh_coordinator,
    scheduler_factory: Callable[[], DeadlineRefreshScheduler] = deadline_refresh_scheduler,
    market_scheduler_factory: Callable[[], MarketTelemetryScheduler] = (
        market_telemetry_scheduler
    ),
    manager_snapshot_archiver: Callable[
        [Mapping[str, Any]], Mapping[str, Any]
    ] = archive_manager_snapshot,
    manager_state_deriver: Callable[[int, int], Mapping[str, Any]] = derive_latest_manager_state,
    actionable_event_resolver: Callable[[], int] = current_actionable_event,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler = scheduler_factory()
        market_scheduler = market_scheduler_factory()
        scheduler.start()
        market_scheduler.start()
        try:
            yield
        finally:
            scheduler.stop()
            market_scheduler.stop()

    app = FastAPI(
        title="FPLAgent application API",
        version="0.1.0",
        description="Local phase-aware application layer over FPLAgent decisions and chat.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "fplagent-web"}

    @app.get("/api/v1/workspace", response_model=WorkspaceView)
    def get_workspace() -> WorkspaceView:
        try:
            return workspace_factory().build()
        except WorkspaceBuildError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/v1/workspace/refresh", response_model=WorkspaceRefreshView, status_code=202)
    def start_workspace_refresh(request: WorkspaceRefreshRequest) -> WorkspaceRefreshView:
        try:
            current = workspace_factory().build()
            profile = profile_factory().get()
            mode = "gw1" if current.phase.phase == "preseason" else "weekly"
            return refresh_factory().request(
                mode=mode,
                reason=request.reason,
                manager_entry_id=profile.fpl_entry_id,
                event=current.phase.decision_event or current.phase.event,
            )
        except WorkspaceBuildError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v1/workspace/refresh", response_model=WorkspaceRefreshView)
    def get_workspace_refresh() -> WorkspaceRefreshView:
        return refresh_factory().status()

    @app.get(
        "/api/v1/workspace/refresh/schedule",
        response_model=DeadlineScheduleView,
    )
    def get_deadline_refresh_schedule() -> DeadlineScheduleView:
        return scheduler_factory().status()

    @app.get("/api/v1/market/telemetry", response_model=MarketTelemetryView)
    def get_market_telemetry() -> MarketTelemetryView:
        return market_scheduler_factory().status()

    @app.get("/api/v1/preseason/options", response_model=PreseasonOptions)
    def get_preseason_options() -> PreseasonOptions:
        try:
            return preseason_factory().options()
        except PreseasonSquadError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @app.get("/api/v1/profile", response_model=ManagerProfileView)
    def get_manager_profile() -> ManagerProfileView:
        return profile_factory().get()

    @app.put("/api/v1/profile", response_model=ManagerProfileView)
    def save_manager_profile(request: ManagerProfileRequest) -> ManagerProfileView:
        return profile_factory().save(request)

    @app.get("/api/v1/integrations/fpl", response_model=McpConnectionView)
    async def get_fpl_mcp_connection() -> McpConnectionView:
        gateway = mcp_factory()
        try:
            tools = await gateway.list_tools()
        except FplMcpError as exc:
            return McpConnectionView(
                status="offline",
                url=gateway.url,
                message=str(exc),
            )
        required = {"begin_web_login", "poll_web_login", "get_manager_snapshot"}
        missing = required - set(tools)
        status = "ready"
        message = "The local MCP server is ready for authentication."
        if not missing and "get_auth_status" in tools:
            try:
                auth = await gateway.call("get_auth_status")
                if auth.get("status") == "connected":
                    status = "connected"
                    message = "The local MCP session is authenticated and ready to sync."
                else:
                    status = "not_authenticated"
            except FplMcpError:
                status = "ready"
        return McpConnectionView(
            status=status,
            url=gateway.url,
            tools_available=len(tools),
            message=(
                message
                if not missing
                else f"The MCP server is missing application tools: {', '.join(sorted(missing))}."
            ),
        )

    @app.post("/api/v1/integrations/fpl/login", response_model=McpLoginStarted)
    async def begin_fpl_mcp_login() -> McpLoginStarted:
        try:
            payload = await mcp_factory().call("begin_web_login")
            return McpLoginStarted.model_validate(payload)
        except (FplMcpError, ValueError) as exc:
            code = exc.code if isinstance(exc, FplMcpError) else "invalid_mcp_result"
            raise HTTPException(
                status_code=503,
                detail={"code": code, "message": str(exc)},
            ) from exc

    @app.get("/api/v1/integrations/fpl/login/{request_id}", response_model=McpLoginStatus)
    async def poll_fpl_mcp_login(request_id: str) -> McpLoginStatus:
        try:
            payload = await mcp_factory().call("poll_web_login", {"request_id": request_id})
            status = str(payload.get("status") or "failed")
            first = str(payload.get("first_name") or "").strip()
            last = str(payload.get("last_name") or "").strip()
            display_name = " ".join(value for value in (first, last) if value) or None
            result = McpLoginStatus(
                status=status,
                request_id=request_id,
                entry_id=(int(payload["entry_id"]) if payload.get("entry_id") else None),
                display_name=display_name,
                error=(str(payload["error"]) if payload.get("error") else None),
            )
            if result.status == "connected" and result.entry_id:
                profile_factory().mark_connected(
                    entry_id=result.entry_id, display_name=result.display_name
                )
            return result
        except (FplMcpError, ValueError) as exc:
            code = exc.code if isinstance(exc, FplMcpError) else "invalid_mcp_result"
            raise HTTPException(
                status_code=503,
                detail={"code": code, "message": str(exc)},
            ) from exc

    @app.post("/api/v1/integrations/fpl/sync", response_model=McpSyncResult)
    async def sync_fpl_manager() -> McpSyncResult:
        try:
            snapshot = await mcp_factory().call("get_manager_snapshot")
            manager_snapshot_archiver(snapshot)
            candidate_id = preseason_factory().adopt_mcp_snapshot(snapshot)
            entry_id = int(snapshot["entry_id"])
            observed_at = str(snapshot["observed_at"])
            manager_state_status = "blocked"
            manager_state_event: int | None = None
            manager_state_message = "The squad synced, but weekly state derivation did not run."
            manager_state_contract_sha256: str | None = None
            try:
                manager_state_event = actionable_event_resolver()
                derived = manager_state_deriver(entry_id, manager_state_event)
                raw_status = str(derived.get("status") or "blocked")
                manager_state_status = (
                    raw_status if raw_status in {"ready", "not_ready", "blocked"} else "blocked"
                )
                manager_state_message = str(
                    derived.get("message") or "Weekly state derivation returned no explanation."
                )
                if derived.get("contract_sha256"):
                    manager_state_contract_sha256 = str(derived["contract_sha256"])
            except (ManagerStateContractError, SnapshotValidationError, OSError, ValueError) as exc:
                manager_state_message = (
                    "The authenticated squad is synced, but exact weekly optimisation is blocked: "
                    f"{exc}"
                )
            profile_factory().mark_connected(
                entry_id=entry_id,
                observed_at=observed_at,
            )
            return McpSyncResult(
                entry_id=entry_id,
                candidate_id=candidate_id,
                observed_at=observed_at,
                player_count=len(snapshot.get("picks", [])),
                manager_state_status=manager_state_status,
                manager_state_event=manager_state_event,
                manager_state_message=manager_state_message,
                manager_state_contract_sha256=manager_state_contract_sha256,
                message=(
                    "The authenticated FPL squad is now active. " + manager_state_message
                ),
            )
        except (
            FplMcpError,
            PreseasonSquadError,
            SnapshotValidationError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            code = getattr(exc, "code", "invalid_mcp_snapshot")
            raise HTTPException(
                status_code=409,
                detail={"code": code, "message": str(exc)},
            ) from exc

    @app.post(
        "/api/v1/preseason/generate",
        response_model=GenerateSquadResponse,
    )
    def generate_preseason_squad(
        request: GenerateSquadRequest,
    ) -> GenerateSquadResponse:
        try:
            return preseason_factory().generate(request)
        except PreseasonSquadError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @app.post(
        "/api/v1/preseason/use-published",
        response_model=GenerateSquadResponse,
    )
    def use_published_preseason_squad() -> GenerateSquadResponse:
        try:
            return preseason_factory().use_published()
        except PreseasonSquadError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @app.post("/api/v1/uploads/team", response_model=UploadAccepted, status_code=201)
    async def upload_team(file: Annotated[UploadFile, File()]) -> UploadAccepted:
        try:
            data = await file.read()
            return uploads_factory().create(file.filename or "team", data)
        except UploadStoreError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        finally:
            await file.close()

    @app.get("/api/v1/uploads/{upload_id}", response_model=UploadStatus)
    def get_upload(upload_id: str) -> UploadStatus:
        try:
            return uploads_factory().get(upload_id)
        except UploadStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v1/uploads/{upload_id}/image", response_class=FileResponse)
    def get_upload_image(upload_id: str) -> FileResponse:
        try:
            path = uploads_factory().image_path(upload_id)
            status = uploads_factory().get(upload_id)
            return FileResponse(path, media_type=status.media_type, filename=status.filename)
        except UploadStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(
        "/api/v1/uploads/{upload_id}/analyse",
        response_model=UploadAnalysisStarted,
        status_code=202,
    )
    def analyse_upload(
        upload_id: str,
        background_tasks: BackgroundTasks,
    ) -> UploadAnalysisStarted:
        try:
            status, started = uploads_factory().start_analysis(upload_id)
            if started:
                background_tasks.add_task(uploads_factory().run_analysis, upload_id)
            return UploadAnalysisStarted(
                upload_id=upload_id,
                status=status.status,
                poll_url=f"/api/v1/uploads/{upload_id}",
            )
        except UploadStoreError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    @app.post(
        "/api/v1/uploads/{upload_id}/confirm",
        response_model=UploadConfirmed,
    )
    def confirm_upload(upload_id: str) -> UploadConfirmed:
        try:
            status = uploads_factory().get(upload_id)
            preseason_factory().adopt_upload(status.result or {})
            uploads_factory().confirm(upload_id)
            return UploadConfirmed(
                upload_id=upload_id,
                message="The imported squad is confirmed and is now active in the workspace.",
            )
        except (UploadStoreError, PreseasonSquadError) as exc:
            code = exc.code
            raise HTTPException(
                status_code=409,
                detail={"code": code, "message": str(exc)},
            ) from exc

    @app.post("/api/v1/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        try:
            return await chat_factory().chat(request)
        except ChatGatewayError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc

    return app


app = create_app()
