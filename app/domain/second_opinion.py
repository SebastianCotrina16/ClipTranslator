from __future__ import annotations

from collections.abc import Callable

from app.domain.coverage import MIN_COVERAGE, Region, covered_fraction
from app.domain.models import Flag, Reading, Segment
from app.domain.quality import HallucinationDetector
from app.domain.text import normalize_for_comparison

DOUBT_FLAGS = frozenset({Flag.KNOWN_PHRASE, Flag.REPETITIVE, Flag.EMPTY, Flag.NO_SPEECH})
MIN_DOUBTFUL_REGION = 1.5


def is_doubtful(segment: Segment, detector: HallucinationDetector) -> bool:
    return bool(DOUBT_FLAGS.intersection(detector.flags_for(segment)))


def doubtful_regions(
    regions: list[Region],
    segments: list[Segment],
    recovered: list[Region],
    detector: HallucinationDetector,
) -> list[Region]:
    def overlaps_recovered(region: Region) -> bool:
        return any(region.start < other.end and region.end > other.start for other in recovered)

    def barely_heard(region: Region) -> bool:
        return (
            region.duration >= MIN_DOUBTFUL_REGION
            and overlaps_recovered(region)
            and covered_fraction(region, segments) < MIN_COVERAGE
        )

    found = [region for region in regions if barely_heard(region)]
    for segment in segments:
        if not is_doubtful(segment, detector):
            continue
        touched = [
            region
            for region in regions
            if region.start < segment.end and region.end > segment.start
        ]
        found.append(
            Region(
                min([segment.start, *(region.start for region in touched)]),
                max([segment.end, *(region.end for region in touched)]),
            )
        )
    return merged(found)


def merged(regions: list[Region]) -> list[Region]:
    result: list[Region] = []
    for region in sorted(regions, key=lambda region: region.start):
        if result and region.start <= result[-1].end:
            result[-1] = Region(result[-1].start, max(result[-1].end, region.end))
        else:
            result.append(region)
    return result


def trusted_by(detector: HallucinationDetector) -> Callable[[Segment], bool]:
    return lambda segment: not is_doubtful(segment, detector)


def combine(segments: list[Segment]) -> Segment:
    ordered = sorted(segments, key=lambda segment: segment.start)
    return Segment(
        id=ordered[0].id,
        start=ordered[0].start,
        end=max(segment.end for segment in ordered),
        text=" ".join(segment.text.strip() for segment in ordered),
        words=[word for segment in ordered for word in segment.words],
        avg_logprob=min(segment.avg_logprob for segment in ordered),
        no_speech_prob=max(segment.no_speech_prob for segment in ordered),
        compression_ratio=max(segment.compression_ratio for segment in ordered),
    )


def settle(
    segments: list[Segment],
    second: list[Segment],
    regions: list[Region],
    sources: tuple[str, str],
    detector: HallucinationDetector,
) -> list[Segment]:
    primary_source, second_source = sources
    result = list(segments)
    for region in regions:
        heard = [segment for segment in second if region.holds(segment)]
        if not heard or any(is_doubtful(segment, detector) for segment in heard):
            continue
        kept = [segment for segment in result if region.holds(segment)]
        other = combine(heard)
        if not kept or any(is_doubtful(segment, detector) for segment in kept):
            other.flags = [Flag.SECOND_MODEL]
            replacement = other
        else:
            replacement = combine(kept)
            if normalize_for_comparison(replacement.text) == normalize_for_comparison(other.text):
                continue
            replacement.flags = [Flag.MODELS_DISAGREE]
            replacement.versions = [
                Reading(primary_source, replacement.text),
                Reading(second_source, other.text),
            ]
        result = [segment for segment in result if not region.holds(segment)] + [replacement]
    result.sort(key=lambda segment: segment.start)
    for position, segment in enumerate(result):
        segment.id = position
    return result
