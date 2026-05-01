from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis.config import Settings
from jarvis.memory.manager import MemoryManager
from jarvis.orchestrator import Orchestrator
from jarvis.v2.approvals import ApprovalCenter
from jarvis.v2.briefing import BriefingService
from jarvis.v2.context import ContextSenseService
from jarvis.v2.creative import CreativeCopilotService
from jarvis.v2.device_control import DeviceControlService
from jarvis.v2.knowledge import KnowledgeDocService
from jarvis.v2.persona import PersonaEngine
from jarvis.v2.plugin_store import LocalPluginStoreService
from jarvis.v2.presence import PresenceStateMachine
from jarvis.v2.radar import RiskOpportunityRadarService
from jarvis.v2.reminders import ReminderOpsService
from jarvis.v2.screen_awareness import ScreenAwarenessService
from jarvis.v2.security import CyberSecurityGuardianService
from jarvis.v2.schemas import (
    ApprovalCard,
    ApprovalStatus,
    BanterLevel,
    BanterProfile,
    BillProfile,
    BillProfileCreate,
    ConversationCoachRequest,
    ConversationCoachResponse,
    CreativeJob,
    CreativeJobRequest,
    DeviceActionRecord,
    DeviceActionRequest,
    InterviewAnswerRequest,
    KnowledgeArtifact,
    KnowledgeCaptureRequest,
    MarkBillPaidRequest,
    PluginRegisterRequest,
    PluginRegistryEntry,
    PluginExecuteRequest,
    PluginExecuteResponse,
    PresenceSignal,
    PresenceState,
    RadarFinding,
    RadarScanRequest,
    RadarScanResult,
    RecommendationResponse,
    ScreenContextSnapshot,
    ScreenCaptureRequest,
    ScreenCaptureResponse,
    ScreenExplainRequest,
    ScreenExplainResponse,
    ScreenObservationControlRequest,
    ScreenObservationStatus,
    ScreenPrivacyModeRequest,
    SchedulerControlRequest,
    SchedulerEvent,
    SchedulerStatus,
    SecurityActionDecisionResponse,
    SecurityAlert,
    EndpointTelemetry,
    SecurityQuarantineRequest,
    SecurityQuarantineResponse,
    SecurityScanRequest,
    SecurityScanResult,
    SecurityStatus,
    SimulationRequest,
    SimulationRun,
    SocialDraft,
    SocialDraftRequest,
    TaskStatus,
    TaskControlRequest,
    TaskGraph,
    TaskRequest,
    UIRevealRequest,
    VoiceAuthConfirmRequest,
    VoiceCommandRequest,
    VoiceCommandResponse,
    VoiceInputRequest,
    VoiceInputResponse,
    VoiceListenerControlRequest,
    VoiceListenerStatus,
    VoiceOutputRequest,
    VoiceOutputResponse,
    WebQARun,
    WebQARunRequest,
)
from jarvis.v2.scheduler import BackgroundSchedulerService
from jarvis.v2.screensaver import ScreenSaverRenderService
from jarvis.v2.simulation import SimulationEngineService
from jarvis.v2.social import SocialIntelligenceService
from jarvis.v2.supervisor import SupervisorAgent
from jarvis.v2.tasking import TaskEngine
from jarvis.v2.voice import VoiceSecurityService
from jarvis.v2.voice_io import VoiceIOService
from jarvis.v2.voice_listener import VoiceListenerService
from jarvis.v2.webqa import WebQASpecialistService


@dataclass
class TaskCreateResult:
    task: TaskGraph
    approval: ApprovalCard | None = None


