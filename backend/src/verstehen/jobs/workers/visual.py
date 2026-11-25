import base64
import re
import xml.etree.ElementTree as ET
from typing import Annotated
from xml.dom import minidom

from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, UserContent
from pydantic_ai.models import Model
from pydantic_ai.tools import ToolReturn
from pydantic_ai.usage import RunUsage, UsageLimits

from verstehen.jobs.contracts import VisualImage, VisualInput, VisualResult
from verstehen.jobs.workers.common import (
    ActivityCallback,
    UsageCallback,
    WorkerModel,
    ignore_activity,
    run_cpu,
    worker_tool,
)

INSTRUCTIONS = """You are a visual maker — a diagram author + renderer for precise, spatial figures. You
receive a brief describing ONE idea that needs exact placement (coordinate geometry, number lines,
vectors, function plots, physical layouts — things auto-layout diagrams cannot express), and you return
ONE clean, correct SVG. You never see the lesson; the brief is everything you know.

You do NOT decide what idea to show — the teacher already decided. Your job is faithful, precise
composition, and above everything CORRECTNESS: the picture must not assert anything false. A right-angle
mark on the wrong corner, a vector pointing the wrong way, a point plotted at the wrong coordinate is a
failure even if it renders cleanly.

Your three tools:
- write_svg({ svg }) — write the complete <svg>…</svg> source (overwrites the previous version).
- edit_svg({ old_text, new_text }) — a surgical exact-match replacement in the current SVG:
  old_text must appear EXACTLY ONCE; it is replaced by new_text. Call write_svg first. For anything
  beyond a one-spot fix (new elements, restructured layout), write_svg the whole document again.
- render_svg({}) — rasterize the current SVG to a PNG. The render arrives as an image in the
  message right after the tool result.

THE ONE RULE THAT MATTERS MOST: verify by looking. You are done only when you have LOOKED at the
rendered PNG and confirmed it is true to the brief. Rendering success only proves the SVG parsed; it
says nothing about whether the geometry is right or the picture is readable. When you look:

- Is every coordinate, angle, direction, and proportion actually correct? Re-derive the geometry if unsure.
- Are labels placed clearly, not overlapping lines or each other?
- Is anything clipped by the viewBox, too small to read, or cramped?
- Would a learner instantly read the intended idea from this picture alone?

Workflow: plan the coordinate space (viewBox + margins, nothing touching the edges) → write_svg →
render_svg → LOOK critically → fix (edit_svg for one-spot fixes, write_svg otherwise) and re-render
until correct and clean. Never finish without having looked at a render of your FINAL SVG.

SVG requirements:
- A complete <svg> with explicit width/height AND a matching viewBox.
- White background (<rect> or style), dark strokes, sans-serif labels at generous sizes.
- One idea, fewest elements — sparse and large beats busy and tiny.
- Draw only what the brief specifies; never invent data, values, or shapes to fill space.
- Plain, clean styling: at most one accent color. An explanatory diagram, not art.

Your FINAL message: 1-2 sentences of notes for the teacher (what the figure shows, any caveats) —
NEVER the SVG source itself. If you genuinely cannot make a correct picture of the brief, say exactly
that in your final message and why."""

IMAGE_INSTRUCTIONS = """ANNOTATING THE LEARNER'S IMAGE — this brief comes with one of the learner's own pictures. Your
figure is that picture with marks on it, not a new drawing:

- Place it EXACTLY ONCE, at its natural size, before your marks so they sit on top:
  <image href="learner-image" x="…" y="…" width="W" height="H"/> — W×H is given with the image.
  The loop substitutes the real picture; never draw or describe its content yourself.
- Use static SVG marks and inline attributes only: no scripts, animation, foreignObject, style blocks,
  external resources, or escaped resource syntax. Local #fragment references are allowed.
- Annotate in the picture's own pixel coordinates (shifted by your x/y if you add margins for labels).
- Every mark must land on the exact feature it names — an arrow at the wrong part is a false statement.
  Locate the feature in the picture first, then check each mark against the render.
- Marks must read against any background: thick strokes in one or two high-contrast colors, and labels
  with a white halo (stroke="white" paint-order="stroke") or set in a margin with a leader line.
- Never hide what the brief is about under a label or a fill.
- If a feature the brief names is not in the picture, never guess where it is: leave it unmarked and say
  so in your notes."""

