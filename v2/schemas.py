from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PresenceMode(str, Enum):
    ACTIVE_USE = "ActiveUse"
    IDLE_SCREENSAVER = "IdleScreensaver"
    LOCKED_PRIVACY = "LockedPrivacy"
    SLEEP_OFFLINE = "SleepOffline"


class PresenceSignal(BaseModel):
    is_user_active: bool = True
    is_locked: bool = False
    is_sleeping: bool = False
    explicit_reveal: bool = False
    explicit_background: bool = False
    reason: str = "signal_update"


class PresenceState(BaseModel):
    mode: PresenceMode
    ui_foreground: bool
    reason: str
    allow_sensitive_details: bool
    updated_at: datetime


class BanterLevel(str, Enum):
    NORMAL = "Normal"
    WITTY = "Witty"
    SASSY = "Sassy"


class BanterProfile(BaseModel):
    level: BanterLevel = BanterLevel.WITTY
    safety_guardrails: bool = True


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REQUIRES_APPROVAL = "requires_approval"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class VerificationReport(BaseModel):
    passed: bool
    checks: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class TaskStep(BaseModel):
    step_id: str
    title: str
    agent: str
    status: TaskStatus = TaskStatus.PENDING
    details: str = ""
    requires_approval: bool = False
    verification: VerificationReport | None = None


class TaskGraph(BaseModel):
    task_id: str
    session_id: str
    user_text: str
    assigned_agent: str
    status: TaskStatus
    steps: list[TaskStep] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    result_summary: str | None = None
    last_error: str | None = None
    approval_id: str | None = None
    source_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verification_refs: list[str] = Field(default_factory=list)


class TaskRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    user_text: str = Field(min_length=1, max_length=4000)
    priority: TaskPriority = TaskPriority.NORMAL
    auto_execute: bool = True


class TaskControlRequest(BaseModel):
    action: Literal["pause", "resume", "cancel", "retry"]


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class ApprovalCard(BaseModel):
    approval_id: str
    source: Literal["task", "device_action", "voice", "system"]
    summary: str
    risk_level: Literal["low", "medium", "high"]
    requires_pin: bool = False
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionRequest(BaseModel):
    approve: bool
    spoken_pin: str | None = None


class DevicePlatform(str, Enum):
    PC = "pc"
    ANDROID = "android"


class DeviceActionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REQUIRES_APPROVAL = "requires_approval"


class DeviceActionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    platform: DevicePlatform
    action: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    sensitive: bool = False


class DeviceActionRecord(BaseModel):
    action_id: str
    session_id: str
    platform: DevicePlatform
    action: str
    parameters: dict[str, Any]
    status: DeviceActionStatus
    created_at: datetime
    updated_at: datetime
    approval_id: str | None = None
    verification: VerificationReport | None = None
    message: str = ""


class BillProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    due_day: int | None = Field(default=None, ge=1, le=31)
    due_date: date | None = None
    lead_days: list[int] = Field(default_factory=lambda: [7, 3, 1, 0])
    amount: float | None = None
    currency: str | None = Field(default=None, min_length=1, max_length=8)
    channels: list[str] = Field(default_factory=lambda: ["desktop", "mobile"])
    notes: str | None = None

    @model_validator(mode="after")
    def validate_due_rule(self) -> "BillProfileCreate":
        if self.due_day is None and self.due_date is None:
            raise ValueError("Either due_day or due_date must be provided.")
        return self


class BillProfile(BillProfileCreate):
    bill_id: str
    active: bool = True
    created_at: datetime
    updated_at: datetime


class BillReminderState(str, Enum):
    SCHEDULED = "scheduled"
    NOTIFIED = "notified"
    SNOOZED = "snoozed"
    PAID = "paid"
    OVERDUE = "overdue"


class BillReminderOccurrence(BaseModel):
    reminder_id: str
    bill_id: str
    bill_name: str
    due_date: date
    notify_on: date
    lead_day: int
    state: BillReminderState
    channels: list[str] = Field(default_factory=list)


class MarkBillPaidRequest(BaseModel):
    cycle_due_date: date | None = None
    note: str | None = None


class Recommendation(BaseModel):
    category: str
    message: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    suggested_actions: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    source_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    verification_refs: list[str] = Field(default_factory=list)


class ContextSnapshot(BaseModel):
    timestamp: datetime
    calendar_events: list[str] = Field(default_factory=list)
    weather_summary: str = "Unavailable"
    temperature_c: float | None = None
    is_rain_expected: bool = False
    traffic_summary: str = "Unknown"
    location_label: str = "Unknown"
    top_reminders: list[str] = Field(default_factory=list)
    style_profile: str = "Smart casual"
    user_status: str = "normal"


