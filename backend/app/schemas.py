"""The shapes of everything the API sends and receives. They are the Python twin of src/api/types.ts, which is the
source of truth: if the two ever disagree, types.ts wins.

Field names are camelCase on purpose, exactly as they appear in the JSON. That way a field here and the same field
in the website are spelled identically, and no renaming layer sits in between.

A field marked "optional" in the contract is left out of the JSON when it has no value (it is not sent as null).
A field that the contract allows to be null (for example `confidence` or `traditional`) is always sent.
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, Field, model_serializer

# ------------------------------------------------------------------ small building blocks

FeatureStatus = Literal['detected', 'uncertain', 'not_visible']
HandSide = Literal['left', 'right']
FeatureId = Literal['heart', 'head', 'life', 'fate', 'sun']
QualityLevel = Literal['good', 'fair', 'poor']
CheckId = Literal['file_type', 'integrity', 'dimensions', 'blur', 'lighting', 'palm_visible']
CheckStatus = Literal['pass', 'warn', 'fail']
ThemeId = Literal['personality', 'career', 'financial', 'relationships', 'future']
ThemeSource = Literal['heart', 'head', 'life', 'fate', 'sun', 'shape']
BoundaryKind = Literal['medical', 'financial', 'employment', 'relationship', 'lifespan', 'prediction', 'not_seen', 'off_topic']
StageKey = Literal['validate', 'resize', 'gray', 'blur', 'contrast', 'edges', 'threshold', 'morphology', 'lines', 'reading']
StageState = Literal['running', 'done', 'failed']

#: A point on a photo as fractions of its width and height (0 to 1), origin at the top left.
NormPoint = tuple[float, float]


class Model(BaseModel):
    """Base of every shape. Names listed in `_omit_when_none` are left out of the JSON when they hold None."""

    _omit_when_none: ClassVar[tuple[str, ...]] = ()

    @model_serializer(mode='wrap')
    def _drop_missing(self, handler):
        data = handler(self)
        for name in self._omit_when_none:
            if data.get(name) is None:
                data.pop(name, None)
        return data


# ------------------------------------------------------------------ photo checks


class PhotoCheck(Model):
    id: CheckId
    label: str
    status: CheckStatus
    message: str


class ValidationResult(Model):
    side: HandSide
    ok: bool
    width: int
    height: int
    checks: list[PhotoCheck]


class PhotoQuality(Model):
    sharpness: QualityLevel
    lighting: QualityLevel
    resolution: QualityLevel
    palmVisible: bool
    score: float


class PhotoSize(Model):
    width: int
    height: int


# ------------------------------------------------------------------ findings


class NormBox(Model):
    x: float
    y: float
    w: float
    h: float


class FeatureTraits(Model):
    _omit_when_none = ('length', 'curve', 'clarity')
    length: Literal['short', 'medium', 'long'] | None = None
    curve: Literal['straight', 'gentle', 'pronounced'] | None = None
    clarity: Literal['faint', 'clear', 'deep'] | None = None


class FeatureResult(Model):
    id: FeatureId
    name: str
    status: FeatureStatus
    path: list[NormPoint]
    searchArea: NormBox
    confidence: float | None
    observation: str
    traits: FeatureTraits
    method: str


class PalmShapeTraits(Model):
    _omit_when_none = ('palm', 'fingers')
    palm: Literal['square', 'long'] | None = None
    fingers: Literal['short', 'long'] | None = None


class PalmShape(Model):
    status: FeatureStatus
    traits: PalmShapeTraits
    palmRatio: float | None
    fingerRatio: float | None
    confidence: float | None
    observation: str
    method: str


class OtherCrease(Model):
    id: str
    path: list[NormPoint]
    confidence: float
    observation: str


class HandAnalysis(Model):
    side: HandSide
    photo: PhotoSize
    quality: PhotoQuality
    outline: list[NormPoint] | None
    features: list[FeatureResult]
    palmShape: PalmShape
    otherCreases: list[OtherCrease]
    methodVersion: str


# ------------------------------------------------------------------ report


class SideObservation(Model):
    status: FeatureStatus
    text: str


class ObservedPair(Model):
    left: SideObservation
    right: SideObservation


class TraditionalPair(Model):
    left: str | None
    right: str | None


class ReportSection(Model):
    featureId: FeatureId
    title: str
    observed: ObservedPair
    traditional: TraditionalPair
    comparison: str | None


class ShapeSection(Model):
    observed: ObservedPair
    traditional: TraditionalPair
    comparison: str | None


class ThemeSection(Model):
    themeId: ThemeId
    title: str
    label: Literal['traditional'] = 'traditional'
    traditional: str | None
    basedOn: list[ThemeSource]
    leftOut: list[ThemeSource]


class Report(Model):
    summary: str
    sections: list[ReportSection]
    themes: list[ThemeSection]
    shape: ShapeSection
    uncertainty: list[str]
    disclaimer: str
    generatedAt: str


class ReadingMeta(Model):
    _omit_when_none = ('note',)
    provider: str
    model: str
    knowledgeBase: str
    prompt: str
    pipeline: str
    mock: bool
    #: one plain sentence about how the words were written: which passages the language model wrote, and why any came from
    #: the knowledge base instead. Left out when there is nothing to say.
    note: str | None = None


class Hands(Model):
    left: HandAnalysis
    right: HandAnalysis


class Reading(Model):
    _omit_when_none = ('name',)
    id: str
    profileId: str
    createdAt: str
    #: what the person called this reading when they made it (or later). Left out when it has no name, and the website
    #: then calls it by its date. It is never sent to Gemini.
    name: str | None = None
    hands: Hands
    report: Report
    meta: ReadingMeta


class StatusCounts(Model):
    detected: int
    uncertain: int
    not_visible: int


class ReadingSummary(Model):
    _omit_when_none = ('name',)
    id: str
    profileId: str
    profileName: str
    name: str | None = None
    createdAt: str
    counts: StatusCounts
    headline: str
    conversationCount: int


# ------------------------------------------------------------------ profiles


class StoredProfile(Model):
    """What is kept for a profile. The counts are worked out when it is listed."""

    id: str
    name: str
    owner: Literal['self', 'other']
    consent: bool
    createdAt: str


class LockSummary(Model):
    """What anyone signed in to the account may know about a profile's palm lock. Never the template itself."""

    side: HandSide
    createdAt: str
    #: how many photos the lock was made from
    samples: int
    engineVersion: str