LOOK_MESSAGE = "Here is the current render of your SVG — inspect it critically (geometry, labels, clipping, readability):"

UNLOOKED_FINISH_MESSAGE = "You finished without looking at a render of your final SVG. Above is its render. If it is correct and clean, reply with just your notes; otherwise call write_svg with fixes and render again."

WRITE_DESCRIPTION = (
    "Write the complete SVG source for the figure (overwrites any previous version)."
)
EDIT_DESCRIPTION = "Replace one exact spot in the current SVG: old_text must appear EXACTLY ONCE and is replaced by new_text. Call write_svg first. For larger changes, write_svg the whole document."
RENDER_DESCRIPTION = (
    "Render the current SVG to a PNG and show it to you for inspection. No arguments."
)

LEARNER_IMAGE_HREF = "learner-image"


class LearnerImage(BaseModel):
    path: str
    snapshot_id: str
    data: bytes
    mime_type: str
    width: int
    height: int


def annotation_placement_problem(svg: str, width: int, height: int) -> str | None:
    if re.search(r"<!DOCTYPE|<!ENTITY", svg, re.I):
        return "annotation SVGs cannot declare entities or a document type"
    if "<?" in svg:
        return "annotation SVGs cannot contain processing instructions"
    try:
        document = minidom.parseString(svg)
    except Exception:
        return "expected a complete SVG document"
    root = document.documentElement
    if root is None or root.tagName != "svg":
        return "expected a complete SVG document"
    elements = list(document.getElementsByTagName("*"))
    images = [element for element in elements if element.tagName == "image"]
    if len(images) != 1:
        return f'the SVG must place the learner\'s image exactly once with <image href="{LEARNER_IMAGE_HREF}" …/> (found {len(images)})'
    image = images[0]
    hrefs = [
        attr.value
        for attr in image.attributes.values()
        if attr.name in {"href", "xlink:href"}
    ]
    if hrefs != [LEARNER_IMAGE_HREF]:
        return f'the image must use exactly one href="{LEARNER_IMAGE_HREF}"'
    try:
        natural_size = (
            float(image.getAttribute("width")) == width
            and float(image.getAttribute("height")) == height
        )
    except ValueError:
        natural_size = False
    if not natural_size:
        return f"place the image at its natural {width}×{height} pixel size"
    for element in elements:
        if ":" in element.tagName:
            return "annotation SVG elements cannot use namespace prefixes"
        if element.tagName.lower() in {
            "script",
            "foreignobject",
            "style",
            "animate",
            "animatemotion",
            "animatetransform",
            "set",
            "discard",
        }:
            return "annotation SVGs must use static SVG marks and inline styling"
        for attr in element.attributes.values():
            key, value = attr.name, attr.value
            if key == "xmlns" and value != "http://www.w3.org/2000/svg":
                return "annotation SVGs must use the SVG namespace"
            if key.startswith("xmlns:") and (
                key != "xmlns:xlink" or value != "http://www.w3.org/1999/xlink"
            ):
                return "annotation SVGs cannot declare namespace aliases"
            if ":" in key and key not in {
                "xmlns:xlink",
                "xlink:href",
                "xml:lang",
                "xml:space",
            }:
                return "annotation SVGs cannot use qualified attribute aliases"
            if key == "xlink:href":
                owner = element
                while isinstance(owner, minidom.Element) and not owner.hasAttribute(
                    "xmlns:xlink"
                ):
                    owner = owner.parentNode
                if (
                    not isinstance(owner, minidom.Element)
                    or owner.getAttribute("xmlns:xlink")
                    != "http://www.w3.org/1999/xlink"
                ):
                    return (
                        "xlink:href requires the standard XLink namespace declaration"
                    )
            if key.lower().startswith("on"):
                return "annotation SVGs cannot contain event handlers"
            if key == "xml:base" or re.search(r"\\|@import", value, re.I):
                return "annotation SVGs cannot change resource bases or use escaped resource syntax"
            if (
                key in {"href", "xlink:href"}
                and element is not image
                and not re.fullmatch(r"#[A-Za-z_][\w:.-]*", value)
            ):
                return "annotation SVGs cannot reference other files or URLs"
            if re.search(r"url\s*\(", value, re.I) and not re.fullmatch(
                r"url\(\s*['\"]?#[A-Za-z_][\w:.-]*['\"]?\s*\)", value
            ):
                return "annotation SVG resources must be local fragment references"
    return None


