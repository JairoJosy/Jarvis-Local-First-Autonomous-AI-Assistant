from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from jarvis.audit import AuditLogger
from jarvis.authority import AuthorityLayer
from jarvis.config import get_settings
from jarvis.intent import IntentDetector
from jarvis.llm import GroqClient, LLMRouter, OllamaClient
from jarvis.memory.manager import MemoryManager
from jarvis.orchestrator import Orchestrator
from jarvis.planner import Planner
from jarvis.schemas import ChatRequest, ChatResponse
from jarvis.timeline import TimelineService
from jarvis.tools import OpenAppTool, ShellCommandTool, SystemInfoTool, ToolRegistry
from jarvis.ui import require_ui_token, screensaver_html, ui_shell_html
from jarvis.v2 import (
    ApprovalDecisionRequest,
    BillProfileCreate,
    ConversationCoachRequest,
    CreativeJobRequest,
    DeviceActionRequest,
    InterviewAnswerRequest,
    KnowledgeCaptureRequest,
    MarkBillPaidRequest,
    PluginExecuteRequest,
    PluginRegisterRequest,
    PresenceSignal,
    RadarScanRequest,
    SchedulerControlRequest,
    ScreenCaptureRequest,
    ScreenExplainRequest,
    ScreenObservationControlRequest,
    ScreenPrivacyModeRequest,
    SecurityActionDecisionRequest,
    SecurityQuarantineRequest,
    SecurityScanRequest,
    SimulationRequest,
    SocialDraftRequest,
    TaskControlRequest,
    TaskRequest,
    UIRevealRequest,
    V2AssistantService,
    VoiceAuthConfirmRequest,
    VoiceCommandRequest,
    VoiceInputRequest,
    VoiceListenerControlRequest,
    VoiceOutputRequest,
    WebQARunRequest,
)


