"""The evaluation of the palm lock (ICA 02): lock with some photos, set the threshold on others, test on the rest.

Each person's photos, in file-name order, are split by position:

    enrolment   the first 3   lock the palm (what the website does with the three photos it asks for)
    validation  the next 2    set the threshold, and nothing else
    test        the rest      the only photos the reported numbers come from

No photo takes part in two of these roles, and the test photos are not looked at until the threshold is fixed.

An attempt is one photo tried against one lock, exactly as the website does it (`engine.verify`). A photo of the lock's
owner is a genuine attempt, a photo of anybody else an impostor attempt. The outcome is Authentication Successful (the
score reached the threshold), Authentication Failed, or Invalid Image (the photo could not be judged). An Invalid Image is
neither an acceptance nor a rejection, so it is counted apart and kept out of FAR and FRR.

    FAR       impostor attempts accepted / impostor attempts scored
    FRR       genuine attempts rejected / genuine attempts scored
    accuracy  correct decisions / scored attempts (with the balance of the test: it is mostly impostor attempts)

A rate whose denominator is zero is "not measurable", never 0%. Nothing here reads or writes a photo or a template: the
caller hands over the photos' features, and what comes out is numbers and pseudonymous labels.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import numpy as np

from .config import DEFAULT, ENGINE_VERSION, EngineSettings, config_hash
from .engine import EnrolProblem, Extraction, Problem, enrol, score_matrix, verify
from .evaluate import PairScores, eer_threshold, fit_normalisers, rates
from .match import Calibration, raw_scores

STAGES = ('roi', 'prep', 'crease', 'compcode', 'lbp')
METHOD_NAMES = {'crease': 'A: crease map', 'compcode': 'B: competitive code', 'lbp': 'LBP texture (spare)', 'fusion': 'A + B fused'}


class EvaluationError(ValueError):
    """The photos cannot be evaluated yet. The message says what to add."""


def natural_key(name: str) -> list:
    """Sorts 2.jpg before 10.jpg."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', name)]


# ------------------------------------------------------------------ the photos


@dataclass(frozen=True)
class Split:
    enrol: int = 3
    validate: int = 2

    def roles(self, count: int) -> list[str]:
        """The role of each of a person's `count` photos, in file-name order."""
        return ['enrol' if k < self.enrol else 'validate' if k < self.enrol + self.validate else 'test' for k in range(count)]


@dataclass(frozen=True)
class Shot:
    """One photo after the checks and the feature extraction: its owner (a pseudonym), its label, its role, what came out,
    and how long the checks and the extraction took."""

    person: str
    label: str
    role: str
    side: str
    result: Extraction | Problem
    #: milliseconds from the photo's bytes to its features: decoding, quality checks, hand finding, the palm steps
    ms: float


# ------------------------------------------------------------------ rates


@dataclass(frozen=True)
class Rate:
    hits: int
    total: int

    @property
    def value(self) -> float | None:
        return self.hits / self.total if self.total else None

    def interval(self, z: float = 1.96) -> tuple[float, float] | None:
        """The 95% Wilson interval: how far from the measured rate the true one could be with this many trials."""
        if not self.total:
            return None
        n, p = self.total, self.hits / self.total
        denominator = 1 + z * z / n
        centre = (p + z * z / (2 * n)) / denominator
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
        return max(0.0, centre - half), min(1.0, centre + half)

    def text(self) -> str:
        if not self.total:
            return 'not measurable'
        return f'{self.value:.1%} ({self.hits} of {self.total})'

    def short(self) -> str:
        if not self.total:
            return 'not measurable'
        return f'{self.value:.1%} ({self.hits}/{self.total})'