class V2AssistantService:
    def __init__(
        self,
        *,
        db_path: Path,
        v1_orchestrator: Orchestrator,
        memory: MemoryManager,
        voice_pin: str = "2580",
        settings: Settings | None = None,
    ) -> None:
        self._v1 = v1_orchestrator
        self._memory = memory
        self._settings = settings

        self.presence = PresenceStateMachine()
        encryption_secret = settings.local_ui_token if settings else None
        self.approvals = ApprovalCenter(db_path=db_path, encryption_secret=encryption_secret)
        self.persona = PersonaEngine()
        self.supervisor = SupervisorAgent()
        self.task_engine = TaskEngine(db_path=db_path, supervisor=self.supervisor)
        self.device_control = DeviceControlService(
            db_path=db_path,
            approvals=self.approvals,
            adb_path=settings.adb_path if settings else "adb",
        )
        self.reminders = ReminderOpsService(db_path=db_path)
        self.context = ContextSenseService(reminders=self.reminders)
        self.briefing = BriefingService(context_service=self.context)
        self.voice = VoiceSecurityService(self.approvals, default_pin=voice_pin)
        self.voice_io = VoiceIOService(settings)
        self.voice_listener = VoiceListenerService(self.voice_io, on_transcript=self.handle_voice_input)
        self.screensaver = ScreenSaverRenderService()
        self.screen = ScreenAwarenessService(
            data_dir=db_path.parent,
            tesseract_cmd=settings.tesseract_cmd if settings else None,
        )
        self.security = CyberSecurityGuardianService(db_path=db_path, pin_code=voice_pin)
        self.creative = CreativeCopilotService(
            db_path=db_path,
            ffmpeg_path=settings.ffmpeg_path if settings else "ffmpeg",
        )
        self.webqa = WebQASpecialistService(
            db_path=db_path,
            lighthouse_cmd=settings.lighthouse_cmd if settings else "lighthouse",
        )
        self.knowledge = KnowledgeDocService(db_path=db_path)
        self.social = SocialIntelligenceService(db_path=db_path)
        self.simulations = SimulationEngineService(db_path=db_path)
        self.radar = RiskOpportunityRadarService(
            db_path=db_path,
            reminders=self.reminders,
            knowledge=self.knowledge,
        )
        self.scheduler = BackgroundSchedulerService(
            db_path=db_path,
            reminders=self.reminders,
            radar=self.radar,
            interval_seconds=settings.scheduler_interval_seconds if settings else 300,
        )
        if settings and settings.scheduler_enabled:
            self.scheduler.start()
        self.plugins = LocalPluginStoreService(
            db_path=db_path,
            signing_secret=settings.plugin_signing_secret if settings else None,
        )
        self.banter_profile = BanterProfile(level=BanterLevel.WITTY, safety_guardrails=True)

    def set_banter_level(self, level: BanterLevel) -> BanterProfile:
        self.banter_profile = BanterProfile(level=level, safety_guardrails=True)
        return self.banter_profile

    def chat(self, *, session_id: str, user_text: str) -> dict[str, Any]:
        self.context.update_from_text(user_text)
        response = self._v1.handle_turn(session_id, user_text)
        styled = self.persona.apply_style(response.message, self.banter_profile)
        return {
            "type": response.type,
            "message": styled,
            "tool_trace_id": response.tool_trace_id,
            "presence": self.presence.get_state().model_dump(mode="json"),
        }

    def create_task(self, payload: TaskRequest) -> TaskCreateResult:
        self.context.update_from_text(payload.user_text)
        planned = self.supervisor.plan(session_id=payload.session_id, user_text=payload.user_text)
        task = self.task_engine.create_task(planned.task)
        approval = None

        if planned.requires_confirmation:
            approval = self.approvals.create_card(
                source="task",
                summary=planned.confirmation_summary or "Task confirmation required.",
                risk_level=planned.risk_level,  # type: ignore[arg-type]
                requires_pin=planned.risk_level == "high",
                metadata={"task_id": task.task_id},
            )
            task = self.task_engine.update_task(
                task.task_id,
                lambda t: self._bind_task_approval(t, approval.approval_id),
            ) or task
            return TaskCreateResult(task=task, approval=approval)

        if payload.auto_execute:
            task = self.task_engine.execute_task(task.task_id) or task
        return TaskCreateResult(task=task, approval=None)

    def get_task(self, task_id: str) -> TaskGraph | None:
        return self.task_engine.get_task(task_id)

    def control_task(self, task_id: str, payload: TaskControlRequest) -> TaskGraph | None:
        task = self.task_engine.apply_control(task_id, payload)
        if task is not None and payload.action == "resume":
            task = self.task_engine.execute_task(task_id) or task
        return task

    def handle_voice_command(self, payload: VoiceCommandRequest) -> VoiceCommandResponse:
        voice_result = self.voice.handle_voice_command(payload)
        if not voice_result.accepted:
            return voice_result
        task_result = self.create_task(
            TaskRequest(
                session_id=payload.session_id,
                user_text=payload.transcript,
                auto_execute=True,
            )
        )
        return VoiceCommandResponse(
            accepted=True,
            message="Voice command executed through task engine.",
            requires_auth=False,
            task_id=task_result.task.task_id,
            approval_id=task_result.approval.approval_id if task_result.approval else None,
        )

    def confirm_voice_auth(self, payload: VoiceAuthConfirmRequest) -> VoiceCommandResponse:
        result = self.voice.confirm(payload)
        if not result.accepted:
            return result
        card = self.approvals.get_card(payload.approval_id)
        if card and card.metadata.get("task_id"):
            task_id = str(card.metadata["task_id"])
            self.task_engine.apply_control(task_id, TaskControlRequest(action="retry"))
            self.task_engine.execute_task(task_id)
            result.task_id = task_id
        return result

    def handle_voice_input(self, payload: VoiceInputRequest) -> VoiceInputResponse:
        transcription = self.voice_io.transcribe(payload)
        if not transcription.accepted or not payload.route_to_command:
            return transcription
        command = self.handle_voice_command(
            VoiceCommandRequest(
                session_id=payload.session_id,
                transcript=transcription.transcript,
                wake_word_detected=payload.wake_word_detected,
                spoken_pin=payload.spoken_pin,
            )
        )
        return transcription.model_copy(update={"command_response": command})

    def create_voice_output(self, payload: VoiceOutputRequest) -> VoiceOutputResponse:
        return self.voice_io.synthesize(payload)

    def control_voice_listener(self, payload: VoiceListenerControlRequest) -> VoiceListenerStatus:
        if payload.action == "start":
            return self.voice_listener.start(session_id=payload.session_id, wake_word=payload.wake_word)
        return self.voice_listener.stop()

    def get_voice_listener_status(self) -> VoiceListenerStatus:
        return self.voice_listener.status()

    def create_device_action(self, payload: DeviceActionRequest) -> DeviceActionRecord:
        return self.device_control.create_action(payload)

    def get_device_action(self, action_id: str) -> DeviceActionRecord | None:
        return self.device_control.get_action(action_id)

    def create_bill_profile(self, payload: BillProfileCreate) -> BillProfile:
        return self.reminders.create_bill_profile(payload)

    def list_bill_profiles(self) -> list[BillProfile]:
        return self.reminders.list_bill_profiles()

    def mark_bill_paid(self, bill_id: str, payload: MarkBillPaidRequest) -> dict[str, str]:
        return self.reminders.mark_bill_paid(bill_id, payload)

    def recommendations(self) -> RecommendationResponse:
        return RecommendationResponse(
            context=self.context.snapshot(),
            recommendations=self.context.recommendations(),
        )

    def morning_briefing(self) -> dict[str, Any]:
        briefing = self.briefing.today()
        return briefing.model_dump(mode="json")

    def get_presence(self) -> dict[str, Any]:
        state = self.presence.get_state()
        screen_state = self.screen.state()
        render = self.screensaver.render_model(
            state=state,
            status_text="Listening in background" if state.mode.value == "ActiveUse" else "Screensaver active",
            top_reminder=(self.reminders.top_reminders(limit=1) or [""])[0],
            weather_summary=self.context.snapshot().weather_summary,
        )
        return {
            "state": state.model_dump(mode="json"),
            "screensaver_render": render,
            "screen_state": screen_state.model_dump(mode="json"),
        }

    def update_presence(self, signal: PresenceSignal) -> PresenceState:
        state = self.presence.apply_signal(signal)
        self.screen.update_from_presence(active=signal.is_user_active, locked=signal.is_locked)
        return state

    def ui_reveal(self, payload: UIRevealRequest) -> PresenceState:
        if payload.foreground:
            return self.presence.explicit_ui_reveal(reason=payload.reason)
        return self.presence.explicit_background(reason=payload.reason)

    def list_approvals(self) -> list[ApprovalCard]:
        return self.approvals.list_pending()

    def decide_approval(self, approval_id: str, approve: bool, *, spoken_pin: str | None = None) -> ApprovalCard | None:
        card = self.approvals.get_card(approval_id)
        if card is None:
            return None
        if card.status != ApprovalStatus.PENDING:
            return card
        if card.requires_pin and spoken_pin not in {"2580", "confirm"}:
            return None

        decided = self.approvals.approve(approval_id) if approve else self.approvals.deny(approval_id)
        if decided is None:
            return None

        if approve:
            self._run_approval_side_effects(decided)
        return decided

    def get_screen_state(self) -> ScreenContextSnapshot:
        return self.screen.state()

    def explain_screen(self, payload: ScreenExplainRequest) -> ScreenExplainResponse:
        return self.screen.explain(payload)

    def set_screen_privacy_mode(self, payload: ScreenPrivacyModeRequest) -> ScreenContextSnapshot:
        return self.screen.set_privacy_mode(payload.enabled)

    def capture_screen(self, payload: ScreenCaptureRequest) -> ScreenCaptureResponse:
        return self.screen.capture_screen(payload)

    def control_screen_observation(self, payload: ScreenObservationControlRequest) -> ScreenObservationStatus:
        return self.screen.control_observation(payload)

    def get_screen_observation_status(self) -> ScreenObservationStatus:
        return self.screen.observation_status()

    def get_security_status(self) -> SecurityStatus:
        return self.security.status(private_mode_paused=self._security_private_mode())

    def list_security_alerts(self) -> list[SecurityAlert]:
        return self.security.list_alerts()

    def run_security_scan(self, payload: SecurityScanRequest) -> SecurityScanResult:
        return self.security.run_scan(payload, private_mode_paused=self._security_private_mode())

    def collect_security_telemetry(self) -> EndpointTelemetry:
        return self.security.collect_telemetry()

    def quarantine_file(self, payload: SecurityQuarantineRequest) -> SecurityQuarantineResponse:
        return self.security.quarantine_file(payload)

    def decide_security_action(
        self, action_id: str, *, approve: bool, spoken_pin: str | None = None
    ) -> SecurityActionDecisionResponse | None:
        return self.security.decide_action(action_id, approve=approve, spoken_pin=spoken_pin)

    def create_creative_job(self, payload: CreativeJobRequest) -> CreativeJob:
        return self.creative.create_job(payload)

    def get_creative_job(self, job_id: str) -> CreativeJob | None:
        return self.creative.get_job(job_id)

    def create_webqa_run(self, payload: WebQARunRequest) -> WebQARun:
        return self.webqa.create_run(payload)

    def get_webqa_run(self, run_id: str) -> WebQARun | None:
        return self.webqa.get_run(run_id)

    def capture_knowledge(self, payload: KnowledgeCaptureRequest) -> KnowledgeArtifact:
        return self.knowledge.capture(payload)

    def list_knowledge(
        self,
        *,
        session_id: str | None = None,
        q: str | None = None,
        limit: int = 30,
    ) -> list[KnowledgeArtifact]:
        return self.knowledge.list_notes(session_id=session_id, q=q, limit=limit)

    def control_scheduler(self, payload: SchedulerControlRequest) -> SchedulerStatus:
        if payload.action == "start":
            return self.scheduler.start(interval_seconds=payload.interval_seconds)
        if payload.action == "stop":
            return self.scheduler.stop()
        return self.scheduler.run_once()

    def get_scheduler_status(self) -> SchedulerStatus:
        return self.scheduler.status()

    def list_scheduler_events(self, *, limit: int = 100) -> list[SchedulerEvent]:
        return self.scheduler.list_events(limit=limit)

    def draft_social_message(self, payload: SocialDraftRequest) -> SocialDraft:
        return self.social.draft_message(payload)

    def prepare_interview_answer(self, payload: InterviewAnswerRequest) -> SocialDraft:
        return self.social.prepare_interview_answer(payload)

    def coach_conversation(self, payload: ConversationCoachRequest) -> ConversationCoachResponse:
        return self.social.coach_conversation(payload)

    def create_simulation(self, payload: SimulationRequest) -> SimulationRun:
        return self.simulations.create_run(payload)

    def get_simulation(self, run_id: str) -> SimulationRun | None:
        return self.simulations.get_run(run_id)

    def run_radar_scan(self, payload: RadarScanRequest) -> RadarScanResult:
        return self.radar.scan(payload)

    def list_radar_findings(self, *, limit: int = 50) -> list[RadarFinding]:
        return self.radar.list_findings(limit=limit)

    def register_plugin(self, payload: PluginRegisterRequest) -> PluginRegistryEntry:
        return self.plugins.register(payload)

    def list_plugins(self) -> list[PluginRegistryEntry]:
        return self.plugins.list_plugins()

    def get_plugin(self, plugin_id: str) -> PluginRegistryEntry | None:
        return self.plugins.get(plugin_id)

    def execute_plugin(self, plugin_id: str, payload: PluginExecuteRequest) -> PluginExecuteResponse:
        return self.plugins.execute(plugin_id, payload)

    def _run_approval_side_effects(self, card: ApprovalCard) -> None:
        task_id = card.metadata.get("task_id")
        if task_id:
            self.task_engine.apply_control(str(task_id), TaskControlRequest(action="retry"))
            self.task_engine.execute_task(str(task_id))
        action_id = card.metadata.get("action_id")
        if action_id:
            self.device_control.execute_approved_action(str(action_id))

    def _bind_task_approval(self, task: TaskGraph, approval_id: str) -> TaskGraph:
        task.status = TaskStatus.REQUIRES_APPROVAL
        task.approval_id = approval_id
        task.updated_at = datetime.now(timezone.utc)
        return task

    def _security_private_mode(self) -> bool:
        screen_state = self.screen.state()
        return bool(screen_state.deep_inspection_paused or screen_state.privacy_mode_enabled)