class HandProfile(StoredProfile):
    #: 0 and null while the profile is locked: how much it holds is the profile's own business
    readingCount: int
    lastReadingAt: str | None
    #: the palm lock, or null when the profile has none
    lock: LockSummary | None = None
    #: True while the profile has a lock and is not open in this session: its readings and chats cannot be reached
    locked: bool = False
    #: True for the one profile open in this session (the one the website is working in)
    open: bool = False


class NewProfileInput(Model):
    name: str = Field(max_length=200)
    owner: Literal['self', 'other']
    consent: bool = False


class RenameProfileInput(Model):
    name: str = Field(max_length=200)


class PasswordInput(Model):
    """The account password, for what a locked profile needs instead of its palm (taking the lock off, deleting it)."""

    password: str = Field(default='', max_length=1000)


# ------------------------------------------------------------------ palm locks

PalmOutcome = Literal['success', 'failed', 'invalid_image']
AttemptKind = Literal['unlock', 'test', 'lock_added', 'lock_replaced', 'lock_removed', 'profile_deleted']


class StoredLock(Model):
    """What is kept for a palm lock: the sealed template (encrypted, see app/cv/biometric/template.py) and a few plain facts."""

    _omit_when_none = ('lockedUntil',)
    profileId: str
    side: HandSide
    createdAt: str
    samples: int
    engineVersion: str
    configHash: str
    #: the Fernet token: the features of the enrolment photos, encrypted. Never a photo.
    sealed: str
    #: milliseconds since 1970: the profile refuses palm attempts until then (too many failures)
    lockedUntil: int | None = None

    def summary(self) -> LockSummary:
        return LockSummary(side=self.side, createdAt=self.createdAt, samples=self.samples, engineVersion=self.engineVersion)


class Attempt(Model):
    """One line of the attempt log. Every palm attempt is written here, whatever its outcome, and so is every change to a lock.
    It holds numbers and words only: never a photo, never a template."""

    _omit_when_none = ('outcome', 'score', 'threshold', 'methods', 'hand', 'durationMs', 'calibrated', 'via', 'problem')
    #: the attempt ID shown to the person (att_...)
    id: str
    #: the user ID of the brief: the hand profile the attempt was for
    profileId: str
    #: its name at the time, so the line still reads well after the profile is renamed or deleted
    profileName: str
    kind: AttemptKind
    #: when, as an ISO time
    at: str
    outcome: PalmOutcome | None = None
    score: float | None = None
    threshold: float | None = None
    #: each deciding method's normalised score (0 to 1)
    methods: dict[str, float] | None = None
    #: one plain sentence
    reason: str
    #: why the photo could not be judged (a short code), for an invalid image
    problem: str | None = None
    hand: HandSide | None = None
    #: from the photo arriving to the decision
    durationMs: int | None = None
    engineVersion: str
    #: False while the threshold is a placeholder, not yet measured on real photos
    calibrated: bool | None = None
    #: how a lock was taken off or a locked profile deleted: with its palm (it was open) or with the account password
    via: Literal['palm', 'password'] | None = None


UnlockStageKey = Literal['checks', 'roi', 'prep', 'features', 'match']


class UnlockEvent(Model):
    """One step of a palm attempt, as it happens."""

    _omit_when_none = ('detail', 'preview', 'ms')
    stage: UnlockStageKey
    state: StageState
    detail: str | None = None
    #: a small picture of what the step made (a data: URL), for the person's own screen only
    preview: str | None = None
    #: how long the step took
    ms: float | None = None