@dataclass(frozen=True)
class Confusion:
    genuine_accepted: int = 0
    genuine_rejected: int = 0
    impostor_accepted: int = 0
    impostor_rejected: int = 0

    @property
    def genuine(self) -> int:
        return self.genuine_accepted + self.genuine_rejected

    @property
    def impostor(self) -> int:
        return self.impostor_accepted + self.impostor_rejected

    @property
    def total(self) -> int:
        return self.genuine + self.impostor

    @property
    def far(self) -> Rate:
        return Rate(self.impostor_accepted, self.impostor)

    @property
    def frr(self) -> Rate:
        return Rate(self.genuine_rejected, self.genuine)

    @property
    def accuracy(self) -> Rate:
        return Rate(self.genuine_accepted + self.impostor_rejected, self.total)

    @property
    def balanced_accuracy(self) -> float | None:
        far, frr = self.far.value, self.frr.value
        return None if far is None or frr is None else ((1 - far) + (1 - frr)) / 2

    @property
    def same_answer_accuracy(self) -> Rate:
        """What a lock that gave everybody the same answer would score on these attempts."""
        return Rate(max(self.genuine, self.impostor), self.total)


def confusion_at(genuine: np.ndarray, impostor: np.ndarray, threshold: float) -> Confusion:
    g, i = np.asarray(genuine, float), np.asarray(impostor, float)
    accepted_g = int((g >= threshold).sum())
    accepted_i = int((i >= threshold).sum())
    return Confusion(accepted_g, len(g) - accepted_g, accepted_i, len(i) - accepted_i)


def d_prime(genuine: np.ndarray, impostor: np.ndarray) -> float | None:
    """How far apart the two kinds of score are, in standard deviations (None without both kinds)."""
    if not len(genuine) or not len(impostor):
        return None
    spread = math.sqrt((float(np.var(genuine)) + float(np.var(impostor))) / 2)
    if spread < 1e-9:
        return None
    return (float(np.mean(genuine)) - float(np.mean(impostor))) / spread