def render_svg(svg: str, image: LearnerImage | None = None) -> bytes:
    import resvg_py

    if image:
        root = ET.fromstring(svg)
        uri = f"data:{image.mime_type};base64,{base64.b64encode(image.data).decode()}"
        for element in root.iter():
            if element.tag.split("}")[-1] == "image":
                for key in ("href", "{http://www.w3.org/1999/xlink}href"):
                    if element.get(key) == LEARNER_IMAGE_HREF:
                        element.set(key, uri)
        svg = ET.tostring(root, encoding="unicode")
    return resvg_py.svg_to_bytes(svg_string=svg)


def snippet_around(svg: str, target: str) -> str:
    words = target.strip().split()
    if not words:
        return "(empty old_text)"
    lines = svg.split("\n")
    scores = [sum(word in line for word in words) for line in lines]
    if not max(scores, default=0):
        return "(no similar line found)"
    index = scores.index(max(scores))
    return "\n".join(
        f"{j + 1}: {lines[j]}"
        for j in range(max(0, index - 1), min(len(lines), index + 2))
    )


async def run_visual_maker(
    input: VisualInput,
    model: Model,
    *,
    learner_image: LearnerImage | None = None,
    on_activity: ActivityCallback | None = None,
    on_usage: UsageCallback | None = None,
    max_iterations: int = 8,
) -> VisualResult:
    image = learner_image
    if input.image and image is None:
        return VisualResult(
            svg="",
            notes="FAILED: showing the learner's image to the maker failed — no learner image supplied",
        )
    prompt = "\n".join(
        [
            "Brief for ONE annotated image (from the teacher, verbatim — it is everything you know):"
            if image
            else "Brief for ONE precise figure (from the teacher, verbatim — it is everything you know):",
            input.brief.strip() or "(no brief)",
            "",
            *(
                [
                    f'The learner\'s image follows: {image.width}×{image.height} px. Place it with <image href="{LEARNER_IMAGE_HREF}" … width="{image.width}" height="{image.height}"/>.'
                ]
                if image
                else []
            ),
            "Author the SVG, render it, look at it, iterate until correct, then finish with your notes.",
        ]
    )
    note = on_activity or ignore_activity
    current = rendered = final_text = ""

    async def write(
        svg: Annotated[
            str,
            Field(description='Complete <svg xmlns="…">…</svg> markup.'),
        ],
    ) -> str:
        nonlocal current
        if "<svg" not in svg:
            return (
                "ERROR: expected a complete <svg>…</svg> document in the `svg` field."
            )
        if image and (
            problem := annotation_placement_problem(svg, image.width, image.height)
        ):
            return f"ERROR: {problem}."
        current = svg
        await note(f"write_svg: {len(svg) / 1024:.1f} KB")
        return f"Saved ({len(svg)} bytes). Call render_svg to look at it."

    async def edit(
        old_text: Annotated[
            str,
            Field(
                description="The exact text to replace — must match exactly once in the current SVG."
            ),
        ],
        new_text: Annotated[str, Field(description="The replacement text.")],
    ) -> str:
        nonlocal current
        if not current:
            return "ERROR: nothing to edit — call write_svg first."
        if not old_text:
            return "ERROR: expected old_text (non-empty) and new_text strings."
        count = current.count(old_text)
        if count == 0:
            return f"ERROR: old_text not found. Closest line for reference:\n{snippet_around(current, old_text)}"
        if count > 1:
            return f"ERROR: old_text appears {count} times — it must match EXACTLY ONCE. Include more surrounding context to make it unique."
        edited = current.replace(old_text, new_text)
        if image and (
            problem := annotation_placement_problem(edited, image.width, image.height)
        ):
            return f"ERROR: edit not applied — {problem}."
        current = edited
        await note("edit_svg: applied")
        return "OK — replaced 1 occurrence. Call render_svg to look at the edited SVG."

    async def render() -> ToolReturn[str] | str:
        nonlocal rendered
        if not current:
            return "ERROR: nothing to render — call write_svg first."
        try:
            png = await run_cpu(render_svg, current, image)
        except Exception as error:
            await note("render_svg: render error")
            return f"RENDER ERROR (the SVG may be malformed): {error}. Fix it with write_svg and render again."
        rendered = current
        await note("render_svg: inspecting render")
        return ToolReturn(
            return_value="Rendered — the PNG follows in the next message. Look at it.",
            content=[LOOK_MESSAGE, BinaryContent(data=png, media_type="image/png")],
        )

    def finish(notes: str) -> VisualResult:
        if not current:
            return VisualResult(
                svg="",
                notes="FAILED: the maker never wrote an SVG."
                + (f" ({notes[:300]})" if notes else ""),
            )
        return VisualResult(
            svg=current,
            notes=notes or None,
            image=VisualImage(
                path=image.path,
                snapshot_id=image.snapshot_id,
                extension="png" if image.mime_type == "image/png" else "jpeg",
            )
            if image
            else None,
        )

    agent = Agent(
        WorkerModel(model, "visualMaker", on_usage),
        system_prompt=INSTRUCTIONS + ("\n\n" + IMAGE_INSTRUCTIONS if image else ""),
        deps_type=type(None),
        output_type=str | None,
        tools=[
            worker_tool(write, "write_svg", WRITE_DESCRIPTION),
            worker_tool(edit, "edit_svg", EDIT_DESCRIPTION),
            worker_tool(render, "render_svg", RENDER_DESCRIPTION),
        ],
        retries=max_iterations,
    )
    usage = RunUsage()
    limits = UsageLimits(request_limit=max_iterations)
    next_prompt: str | list[UserContent] = (
        [prompt, BinaryContent(data=image.data, media_type=image.mime_type)]
        if image
        else prompt
    )
    history: list[ModelMessage] | None = None
    try:
        while True:
            result = await agent.run(
                next_prompt, message_history=history, usage=usage, usage_limits=limits
            )
            final_text, history = (result.output or "").strip(), result.all_messages()
            if not current or rendered == current:
                return finish(final_text)
            try:
                png = await run_cpu(render_svg, current, image)
            except Exception as error:
                return VisualResult(
                    svg="",
                    notes=f"FAILED: rendering the final SVG failed — {error}",
                )
            await note("render_svg: inspecting final render")
            rendered = current
            next_prompt = [
                UNLOOKED_FINISH_MESSAGE,
                BinaryContent(data=png, media_type="image/png"),
            ]
    except UsageLimitExceeded:
        pass
    except Exception as error:
        return VisualResult(svg="", notes=f"FAILED: the maker crashed — {error}")
    if current and rendered == current:
        return finish(
            final_text or "Iteration limit reached — delivering the last verified SVG."
        )
    return VisualResult(
        svg="",
        notes=f"FAILED: iteration limit ({max_iterations}) reached without a verified SVG.",
    )
