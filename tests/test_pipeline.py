"""Offline checks for the parts that do not need an API key.

Builds a real audio file with ffmpeg so the silence detection and chunk
planning are exercised against actual audio rather than fixtures.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import audio as A  # noqa: E402
from app import formats  # noqa: E402
from app.engines.base import Segment, Transcript, Word  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        failures.append(label)


async def build_test_audio(path: Path) -> float:
    """Six 20 s tones separated by 3 s of silence: 8 predictable gaps."""
    parts = []
    for i in range(6):
        freq = 300 + i * 90
        parts.append(f"sine=frequency={freq}:duration=20")
        if i < 5:
            parts.append("anullsrc=r=44100:cl=mono,atrim=duration=3")

    inputs: list[str] = []
    for part in parts:
        inputs += ["-f", "lavfi", "-i", part]
    filters = "".join(f"[{i}:a]" for i in range(len(parts)))
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-y", *inputs,
        "-filter_complex", f"{filters}concat=n={len(parts)}:v=0:a=1[out]",
        "-map", "[out]", "-ar", "16000", "-ac", "1", "-c:a", "flac", str(path),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    info = await A.probe(path)
    return float(info["duration"])


async def test_audio() -> None:
    print("\naudio: probe / silence detection / chunk planning")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        source = tmpdir / "source.flac"
        duration = await build_test_audio(source)
        # 6*20 tones + 5*3 silences = 135 s
        check("probe reports the real duration", 130 < duration < 140, f"got {duration:.1f}s")

        silences = await A.detect_silences(source)
        check("finds the 5 inserted gaps", len(silences) == 5, f"got {len(silences)}")

        chunks = A.plan_chunks(duration, silences, target_seconds=45.0, overlap=2.0)
        check("splits into multiple chunks", len(chunks) >= 2, f"got {len(chunks)}")
        check(
            "chunk spans tile the timeline with no gap or overlap",
            chunks[0].start == 0.0
            and abs(chunks[-1].end - duration) < 0.01
            and all(
                abs(chunks[i].end - chunks[i + 1].start) < 1e-6 for i in range(len(chunks) - 1)
            ),
        )
        # Every interior boundary should have landed inside one of the gaps.
        on_silence = [
            any(s <= chunk.end <= e for s, e in silences) for chunk in chunks[:-1]
        ]
        check("every boundary lands inside a silence", all(on_silence), f"{on_silence}")
        check(
            "cuts are padded by the overlap",
            all(c.cut_start <= c.start and c.cut_end >= c.end for c in chunks)
            and chunks[1].cut_start < chunks[1].start,
        )

        # A cut chunk must be real, playable audio of about the right length.
        chunk = chunks[1]
        out = tmpdir / "chunk.flac"
        await A.cut_chunk(source, chunk, out)
        cut_info = await A.probe(out)
        check(
            "cut chunk has the planned duration",
            abs(float(cut_info["duration"]) - chunk.cut_duration) < 0.5,
            f"want {chunk.cut_duration:.1f}s got {cut_info['duration']}",
        )

        # Short audio should never be split.
        single = A.plan_chunks(30.0, [], target_seconds=600.0, overlap=2.0)
        check("short audio stays as one chunk", len(single) == 1)


def test_stitch() -> None:
    print("\nstitch: overlap de-duplication and timeline offsets")
    # Two chunks; chunk 1 is cut 2 s early, so its first segment is a
    # duplicate of the tail of chunk 0 and must be dropped.
    c0 = A.Chunk(0, 0.0, 60.0, 0.0, 62.0)
    c1 = A.Chunk(1, 60.0, 120.0, 58.0, 120.0)

    t0 = Transcript(
        text="",
        segments=[
            Segment(0.0, 30.0, "first half"),
            Segment(30.0, 59.0, "end of chunk zero"),
            Segment(59.0, 62.0, "spills past the boundary"),  # midpoint 60.5 -> chunk 1
        ],
    )
    t1 = Transcript(
        text="",
        segments=[
            Segment(0.0, 3.0, "spills past the boundary"),   # abs 58-61, mid 59.5 -> chunk 0
            Segment(3.0, 40.0, "second half", words=[Word(3.0, 4.0, "second")]),
        ],
    )

    text, segments = A.stitch([(c1, t1), (c0, t0)])  # deliberately out of order

    check("segments come back in time order", [s.start for s in segments]
          == sorted(s.start for s in segments))
    check("the overlapping line appears exactly once",
          text.count("spills past the boundary") == 1, text)
    check("later chunk timestamps are offset onto the global timeline",
          any(abs(s.start - 61.0) < 1e-6 for s in segments),
          str([round(s.start, 2) for s in segments]))
    check("word timings are offset too",
          any(w.start == 61.0 for s in segments for w in s.words))
    check("nothing is lost", "first half" in text and "second half" in text)


def test_size_targeting() -> None:
    print("\nchunk sizing: derived from the file's own bitrate")
    # 1 hour, 60 MB -> 16.6 kB/s. A 24 MB cap fits ~1440 s, under the 600 s ceiling.
    target = A.target_seconds_for_size(3600, 60_000_000, 24_000_000, 600.0)
    check("ceiling wins when the cap is generous", target == 600.0, f"got {target}")

    # A dense file: 1 hour at 200 MB -> the cap binds well below the ceiling.
    target = A.target_seconds_for_size(3600, 200_000_000, 24_000_000, 600.0)
    check("cap wins when the file is dense", 350 < target < 420, f"got {target:.0f}")
    check("never returns a nonsensical target",
          A.target_seconds_for_size(0, 0, 24_000_000, 600.0) == 600.0)


def test_formats() -> None:
    print("\nformats: txt / srt / vtt")
    segments = [
        Segment(0.0, 2.5, "Hello there.", speaker="Speaker 1"),
        Segment(2.5, 4.0, "How are you?", speaker="Speaker 1"),
        Segment(4.25, 7.75, "Doing well.", speaker="Speaker 2"),
    ]

    text = formats.to_text(segments)
    check("consecutive turns by one speaker merge into a single line",
          text.count("Speaker 1:") == 1, text)
    check("the speaker change starts a new line", "Speaker 2: Doing well." in text, text)

    srt = formats.to_srt(segments)
    check("srt numbers cues from 1", srt.startswith("1\n"))
    check("srt uses comma milliseconds", "00:00:00,000 --> 00:00:02,500" in srt, srt[:80])
    check("srt fractional seconds are exact", "00:00:04,250 --> 00:00:07,750" in srt)

    vtt = formats.to_vtt(segments)
    check("vtt has the required header", vtt.startswith("WEBVTT"))
    check("vtt uses dot milliseconds and voice spans",
          "00:00:04.250 --> 00:00:07.750" in vtt and "<v Speaker 2>" in vtt)

    plain = formats.to_text([Segment(0.0, 1.0, "no speakers here")])
    check("undiarized text has no speaker prefix", plain == "no speakers here", plain)

    check("an hour-plus timestamp renders correctly",
          formats.to_srt([Segment(3661.5, 3662.0, "x")]).count("01:01:01,500") == 1)


def test_stitch_boundary_skew() -> None:
    """The cases that make a naive time-partition lose or duplicate speech.

    Whisper re-times the overlap differently in each chunk, so the two copies
    of one utterance can disagree by seconds in either direction.
    """
    print("\nstitch: boundary skew and truncation")
    c0 = A.Chunk(0, 0.0, 60.0, 0.0, 62.0)
    c1 = A.Chunk(1, 60.0, 120.0, 58.0, 120.0)

    # Skewed the other way: chunk 0 times it late, chunk 1 times it early.
    t0 = Transcript(text="", segments=[
        Segment(0.0, 58.0, "before"),
        Segment(58.0, 62.0, "straddles the cut"),
    ])
    t1 = Transcript(text="", segments=[
        Segment(0.0, 3.5, "straddles the cut"),
        Segment(3.5, 30.0, "after"),
    ])
    text, _ = A.stitch([(c0, t0), (c1, t1)])
    check("mirrored skew keeps the utterance exactly once",
          text.count("straddles the cut") == 1, text)
    check("mirrored skew loses nothing", "before" in text and "after" in text, text)

    # Chunk 0 ran out of audio mid-sentence; chunk 1 heard the whole thing.
    t0 = Transcript(text="", segments=[
        Segment(0.0, 58.0, "before"),
        Segment(58.0, 62.0, "the quick brown"),
    ])
    t1 = Transcript(text="", segments=[
        Segment(0.0, 5.0, "the quick brown fox jumps"),
        Segment(5.0, 30.0, "after"),
    ])
    text, _ = A.stitch([(c0, t0), (c1, t1)])
    check("the complete version wins over the truncated one",
          "the quick brown fox jumps" in text, text)
    check("the truncated version is not left behind as well",
          text.count("the quick brown") == 1, text)

    # Punctuation and casing differ across the seam but it is the same speech.
    t0 = Transcript(text="", segments=[Segment(55.0, 62.0, "So, what do you think?")])
    t1 = Transcript(text="", segments=[
        Segment(0.0, 4.0, "so what do you think"),
        Segment(4.0, 20.0, "Good question."),
    ])
    text, _ = A.stitch([(c0, t0), (c1, t1)])
    check("repunctuated duplicates are still recognised as one utterance",
          text.lower().count("what do you think") == 1, text)

    # Three chunks: dedup has to hold at every seam.
    chunks = [
        A.Chunk(0, 0.0, 60.0, 0.0, 62.0),
        A.Chunk(1, 60.0, 120.0, 58.0, 122.0),
        A.Chunk(2, 120.0, 180.0, 118.0, 180.0),
    ]
    transcripts = [
        Transcript(text="", segments=[Segment(0.0, 58.0, "one"), Segment(58.0, 62.0, "seam A")]),
        Transcript(text="", segments=[
            Segment(0.0, 3.0, "seam A"), Segment(3.0, 60.0, "two"),
            Segment(60.0, 64.0, "seam B"),
        ]),
        Transcript(text="", segments=[Segment(0.0, 3.0, "seam B"), Segment(3.0, 60.0, "three")]),
    ]
    text, segments = A.stitch(list(zip(chunks, transcripts)))
    check("three chunks dedup at both seams",
          text.count("seam A") == 1 and text.count("seam B") == 1, text)
    check("all three bodies survive",
          all(word in text for word in ("one", "two", "three")), text)
    check("the merged timeline is monotonic",
          all(segments[i].start <= segments[i + 1].start for i in range(len(segments) - 1)))


def test_stitch_partial_failure() -> None:
    print("\nstitch: a failed chunk does not sink the rest")
    c0 = A.Chunk(0, 0.0, 60.0, 0.0, 62.0)
    c2 = A.Chunk(2, 120.0, 180.0, 118.0, 180.0)
    text, segments = A.stitch([
        (c0, Transcript(text="", segments=[Segment(0.0, 60.0, "start survives")])),
        (c2, Transcript(text="", segments=[Segment(2.0, 60.0, "end survives")])),
    ])
    check("surviving chunks still stitch", "start survives" in text and "end survives" in text)
    check("the gap keeps its real timestamps",
          abs(segments[-1].start - 120.0) < 1e-6, str(segments[-1].start))


async def main() -> int:
    test_stitch()
    test_stitch_boundary_skew()
    test_stitch_partial_failure()
    test_size_targeting()
    test_formats()
    await test_audio()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