def build_app() -> FastAPI:
    settings = get_settings()

    llm_router = LLMRouter(
        primary=GroqClient(settings),
        fallback=OllamaClient(settings),
    )
    memory = MemoryManager(settings)
    tools = ToolRegistry([SystemInfoTool(), OpenAppTool(), ShellCommandTool()])
    timeline = TimelineService(memory.structured, settings.timezone)
    orchestrator = Orchestrator(
        settings=settings,
        intent_detector=IntentDetector(),
        planner=Planner(llm_router, settings),
        memory=memory,
        authority=AuthorityLayer(),
        tools=tools,
        audit=AuditLogger(settings.sqlite_path),
        timeline=timeline,
    )

    app = FastAPI(title="Jarvis v1", version="0.1.0")
    app.state.orchestrator = orchestrator
    app.state.memory = memory
    app.state.timeline = timeline
    app.state.settings = settings
    app.state.v2 = V2AssistantService(
        db_path=settings.sqlite_path,
        v1_orchestrator=orchestrator,
        memory=memory,
        settings=settings,
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ui", response_class=HTMLResponse)
    def ui(request: Request) -> HTMLResponse:
        require_ui_token(request, app.state.settings.local_ui_token)
        return HTMLResponse(ui_shell_html(app.state.settings.local_ui_token))

    @app.get("/screensaver", response_class=HTMLResponse)
    def screensaver(request: Request) -> HTMLResponse:
        require_ui_token(request, app.state.settings.local_ui_token)
        return HTMLResponse(screensaver_html(app.state.settings.local_ui_token))

    @app.post("/chat", response_model=ChatResponse)
    def chat(payload: ChatRequest) -> ChatResponse:
        return app.state.orchestrator.handle_turn(payload.session_id, payload.user_text)

    @app.get("/memory/person/{name}")
    def get_person(name: str) -> dict:
        person = app.state.memory.query_person(name)
        if person is None:
            raise HTTPException(status_code=404, detail="Person not found.")
        return person

    @app.get("/memory/timeline")
    def get_timeline(
        range: str = Query(default="recent", pattern="^(today|recent)$"),
        limit: int = Query(default=10, ge=1, le=100),
    ) -> dict:
        items = app.state.memory.query_timeline(range_key=range, limit=limit)
        summary = app.state.orchestrator.timeline_summary(range, limit)
        return {"range": range, "items": items, "summary": summary}

    @app.get("/memory/search")
    def search_memory(q: str = Query(min_length=1), limit: int = Query(default=5, ge=1, le=20)) -> dict:
        results = app.state.memory.semantic_search(q, limit=limit)
        return {"query": q, "results": results}

    @app.post("/v2/tasks")
    def create_task(payload: TaskRequest) -> dict:
        result = app.state.v2.create_task(payload)
        response = {"task": result.task.model_dump(mode="json")}
        if result.approval:
            response["approval"] = result.approval.model_dump(mode="json")
        return response

    @app.post("/v2/chat")
    def v2_chat(payload: ChatRequest) -> dict:
        return app.state.v2.chat(session_id=payload.session_id, user_text=payload.user_text)

    @app.get("/v2/tasks/{task_id}")
    def get_task(task_id: str) -> dict:
        task = app.state.v2.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return task.model_dump(mode="json")

    @app.post("/v2/tasks/{task_id}/control")
    def control_task(task_id: str, payload: TaskControlRequest) -> dict:
        task = app.state.v2.control_task(task_id, payload)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return task.model_dump(mode="json")

    @app.post("/v2/voice/commands")
    def voice_command(payload: VoiceCommandRequest) -> dict:
        result = app.state.v2.handle_voice_command(payload)
        return result.model_dump(mode="json")

    @app.post("/v2/voice/auth/confirm")
    def voice_confirm(payload: VoiceAuthConfirmRequest) -> dict:
        result = app.state.v2.confirm_voice_auth(payload)
        return result.model_dump(mode="json")

    @app.post("/v2/voice/input")
    def voice_input(payload: VoiceInputRequest) -> dict:
        result = app.state.v2.handle_voice_input(payload)
        return result.model_dump(mode="json")

    @app.post("/v2/voice/output")
    def voice_output(payload: VoiceOutputRequest) -> dict:
        result = app.state.v2.create_voice_output(payload)
        return result.model_dump(mode="json")

    @app.post("/v2/voice/listener")
    def voice_listener_control(payload: VoiceListenerControlRequest) -> dict:
        result = app.state.v2.control_voice_listener(payload)
        return result.model_dump(mode="json")

    @app.get("/v2/voice/listener")
    def voice_listener_status() -> dict:
        return app.state.v2.get_voice_listener_status().model_dump(mode="json")

    @app.post("/v2/device/actions")
    def create_device_action(payload: DeviceActionRequest) -> dict:
        action = app.state.v2.create_device_action(payload)
        return action.model_dump(mode="json")

    @app.get("/v2/device/actions/{action_id}")
    def get_device_action(action_id: str) -> dict:
        action = app.state.v2.get_device_action(action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found.")
        return action.model_dump(mode="json")

    @app.post("/v2/reminders/bills")
    def create_bill(payload: BillProfileCreate) -> dict:
        bill = app.state.v2.create_bill_profile(payload)
        return bill.model_dump(mode="json")

    @app.get("/v2/reminders/bills")
    def list_bills() -> list[dict]:
        return [bill.model_dump(mode="json") for bill in app.state.v2.list_bill_profiles()]

    @app.post("/v2/reminders/bills/{bill_id}/mark-paid")
    def mark_bill_paid(bill_id: str, payload: MarkBillPaidRequest) -> dict:
        try:
            return app.state.v2.mark_bill_paid(bill_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v2/briefings/today")
    def get_morning_briefing() -> dict:
        return app.state.v2.morning_briefing()

    @app.get("/v2/recommendations/next")
    def get_recommendations() -> dict:
        return app.state.v2.recommendations().model_dump(mode="json")

    @app.get("/v2/presence/state")
    def get_presence_state() -> dict:
        return app.state.v2.get_presence()

    @app.post("/v2/presence/state")
    def update_presence_state(payload: PresenceSignal) -> dict:
        state = app.state.v2.update_presence(payload)
        return state.model_dump(mode="json")

    @app.post("/v2/ui/reveal")
    def ui_reveal(payload: UIRevealRequest) -> dict:
        state = app.state.v2.ui_reveal(payload)
        return state.model_dump(mode="json")

    @app.get("/v2/approvals")
    def list_approvals() -> list[dict]:
        return [card.model_dump(mode="json") for card in app.state.v2.list_approvals()]

    @app.post("/v2/approvals/{approval_id}")
    def decide_approval(approval_id: str, payload: ApprovalDecisionRequest) -> dict:
        card = app.state.v2.decide_approval(
            approval_id,
            approve=payload.approve,
            spoken_pin=payload.spoken_pin,
        )
        if card is None:
            raise HTTPException(status_code=404, detail="Approval not found or authentication failed.")
        return card.model_dump(mode="json")

    @app.get("/v2/screen/state")
    def get_screen_state() -> dict:
        return app.state.v2.get_screen_state().model_dump(mode="json")

    @app.post("/v2/screen/explain")
    def explain_screen(payload: ScreenExplainRequest) -> dict:
        result = app.state.v2.explain_screen(payload)
        return result.model_dump(mode="json")

    @app.post("/v2/screen/privacy-mode")
    def set_screen_privacy_mode(payload: ScreenPrivacyModeRequest) -> dict:
        state = app.state.v2.set_screen_privacy_mode(payload)
        return state.model_dump(mode="json")

    @app.post("/v2/screen/capture")
    def capture_screen(payload: ScreenCaptureRequest) -> dict:
        result = app.state.v2.capture_screen(payload)
        return result.model_dump(mode="json")

    @app.post("/v2/screen/observe")
    def control_screen_observation(payload: ScreenObservationControlRequest) -> dict:
        result = app.state.v2.control_screen_observation(payload)
        return result.model_dump(mode="json")

    @app.get("/v2/screen/observe")
    def get_screen_observation_status() -> dict:
        return app.state.v2.get_screen_observation_status().model_dump(mode="json")

    @app.get("/v2/security/status")
    def get_security_status() -> dict:
        return app.state.v2.get_security_status().model_dump(mode="json")

    @app.get("/v2/security/alerts")
    def get_security_alerts() -> list[dict]:
        return [a.model_dump(mode="json") for a in app.state.v2.list_security_alerts()]

    @app.get("/v2/security/telemetry")
    def get_security_telemetry() -> dict:
        return app.state.v2.collect_security_telemetry().model_dump(mode="json")

    @app.post("/v2/security/scan")
    def run_security_scan(payload: SecurityScanRequest) -> dict:
        result = app.state.v2.run_security_scan(payload)
        return result.model_dump(mode="json")

    @app.post("/v2/security/actions/{action_id}")
    def decide_security_action(action_id: str, payload: SecurityActionDecisionRequest) -> dict:
        result = app.state.v2.decide_security_action(
            action_id,
            approve=payload.approve,
            spoken_pin=payload.spoken_pin,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Security action not found.")
        return result.model_dump(mode="json")

    @app.post("/v2/security/quarantine")
    def quarantine_file(payload: SecurityQuarantineRequest) -> dict:
        result = app.state.v2.quarantine_file(payload)
        return result.model_dump(mode="json")

    @app.post("/v2/creative/jobs")
    def create_creative_job(payload: CreativeJobRequest) -> dict:
        job = app.state.v2.create_creative_job(payload)
        return job.model_dump(mode="json")

    @app.get("/v2/creative/jobs/{job_id}")
    def get_creative_job(job_id: str) -> dict:
        job = app.state.v2.get_creative_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Creative job not found.")
        return job.model_dump(mode="json")

    @app.post("/v2/webqa/runs")
    def create_webqa_run(payload: WebQARunRequest) -> dict:
        run = app.state.v2.create_webqa_run(payload)
        return run.model_dump(mode="json")

    @app.get("/v2/webqa/runs/{run_id}")
    def get_webqa_run(run_id: str) -> dict:
        run = app.state.v2.get_webqa_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Web QA run not found.")
        return run.model_dump(mode="json")

    @app.post("/v2/knowledge/capture")
    def capture_knowledge(payload: KnowledgeCaptureRequest) -> dict:
        artifact = app.state.v2.capture_knowledge(payload)
        return artifact.model_dump(mode="json")

    @app.get("/v2/knowledge/notes")
    def get_knowledge_notes(
        session_id: str | None = Query(default=None),
        q: str | None = Query(default=None),
        limit: int = Query(default=30, ge=1, le=200),
    ) -> list[dict]:
        artifacts = app.state.v2.list_knowledge(session_id=session_id, q=q, limit=limit)
        return [a.model_dump(mode="json") for a in artifacts]

    @app.post("/v2/scheduler")
    def control_scheduler(payload: SchedulerControlRequest) -> dict:
        return app.state.v2.control_scheduler(payload).model_dump(mode="json")

    @app.get("/v2/scheduler")
    def get_scheduler_status() -> dict:
        return app.state.v2.get_scheduler_status().model_dump(mode="json")

    @app.get("/v2/scheduler/events")
    def get_scheduler_events(limit: int = Query(default=100, ge=1, le=1000)) -> list[dict]:
        return [item.model_dump(mode="json") for item in app.state.v2.list_scheduler_events(limit=limit)]

    @app.post("/v2/social/draft")
    def draft_social_message(payload: SocialDraftRequest) -> dict:
        draft = app.state.v2.draft_social_message(payload)
        return draft.model_dump(mode="json")

    @app.post("/v2/social/interview-answer")
    def prepare_interview_answer(payload: InterviewAnswerRequest) -> dict:
        draft = app.state.v2.prepare_interview_answer(payload)
        return draft.model_dump(mode="json")

    @app.post("/v2/social/conversation-coach")
    def coach_conversation(payload: ConversationCoachRequest) -> dict:
        response = app.state.v2.coach_conversation(payload)
        return response.model_dump(mode="json")

    @app.post("/v2/simulations")
    def create_simulation(payload: SimulationRequest) -> dict:
        run = app.state.v2.create_simulation(payload)
        return run.model_dump(mode="json")

    @app.get("/v2/simulations/{run_id}")
    def get_simulation(run_id: str) -> dict:
        run = app.state.v2.get_simulation(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Simulation not found.")
        return run.model_dump(mode="json")

    @app.post("/v2/radar/scan")
    def run_radar_scan(payload: RadarScanRequest) -> dict:
        result = app.state.v2.run_radar_scan(payload)
        return result.model_dump(mode="json")

    @app.get("/v2/radar/findings")
    def list_radar_findings(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
        return [item.model_dump(mode="json") for item in app.state.v2.list_radar_findings(limit=limit)]

    @app.get("/v2/plugins")
    def list_plugins() -> list[dict]:
        return [item.model_dump(mode="json") for item in app.state.v2.list_plugins()]

    @app.post("/v2/plugins/register")
    def register_plugin(payload: PluginRegisterRequest) -> dict:
        try:
            entry = app.state.v2.register_plugin(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return entry.model_dump(mode="json")

    @app.get("/v2/plugins/{plugin_id}")
    def get_plugin(plugin_id: str) -> dict:
        plugin = app.state.v2.get_plugin(plugin_id)
        if plugin is None:
            raise HTTPException(status_code=404, detail="Plugin not found.")
        return plugin.model_dump(mode="json")

    @app.post("/v2/plugins/{plugin_id}/execute")
    def execute_plugin(plugin_id: str, payload: PluginExecuteRequest) -> dict:
        result = app.state.v2.execute_plugin(plugin_id, payload)
        if not result.executed and result.message == "Plugin not found.":
            raise HTTPException(status_code=404, detail="Plugin not found.")
        return result.model_dump(mode="json")

    return app


app = build_app()