class PalmResult(Model):
    """The answer to a palm attempt: one of the three outcomes, with everything it was based on."""

    _omit_when_none = ('score', 'problem', 'lockedUntil', 'bestSample')
    attemptId: str
    profileId: str
    outcome: PalmOutcome
    #: "Authentication Successful", "Authentication Failed" or "Invalid Image"
    title: str
    score: float | None = None
    threshold: float
    methods: dict[str, float]
    #: every method's own similarity before normalising, the spare (LBP) included
    raw: dict[str, float]
    reason: str
    problem: str | None = None
    hand: HandSide
    durationMs: int
    at: str
    calibrated: bool
    engineVersion: str
    #: True when this attempt opened the profile (a successful unlock; never a test)
    opened: bool
    bestSample: int | None = None
    #: set when this failure locked the profile out: milliseconds since 1970
    lockedUntil: int | None = None


class PalmMethod(Model):
    id: str
    name: str
    #: how much it counts in the fused score (0 for the spare)
    weight: float
    description: str


class PalmPolicy(Model):
    failures: int
    windowMinutes: int
    lockoutMinutes: int
    idleMinutes: int
    enrolMin: int
    enrolMax: int


class PalmLockInfo(Model):
    """How the palm lock decides, for the Palm lab page. Read-only: the threshold changes only by calibrating."""

    available: bool
    #: why not, when it is not available
    note: str | None
    engineVersion: str
    configHash: str
    calibrated: bool
    threshold: float
    calibrationSource: str
    measured: dict
    methods: list[PalmMethod]
    policy: PalmPolicy
    roiSize: int


class RenameReadingInput(Model):
    """An empty name takes the name away."""

    name: str = Field(max_length=200)


# ------------------------------------------------------------------ chat


class MessageRefs(Model):
    _omit_when_none = ('featureIds', 'side', 'section')
    featureIds: list[FeatureId] | None = None
    side: HandSide | None = None
    section: Literal['heart', 'head', 'life', 'fate', 'sun', 'summary', 'comparison', 'uncertainty', 'themes', 'shape'] | None = None


class MessageFlags(Model):
    _omit_when_none = ('disclaimer', 'boundary', 'switchProfileId')
    disclaimer: bool | None = None
    boundary: BoundaryKind | None = None
    switchProfileId: str | None = None


class Message(Model):
    _omit_when_none = ('refs', 'flags', 'source', 'note')
    id: str
    conversationId: str
    role: Literal['user', 'assistant']
    text: str
    createdAt: str
    refs: MessageRefs | None = None
    flags: MessageFlags | None = None
    #: "gemini": the language model wrote the answer and it passed the checks. "knowledge-base": Gemini was expected to answer and
    #: did not, so the fixed wording answered (see `note`). Left out when the model was never involved: a boundary, a greeting, no key.
    source: Literal['gemini', 'knowledge-base'] | None = None
    #: set when the model was expected to answer and did not (a used-up allowance, a failed check): why, in one sentence
    note: str | None = None


class Conversation(Model):
    id: str
    readingId: str
    profileId: str
    title: str
    createdAt: str
    updatedAt: str
    messageCount: int


class ConversationWithMessages(Conversation):
    messages: list[Message]


class SendMessageInput(Model):
    text: str = Field(max_length=5000)


class MessagePair(Model):
    user: Message
    assistant: Message


# ------------------------------------------------------------------ processing stream


class Previews(Model):
    _omit_when_none = ('left', 'right')
    left: str | None = None
    right: str | None = None


class ProcessingEvent(Model):
    _omit_when_none = ('detail', 'previews')
    stage: StageKey
    state: StageState
    detail: str | None = None
    previews: Previews | None = None


# ------------------------------------------------------------------ accounts and sessions


class UserInfo(Model):
    id: str
    email: str
    displayName: str


class UserSession(Model):
    kind: Literal['user'] = 'user'
    user: UserInfo


class GuestSession(Model):
    kind: Literal['guest'] = 'guest'
    guestId: str
    #: milliseconds since 1 January 1970
    expiresAt: int


Session = Annotated[UserSession | GuestSession, Field(discriminator='kind')]


class RestoreResult(Model):
    _omit_when_none = ('guestExpired',)
    session: Session | None
    guestExpired: bool | None = None


class SignUpInput(Model):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1000)
    displayName: str = Field(max_length=200)


class SignInInput(Model):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1000)


class DataCounts(Model):
    profiles: int
    readings: int
    conversations: int
    messages: int


#: What a delete removed. The same four counts.
DeleteSummary = DataCounts


class ExportBundle(Model):
    exportedAt: str
    profiles: list[HandProfile]
    readings: list[Reading]
    conversations: list[ConversationWithMessages]


class Health(Model):
    _omit_when_none = ('writerModel',)
    ok: bool
    service: str
    version: str
    #: "real" when the hand model is loaded and the lines are found in the photos; "sample" when it is not (every reading is then a labelled stand-in)
    analysis: str
    #: "gemini" when a key is set and the language model writes the reports and the chat; "knowledge-base" when the fixed wording does
    writer: str = 'knowledge-base'
    writerModel: str | None = None
    #: "firestore" when accounts and their data are also kept in the online database; "memory" when they live only until the server stops
    storage: str = 'memory'