class MorningBriefing(BaseModel):
    summary: str
    highlights: list[str] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    generated_at: datetime


class VoiceCommandRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    transcript: str = Field(min_length=1, max_length=4000)
    wake_word_detected: bool = True
    spoken_pin: str | None = None


class VoiceAuthConfirmRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    approval_id: str = Field(min_length=4, max_length=64)
    spoken_pin: str | None = None
    confirm_phrase: str | None = None


class VoiceCommandResponse(BaseModel):
    accepted: bool
    message: str
    requires_auth: bool = False
    task_id: str | None = None
    approval_id: str | None = None


class VoiceInputRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    audio_base64: str | None = None
    mime_type: Literal["text/plain", "audio/wav", "audio/mpeg", "audio/webm", "audio/ogg"] = "text/plain"
    transcript_hint: str | None = Field(default=None, max_length=4000)
    language: str = Field(default="en", min_length=2, max_length=12)
    wake_word_detected: bool = True
    spoken_pin: str | None = None
    route_to_command: bool = True


class VoiceInputResponse(BaseModel):
    accepted: bool
    transcript: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    engine: str
    message: str
    command_response: VoiceCommandResponse | None = None
    warnings: list[str] = Field(default_factory=list)


class VoiceOutputRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=4000)
    voice: Literal["default", "calm", "clear", "energetic"] = "default"
    speak_locally: bool = False


class VoiceOutputResponse(BaseModel):
    accepted: bool
    message: str
    text: str
    voice: str
    engine: str
    spoken_locally: bool = False
    ssml: str | None = None
    duration_ms_estimate: int | None = None
    warnings: list[str] = Field(default_factory=list)


class VoiceListenerControlRequest(BaseModel):
    action: Literal["start", "stop"]
    session_id: str = Field(default="default", min_length=1, max_length=128)
    wake_word: str = Field(default="jarvis", min_length=2, max_length=40)


class VoiceListenerStatus(BaseModel):
    running: bool
    engine: str
    wake_word: str = "jarvis"
    last_transcript: str = ""
    last_error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class UIRevealRequest(BaseModel):
    reason: str = "manual_request"
    foreground: bool = True


class LearnedRoutine(BaseModel):
    routine_id: str
    trigger: str
    steps: list[str] = Field(default_factory=list)
    safeguards: list[str] = Field(default_factory=list)
    rollback_hint: str | None = None


class RecommendationResponse(BaseModel):
    context: ContextSnapshot
    recommendations: list[Recommendation] = Field(default_factory=list)


class SamplingMode(str, Enum):
    LOW = "low"
    BURST = "burst"


class PrivacyMaskReport(BaseModel):
    masked_fields: int
    categories: dict[str, int] = Field(default_factory=dict)
    retention_hours: int = 24
    ephemeral: bool = True


class ScreenContextSnapshot(BaseModel):
    timestamp: datetime
    mode: SamplingMode
    sampling_hz: float
    privacy_mode_enabled: bool
    sensitive_app_detected: bool
    deep_inspection_paused: bool
    app_name: str | None = None
    ocr_text_excerpt: str = ""
    ui_elements: list[str] = Field(default_factory=list)
    mask_report: PrivacyMaskReport | None = None


class ScreenExplainRequest(BaseModel):
    prompt: str = "Explain what is on my screen."
    visible_text: str = ""
    app_name: str | None = None
    burst: bool = True


class ScreenExplainResponse(BaseModel):
    summary: str
    masked_text: str
    mask_report: PrivacyMaskReport
    snapshot: ScreenContextSnapshot


class ScreenPrivacyModeRequest(BaseModel):
    enabled: bool
    reason: str = "manual_override"


class ScreenCaptureRequest(BaseModel):
    include_ocr: bool = True
    save_debug_image: bool = False
    burst: bool = True


class ScreenCaptureResponse(BaseModel):
    captured: bool
    message: str
    snapshot: ScreenContextSnapshot
    image_path: str | None = None
    ocr_text: str = ""
    vision_summary: str = ""
    warnings: list[str] = Field(default_factory=list)


class ScreenObservationControlRequest(BaseModel):
    action: Literal["start", "stop"]
    interval_seconds: float = Field(default=5.0, ge=1.0, le=60.0)
    include_ocr: bool = True


class ScreenObservationStatus(BaseModel):
    running: bool
    interval_seconds: float
    captures: int
    last_capture_at: datetime | None = None
    last_error: str | None = None
    last_snapshot: ScreenContextSnapshot | None = None


class SecurityScanRequest(BaseModel):
    scan_type: Literal["quick", "deep"] = "quick"
    indicators: list[str] = Field(default_factory=list)
    force: bool = False


