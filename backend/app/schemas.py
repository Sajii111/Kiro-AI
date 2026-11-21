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
    id: str
    profileId: str
    createdAt: str
    hands: Hands
    report: Report
    meta: ReadingMeta


class StatusCounts(Model):
    detected: int
    uncertain: int
    not_visible: int


class ReadingSummary(Model):
    id: str
    profileId: str
    profileName: str
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


class HandProfile(StoredProfile):
    readingCount: int
    lastReadingAt: str | None


class NewProfileInput(Model):
    name: str = Field(max_length=200)
    owner: Literal['self', 'other']
    consent: bool = False


class RenameProfileInput(Model):
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