def roc_curve(genuine: np.ndarray, impostor: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(FAR, FRR) at every threshold that changes an answer, from accept-everything to refuse-everything."""
    g, i = np.asarray(genuine, float), np.asarray(impostor, float)
    cuts = np.unique(np.concatenate([g, i, [-1.0, 2.0]]))
    far = np.array([(i >= t).mean() if len(i) else 0.0 for t in cuts])
    frr = np.array([(g < t).mean() if len(g) else 0.0 for t in cuts])
    return far, frr


# ------------------------------------------------------------------ trials


@dataclass(frozen=True)
class Trial:
    """One photo against one lock: its raw scores against each enrolment photo (the lock keeps the best)."""

    person: str
    photo: str
    lock: str
    genuine: bool
    samples: tuple[dict[str, float], ...]


Scorer = Callable[[dict[str, float]], float]


def best_score(trial: Trial, scorer: Scorer) -> float:
    return max(scorer(r) for r in trial.samples)


def scores_of(trials: Sequence[Trial], scorer: Scorer) -> tuple[np.ndarray, np.ndarray]:
    """(genuine scores, impostor scores) of the trials under one way of scoring."""
    genuine = np.array([best_score(t, scorer) for t in trials if t.genuine], float)
    impostor = np.array([best_score(t, scorer) for t in trials if not t.genuine], float)
    return genuine, impostor


def make_trials(probes: Sequence[Shot], gallery: Mapping[str, list[Extraction]], settings: EngineSettings = DEFAULT) -> list[Trial]:
    """Every usable photo against every lock of the same hand (a photo of the other hand is Invalid Image, not an attempt)."""
    out: list[Trial] = []
    for shot in probes:
        if not isinstance(shot.result, Extraction):
            continue
        for lock, samples in gallery.items():
            if samples[0].side != shot.side:
                continue
            raws = tuple(raw_scores(shot.result.features, s.features, settings) for s in samples)
            out.append(Trial(shot.person, shot.label, lock, shot.person == lock, raws))
    return out


def fit_calibration(trials: Sequence[Trial], settings: EngineSettings, source: str, calibrated: bool) -> Calibration:
    """Normalisers and threshold from the validation trials, and from nothing else."""
    genuine = [r for t in trials if t.genuine for r in t.samples]
    impostor = [r for t in trials if not t.genuine for r in t.samples]
    n_g, n_i = sum(1 for t in trials if t.genuine), sum(1 for t in trials if not t.genuine)
    if not n_g or not n_i:
        raise EvaluationError(
            f'The validation photos give {n_g} same-person and {n_i} different-person trials. Setting a threshold needs at least one of each: '
            'every person needs a validation photo that can be used, and at least two people need a lock.'
        )
    normalisers = fit_normalisers(PairScores(genuine=genuine, impostor=impostor, labels=[]), ('crease', 'compcode', 'lbp'))
    weights = dict(zip(settings.match.methods, settings.match.weights, strict=True))
    draft = Calibration(
        calibrated=calibrated,
        threshold=0.5,
        normalisers=normalisers,
        weights=weights,
        source=source,
        engine_version=ENGINE_VERSION,
        config_hash=config_hash(settings),
    )
    g, i = scores_of(trials, draft.fuse)
    threshold, eer = eer_threshold(g, i)
    far, frr = rates(g, i, threshold)
    measured = {
        'date': datetime.now(UTC).date().isoformat(),
        'people': len({t.lock for t in trials}),
        'photos': len({(t.person, t.photo) for t in trials}),
        'genuine_pairs': n_g,
        'impostor_pairs': n_i,
        'eer': round(eer, 4),
        'far': round(far, 4),
        'frr': round(frr, 4),
        'genuine_mean': round(float(g.mean()), 4),
        'impostor_mean': round(float(i.mean()), 4),
        'note': 'validation photos tried against the locks made from the enrolment photos; the test photos were not used',
    }
    return replace(draft, threshold=round(threshold, 4), measured=measured)


# ------------------------------------------------------------------ the evaluation


@dataclass(frozen=True)
class PersonRow:
    person: str
    photos: int
    usable: int
    enrol: int
    validate: int
    test: int
    #: the codes of the photos that were Invalid Image
    invalid: tuple[str, ...]
    locked: bool
    why_not: str = ''


@dataclass(frozen=True)
class Attempt:
    person: str
    photo: str
    lock: str
    genuine: bool
    outcome: str
    score: float | None
    methods: dict[str, float]
    #: milliseconds, photo bytes to outcome: the checks and the features of the photo, then the comparison with the lock
    ms: float
    verify_ms: float
    reason: str


@dataclass(frozen=True)
class Variant:
    """One way of scoring (a method alone, or the fusion), with its own threshold set on the validation photos."""

    key: str
    name: str
    role: str
    threshold: float
    validation_eer: float
    test: Confusion
    #: the equal error rate of the test scores themselves: no threshold involved, so it is optimistic as a prediction
    test_eer: float | None
    d_prime: float | None


@dataclass
class Evaluation:
    date: str
    settings_hash: str
    split: Split
    people: list[PersonRow]
    calibration: Calibration
    validation_genuine: int
    validation_impostor: int
    attempts: list[Attempt]
    #: the scored attempts as the lock decided them
    confusion: Confusion
    invalid: Counter
    variants: list[Variant]
    sweep: list[tuple[float, Confusion]]
    #: fused test scores (genuine, impostor), for the curves
    fused: tuple[np.ndarray, np.ndarray]
    stage_ms: dict[str, float]
    notes: list[str] = field(default_factory=list)

    @property
    def fusion(self) -> Variant:
        return next(v for v in self.variants if v.key == 'fusion')

    def attempts_of(self, genuine: bool) -> list[Attempt]:
        return [a for a in self.attempts if a.genuine == genuine]

    def mean_ms(self, genuine: bool | None = None) -> float | None:
        pool = self.attempts if genuine is None else self.attempts_of(genuine)
        return float(np.mean([a.ms for a in pool])) if pool else None


DEFAULT_SPLIT = Split()


def weakest_agreement(photos: Sequence[Extraction], cal: Calibration, settings: EngineSettings) -> float:
    """The lowest, over a person's enrolment photos, of the mean score of that photo against the others (what `enrol` checks)."""
    scores = score_matrix([p.features for p in photos], cal, settings)
    n = len(photos)
    return float(((scores.sum(axis=1) - 1.0) / (n - 1)).min())


def evaluate(shots: Sequence[Shot], settings: EngineSettings = DEFAULT, split: Split = DEFAULT_SPLIT, clock: Callable[[], float] = time.perf_counter) -> Evaluation:
    need, most = settings.match.enrol_min, settings.match.enrol_max
    if not need <= split.enrol <= most:
        raise EvaluationError(f'A lock is made from {need} to {most} photos, so --enrol must be between {need} and {most}.')
    if split.validate < 1:
        raise EvaluationError('The threshold needs at least one validation photo per person.')

    people = list(dict.fromkeys(s.person for s in shots))
    usable = [s for s in shots if isinstance(s.result, Extraction)]

    # who can have a lock: three usable enrolment photos of one hand
    gallery: dict[str, list[Extraction]] = {}
    why_not: dict[str, str] = {}
    for person in people:
        mine = [s.result for s in usable if s.person == person and s.role == 'enrol']
        if len(mine) < need:
            why_not[person] = f'only {len(mine)} of the enrolment photos could be used (a lock needs {need})'
        else:
            gallery[person] = mine  # type: ignore[assignment]
    if len(gallery) < 2:
        raise EvaluationError('At least two people need a lock (three usable enrolment photos each), or there are no different-person attempts to measure.')

    # the threshold: validation photos against the locks, and only those. A lock the consistency check refuses is dropped and
    # the threshold is set again without it, until the people who have a lock stay the same
    validation = [s for s in usable if s.role == 'validate']
    all_validation = make_trials(validation, gallery, settings)
    locked = dict(gallery)
    while True:
        trials = [t for t in all_validation if t.lock in locked]
        source = f'class dataset: {len(locked)} people, validation photos only'
        calibrated = len(locked) >= 5
        if not calibrated:
            source += ' (a placeholder until 5 or more people are measured)'
        cal = fit_calibration(trials, settings, source, calibrated)
        templates, refused = {}, {}
        for person, photos in locked.items():
            made = enrol(photos, photos[0].side, cal, settings)
            if isinstance(made, EnrolProblem):
                refused[person] = made.message
            else:
                templates[person] = made
        if not refused:
            break
        # one bad lock drags the threshold with it (its owner's validation photos score like a stranger's), which can make the
        # others look inconsistent too: so only the lock whose enrolment photos agree least is dropped before the threshold is set again
        worst = min(refused, key=lambda person: weakest_agreement(locked[person], cal, settings))
        why_not[worst] = f'the lock was not made: {refused[worst]}'
        del locked[worst]
        if len(locked) < 2:
            raise EvaluationError('Fewer than two locks could be made: the enrolment photos of the others do not match each other. ' + ' '.join(why_not.values()))
    n_genuine = sum(1 for t in trials if t.genuine)

    # the test: every test photo against every lock, as the website would answer it
    attempts: list[Attempt] = []
    tests = [s for s in shots if s.role == 'test']
    for shot in tests:
        for lock, template in templates.items():
            if shot.side != template.side:
                continue
            t0 = clock()
            decision = verify(template, shot.result, cal, settings)
            verify_ms = (clock() - t0) * 1000
            attempts.append(
                Attempt(
                    person=shot.person,
                    photo=shot.label,
                    lock=lock,
                    genuine=shot.person == lock,
                    outcome=decision.outcome,
                    score=decision.score,
                    methods=dict(decision.methods),
                    ms=round(shot.ms + verify_ms, 1),
                    verify_ms=round(verify_ms, 1),
                    reason=decision.reason,
                )
            )
    scored = [a for a in attempts if a.outcome in ('success', 'failed')]
    confusion = Confusion(
        genuine_accepted=sum(a.genuine and a.outcome == 'success' for a in scored),
        genuine_rejected=sum(a.genuine and a.outcome == 'failed' for a in scored),
        impostor_accepted=sum((not a.genuine) and a.outcome == 'success' for a in scored),
        impostor_rejected=sum((not a.genuine) and a.outcome == 'failed' for a in scored),
    )
    invalid = Counter()
    for shot in tests:
        if isinstance(shot.result, Problem):
            invalid[shot.result.code] += sum(1 for t in templates.values() if shot.side == t.side)

    # the same attempts scored by each method alone and fused, each with its own threshold from the validation photos
    test_trials = make_trials([s for s in tests if isinstance(s.result, Extraction)], locked, settings)
    approaches: list[tuple[str, str, Scorer]] = [(m, 'decides' if m in cal.weights else 'spare', (lambda r, m=m: r[m])) for m in ('crease', 'compcode', 'lbp')]
    approaches.append(('fusion', 'decides', cal.fuse))
    variants: list[Variant] = []
    for key, role, scorer in approaches:
        vg, vi = scores_of(trials, scorer)
        threshold, validation_eer = eer_threshold(vg, vi)
        threshold = cal.threshold if key == 'fusion' else round(threshold, 4)
        tg, ti = scores_of(test_trials, scorer)
        variants.append(
            Variant(
                key=key,
                name=METHOD_NAMES[key],
                role=role,
                threshold=threshold,
                validation_eer=validation_eer,
                test=confusion_at(tg, ti, threshold),
                test_eer=eer_threshold(tg, ti)[1] if len(tg) and len(ti) else None,
                d_prime=d_prime(tg, ti),
            )
        )
    fg, fi = scores_of(test_trials, cal.fuse)
    cuts = sorted({*(round(float(t), 2) for t in np.arange(0.1, 0.91, 0.05)), cal.threshold})
    sweep = [(t, confusion_at(fg, fi, t)) for t in cuts]

    measured = [s for s in tests if isinstance(s.result, Extraction)]
    stage_ms = {stage: float(np.mean([s.result.timings.get(stage, 0.0) for s in measured])) for stage in STAGES} if measured else {}  # type: ignore[union-attr]
    if measured:
        stage_ms['checks'] = float(np.mean([max(0.0, s.ms - sum(s.result.timings.values())) for s in measured]))  # type: ignore[union-attr]

    rows = []
    for person in people:
        mine = [s for s in shots if s.person == person]
        ok = [s for s in mine if isinstance(s.result, Extraction)]
        rows.append(
            PersonRow(
                person=person,
                photos=len(mine),
                usable=len(ok),
                enrol=sum(s.role == 'enrol' for s in ok),
                validate=sum(s.role == 'validate' for s in ok),
                test=sum(s.role == 'test' for s in ok),
                invalid=tuple(s.result.code for s in mine if isinstance(s.result, Problem)),
                locked=person in templates,
                why_not=why_not.get(person, ''),
            )
        )
    ev = Evaluation(
        date=datetime.now(UTC).date().isoformat(),
        settings_hash=config_hash(settings),
        split=split,
        people=rows,
        calibration=cal,
        validation_genuine=n_genuine,
        validation_impostor=len(trials) - n_genuine,
        attempts=attempts,
        confusion=confusion,
        invalid=invalid,
        variants=variants,
        sweep=sweep,
        fused=(fg, fi),
        stage_ms=stage_ms,
    )
    ev.notes = limits(ev)
    return ev


def limits(ev: Evaluation) -> list[str]:
    """What the numbers cannot say, worked out from this run's own counts."""
    c = ev.confusion
    notes = []
    if c.genuine:
        notes.append(f'There were {c.genuine} same-person attempts to score, so one wrong answer moves FRR by {100 / c.genuine:.1f} points.')
    if c.impostor:
        locks = sum(p.locked for p in ev.people)
        notes.append(
            f'The {c.impostor} different-person attempts are {locks} locks tried with the same few photos, so they are not independent trials: '
            'the intervals above are narrower than the real uncertainty.'
        )
    notes.append('The people tried as impostors are the other people in the dataset, not strangers, and all photos come from one class: a small dataset supports proof-of-concept conclusions only.')
    notes.append('The threshold was set on the validation photos of the same people who are tested, which is how a lock is used, but it says little about people who are not in the dataset.')
    if len(ev.people) < 10:
        notes.append(f'Only {len(ev.people)} people took part. The brief suggests about 10.')
    return notes


# ------------------------------------------------------------------ the written report


def pct(value: float | None) -> str:
    return 'not measurable' if value is None else f'{value:.1%}'


def span(rate: Rate) -> str:
    box = rate.interval()
    return '' if box is None else f'   95% interval {box[0]:.1%} to {box[1]:.1%}'


def report_lines(ev: Evaluation) -> list[str]:
    cal, c, split = ev.calibration, ev.confusion, ev.split
    out: list[str] = []
    add = out.append
    people = ev.people
    photos = sum(p.photos for p in people)
    usable = sum(p.usable for p in people)
    add('Palm lock evaluation')
    add('====================')
    add(f'Engine {ENGINE_VERSION} (settings {ev.settings_hash}), measured {ev.date}.')
    add('Score convention: a similarity from 0 to 1; a photo is accepted when its score is at or above the threshold.')
    add('')
    add('1. The photos and how they were split')
    add('-------------------------------------')
    add(f'{len(people)} people, {photos} photos, {usable} usable and {photos - usable} Invalid Image.')
    first_validation, first_test = split.enrol + 1, split.enrol + split.validate + 1
    add(f'Per person, in file-name order: photos 1-{split.enrol} made the lock (enrolment), photos {first_validation}-{first_test - 1} set the threshold (validation),')
    add(f'photos {first_test} onwards were the test. No photo has more than one role.')
    add('')
    add(f'  {"person":12s} {"photos":>6s} {"usable":>6s} {"enrol":>6s} {"validation":>10s} {"test":>5s}   lock')
    for p in people:
        lock = 'made' if p.locked else f'not made: {p.why_not}'
        add(f'  {p.person:12s} {p.photos:6d} {p.usable:6d} {p.enrol:6d} {p.validate:10d} {p.test:5d}   {lock}')
        if p.invalid:
            add(f'  {"":12s} Invalid Image: {", ".join(f"{k} x{v}" for k, v in sorted(Counter(p.invalid).items()))}')
    add('')
    add('2. The threshold, set on the validation photos only')
    add('---------------------------------------------------')
    add(f'Validation attempts: {ev.validation_genuine} same-person and {ev.validation_impostor} different-person (each validation photo against each lock).')
    for m, n in cal.normalisers.items():
        role = 'decides' if m in cal.weights else 'spare, not used'
        add(f'  {METHOD_NAMES[m]:22s} {role:16s} a typical different-person score ({n.impostor:.3f}) counts as 0, a typical same-person score ({n.genuine:.3f}) as 1')
    add('  fusion: ' + ' + '.join(f'{w:g} x {METHOD_NAMES[m]}' for m, w in cal.weights.items()) + ', each normalised, then averaged')
    add(f'Threshold {cal.threshold:.4f}: the fused score where FAR and FRR were equal on the validation attempts (EER {pct(cal.measured.get("eer"))}).')
    add(f'It is {"calibrated" if cal.calibrated else "not yet calibrated: fewer than 5 people were measured"}; it lives in the backend and the website shows it read-only.')
    add('')
    add('3. Results on the test photos (not used for the threshold)')
    add('----------------------------------------------------------')
    all_g, all_i = ev.attempts_of(True), ev.attempts_of(False)
    bad_g = sum(a.outcome == 'invalid_image' for a in all_g)
    bad_i = sum(a.outcome == 'invalid_image' for a in all_i)
    add(f'Attempts: {len(all_g)} same-person (genuine), {len(all_i)} different-person (impostor).')
    add(f'Invalid Image: {bad_g} genuine, {bad_i} impostor. These got no score, so they are not in FAR, FRR or accuracy.')
    if bad_g or bad_i:
        add('  ' + ', '.join(f'{k}: {v}' for k, v in sorted(ev.invalid.items())) + ' (attempts)')
    add(f'Scored attempts: {c.genuine} genuine, {c.impostor} impostor, threshold {cal.threshold:.4f}.')
    add('')
    add('  Confusion matrix (scored attempts)       accepted   rejected')
    add(f'  same palm (genuine)                      {c.genuine_accepted:8d}   {c.genuine_rejected:8d}')
    add(f'  another palm (impostor)                  {c.impostor_accepted:8d}   {c.impostor_rejected:8d}')
    add('')
    add(f'  FAR  {c.far.text()}{span(c.far)}')
    add(f'  FRR  {c.frr.text()}{span(c.frr)}')
    add(f'  Accuracy  {c.accuracy.text()}{span(c.accuracy)}')
    if c.total:
        share = c.genuine / c.total
        add(f'  Test balance: {c.genuine} genuine : {c.impostor} impostor ({share:.0%} genuine). A lock that gave everybody the same answer would score {c.same_answer_accuracy.text()},')
        add(f'  so read accuracy with the balance. Balanced accuracy (the mean of 1-FAR and 1-FRR): {pct(c.balanced_accuracy)}.')
    else:
        add('  Test balance: no scored attempts.')
    mean_all, mean_g, mean_i = ev.mean_ms(), ev.mean_ms(True), ev.mean_ms(False)
    if mean_all is None:
        add('  Mean latency: not measurable (no attempts).')
    else:
        kinds = ''.join(f', {name} {value:.0f} ms' for name, value in (('genuine', mean_g), ('impostor', mean_i)) if value is not None)
        add(f'  Mean latency: {mean_all:.0f} ms per attempt, from the photo to the outcome ({kinds[2:]}).')
        if ev.stage_ms:
            parts = ', '.join(f'{k} {v:.0f}' for k, v in ev.stage_ms.items())
            add(f'  One photo, by stage (ms): {parts}. "checks" is decoding, the quality checks and finding the hand.')
        add('  Timed on this computer, one attempt after another, without the network.')
    add('')
    add('4. Each method alone and fused (ablation)')
    add('-----------------------------------------')
    add('Each row has its own threshold, set at its own equal error rate on the validation photos. "test EER" is the equal error rate of the test scores')
    add('themselves, so it needs no threshold, but it is the best case.')
    add('')
    add(f'  {"approach":24s} {"threshold":>9s}  {"FAR":>22s}  {"FRR":>22s}  {"accuracy":>22s}  {"test EER":>8s}  {"d-prime":>7s}')
    for v in ev.variants:
        dp = 'n/a' if v.d_prime is None else f'{v.d_prime:.2f}'
        add(f'  {v.name:24s} {v.threshold:9.4f}  {v.test.far.short():>22s}  {v.test.frr.short():>22s}  {v.test.accuracy.short():>22s}  {pct(v.test_eer):>8s}  {dp:>7s}')
    add('')
    add('5. The threshold moved (fusion, test photos)')
    add('--------------------------------------------')
    add(f'  {"threshold":>9s}  {"FAR":>22s}  {"FRR":>22s}')
    for t, row in ev.sweep:
        mark = '   <- the threshold in use' if abs(t - cal.threshold) < 1e-9 else ''
        add(f'  {t:9.4f}  {row.far.short():>22s}  {row.frr.short():>22s}{mark}')
    add('')
    add('6. Where it went wrong, or nearly')
    add('---------------------------------')
    scored = [a for a in ev.attempts if a.score is not None]
    low = sorted((a for a in scored if a.genuine), key=lambda a: a.score)[:3]  # type: ignore[arg-type,return-value]
    high = sorted((a for a in scored if not a.genuine), key=lambda a: -a.score)[:3]  # type: ignore[operator]

    def line(a: Attempt) -> str:
        parts = ', '.join(f'{METHOD_NAMES[k][:1]} {v:.2f}' for k, v in a.methods.items())
        return f'  {a.photo:18s} on the lock of {a.lock:10s} score {a.score:.3f}  ({parts})  {a.outcome}'

    add('Lowest same-person scores (A = crease map, B = competitive code, each normalised to 0-1 as in section 2):')
    out.extend(line(a) for a in low) if low else out.append('  none')
    add('Highest different-person scores:')
    out.extend(line(a) for a in high) if high else out.append('  none')
    add('')
    add('7. What these numbers can and cannot say')
    add('-----------------------------------------')
    out.extend(f'  - {n}' for n in ev.notes)
    return out


def attempts_csv(ev: Evaluation) -> str:
    """One row per test attempt: pseudonymous labels and numbers, never a photo."""
    rows = ['attempt,photo_of,photo,lock,kind,outcome,score,crease,compcode,ms']
    for k, a in enumerate(ev.attempts, start=1):
        cells = [
            str(k),
            a.person,
            a.photo,
            a.lock,
            'genuine' if a.genuine else 'impostor',
            a.outcome,
            '' if a.score is None else f'{a.score:.4f}',
            f'{a.methods["crease"]:.4f}' if 'crease' in a.methods else '',
            f'{a.methods["compcode"]:.4f}' if 'compcode' in a.methods else '',
            str(a.ms),
        ]
        rows.append(','.join(cells))
    return '\n'.join(rows) + '\n'