class SecurityStatus(BaseModel):
    monitoring_enabled: bool = True
    adaptive_mode: bool = True
    threat_intel_enabled: bool = True
    private_mode_paused: bool = False
    native_av_status: str = "unknown"
    last_scan_at: datetime | None = None
    active_alerts: int = 0


class SecurityAlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class SecurityAlert(BaseModel):
    alert_id: str
    timestamp: datetime
    severity: Literal["low", "medium", "high"]
    title: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    recommended_actions: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True
    status: SecurityAlertStatus = SecurityAlertStatus.OPEN
    verification_refs: list[str] = Field(default_factory=list)


class SecurityActionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXECUTED = "executed"
    FAILED = "failed"


class SecurityActionProposal(BaseModel):
    action_id: str
    alert_id: str
    action: Literal["quarantine", "kill_process", "isolate_network", "remove_persistence", "dismiss"]
    risk_level: Literal["low", "medium", "high"]
    requires_confirmation: bool = True
    status: SecurityActionStatus = SecurityActionStatus.PENDING
    created_at: datetime
    updated_at: datetime
    verification_refs: list[str] = Field(default_factory=list)


class SecurityScanResult(BaseModel):
    scan_type: str
    generated_at: datetime
    alerts: list[SecurityAlert] = Field(default_factory=list)
    action_proposals: list[SecurityActionProposal] = Field(default_factory=list)
    summary: str


class SecurityActionDecisionRequest(BaseModel):
    approve: bool
    spoken_pin: str | None = None


class SecurityActionDecisionResponse(BaseModel):
    action: SecurityActionProposal
    message: str


class EndpointTelemetry(BaseModel):
    timestamp: datetime
    processes: list[dict[str, Any]] = Field(default_factory=list)
    network: list[dict[str, Any]] = Field(default_factory=list)
    startup_items: list[dict[str, Any]] = Field(default_factory=list)
    native_av_status: str = "unknown"
    warnings: list[str] = Field(default_factory=list)


class SecurityQuarantineRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    spoken_pin: str | None = None
    reason: str = Field(default="manual_quarantine", max_length=500)


class SecurityQuarantineResponse(BaseModel):
    quarantined: bool
    message: str
    original_path: str
    quarantine_path: str | None = None
    verification_refs: list[str] = Field(default_factory=list)


class CreativeJobType(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"
    DESIGN = "design"
    CODE_ASSIST = "code_assist"


class CreativeJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CreativeStepStatus(str, Enum):
    PLANNED = "planned"
    APPLIED = "applied"
    SKIPPED = "skipped"


class CreativeStep(BaseModel):
    step_id: str
    title: str
    tool: str
    status: CreativeStepStatus = CreativeStepStatus.PLANNED
    reversible: bool = True
    output_ref: str | None = None
    notes: str = ""


class CreativeJobRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    job_type: CreativeJobType
    instructions: str = Field(min_length=1, max_length=4000)
    input_path: str | None = None
    cloud_enhance: bool = False
    auto_apply: bool = True


class CreativeJob(BaseModel):
    job_id: str
    session_id: str
    job_type: CreativeJobType
    instructions: str
    status: CreativeJobStatus
    steps: list[CreativeStep] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    version_outputs: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    reversible: bool = True


class WebQARunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WebQARunRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=3, max_length=2048)
    viewport_profiles: list[str] = Field(default_factory=lambda: ["mobile", "tablet", "desktop"])
    include_lighthouse: bool = True
    include_a11y: bool = True
    include_visual_diff: bool = True
    include_smoke: bool = True


class WebQAFinding(BaseModel):
    finding_id: str
    severity: Literal["info", "low", "medium", "high"]
    category: str
    title: str
    description: str
    recommendation: str
    source_confidence: float = Field(ge=0.0, le=1.0)
    verification_refs: list[str] = Field(default_factory=list)


class WebQARun(BaseModel):
    run_id: str
    session_id: str
    url: str
    status: WebQARunStatus
    findings: list[WebQAFinding] = Field(default_factory=list)
    summary: str = ""
    created_at: datetime
    updated_at: datetime


class KnowledgeCaptureRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    source: Literal["meeting", "note", "task", "web", "chat"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=10000)
    tags: list[str] = Field(default_factory=list)


class KnowledgeArtifact(BaseModel):
    artifact_id: str
    session_id: str
    source: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    summary: str = ""
    searchable_tokens: list[str] = Field(default_factory=list)
    created_at: datetime


class SchedulerControlRequest(BaseModel):
    action: Literal["start", "stop", "run_once"]
    interval_seconds: int | None = Field(default=None, ge=30, le=86400)


class SchedulerStatus(BaseModel):
    running: bool
    interval_seconds: int
    last_run_at: datetime | None = None
    last_error: str | None = None
    events_recorded: int = 0


class SchedulerEvent(BaseModel):
    event_id: str
    event_type: Literal["bill_notification", "radar_scan", "error"]
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SocialTone(str, Enum):
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    CONFIDENT = "confident"
    WARM = "warm"
    FIRM = "firm"
    WITTY = "witty"


class SocialDraftScenario(str, Enum):
    EMAIL_REPLY = "email_reply"
    MESSAGE = "message"
    INTERVIEW_ANSWER = "interview_answer"
    CONVERSATION = "conversation"


class SocialDraftRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    scenario: SocialDraftScenario
    source_text: str = Field(default="", max_length=8000)
    goal: str = Field(min_length=1, max_length=2000)
    audience: str = Field(default="", max_length=200)
    tone: SocialTone = SocialTone.PROFESSIONAL
    constraints: list[str] = Field(default_factory=list)


class SocialDraft(BaseModel):
    draft_id: str
    session_id: str
    scenario: SocialDraftScenario
    draft: str
    rationale: str
    suggested_followups: list[str] = Field(default_factory=list)
    created_at: datetime


class InterviewAnswerRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=1000)
    background: str = Field(default="", max_length=4000)
    target_role: str = Field(default="", max_length=200)
    tone: SocialTone = SocialTone.CONFIDENT


class ConversationCoachRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    situation: str = Field(min_length=1, max_length=4000)
    desired_outcome: str = Field(min_length=1, max_length=1000)
    other_person: str = Field(default="", max_length=200)
    tone: SocialTone = SocialTone.WARM


class ConversationCoachResponse(BaseModel):
    coach_id: str
    opening_line: str
    talking_points: list[str] = Field(default_factory=list)
    pitfalls: list[str] = Field(default_factory=list)
    suggested_replies: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    created_at: datetime


class SimulationType(str, Enum):
    INTERVIEW = "interview"
    DEBATE = "debate"
    DECISION = "decision"


class SimulationRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    simulation_type: SimulationType
    prompt: str = Field(min_length=1, max_length=4000)
    rounds: int = Field(default=3, ge=1, le=8)
    stance: str = Field(default="", max_length=1000)
    context: str = Field(default="", max_length=6000)


class SimulationTurn(BaseModel):
    turn_index: int
    role: str
    message: str
    feedback: str | None = None


class SimulationRun(BaseModel):
    run_id: str
    session_id: str
    simulation_type: SimulationType
    prompt: str
    turns: list[SimulationTurn] = Field(default_factory=list)
    scorecard: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RadarFindingType(str, Enum):
    DEADLINE = "deadline"
    OPPORTUNITY = "opportunity"
    RISK = "risk"


class RadarFindingStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"


class RadarFinding(BaseModel):
    finding_id: str
    finding_type: RadarFindingType
    title: str
    description: str
    severity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_actions: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    status: RadarFindingStatus = RadarFindingStatus.OPEN
    created_at: datetime


class RadarScanRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    include_deadlines: bool = True
    include_opportunities: bool = True
    include_risks: bool = True
    context_text: str = Field(default="", max_length=8000)


class RadarScanResult(BaseModel):
    generated_at: datetime
    findings: list[RadarFinding] = Field(default_factory=list)
    summary: str


class PluginKind(str, Enum):
    TOOL = "tool"
    AGENT = "agent"
    CONNECTOR = "connector"
    WORKFLOW = "workflow"


class PluginManifest(BaseModel):
    plugin_id: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    kind: PluginKind
    description: str = Field(min_length=1, max_length=1000)
    entrypoint: str = Field(min_length=1, max_length=500)
    scopes: list[str] = Field(default_factory=list)
    author: str = Field(default="local", max_length=120)
    enabled: bool = True
    sha256: str | None = Field(default=None, max_length=128)
    signature: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_scopes(self) -> "PluginManifest":
        if any(scope.strip() in {"", "*"} for scope in self.scopes):
            raise ValueError("Plugin scopes must be explicit and cannot use wildcards.")
        return self


class PluginRegisterRequest(BaseModel):
    manifest: PluginManifest


class PluginRegistryEntry(PluginManifest):
    registered_at: datetime


class PluginExecuteRequest(BaseModel):
    action: str = Field(default="run", min_length=1, max_length=120)
    parameters: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=10, ge=1, le=60)


class PluginExecuteResponse(BaseModel):
    plugin_id: str
    executed: bool
    message: str
    returncode: int | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    sandbox: dict[str, Any] = Field(default_factory=dict)
