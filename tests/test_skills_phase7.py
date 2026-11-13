"""Phase 7 regression: local skills catalog, prompt injection, request_skill."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.config import BotConfig
from core.reactive_engine import ReactiveEngine
from core.skills import SkillCatalog, _split_frontmatter
from tools.skills_tool import run_request_skill

REPO = Path(__file__).resolve().parents[1]


def _write_skill(root: Path, folder: str, *, name: str, description: str,
                 text_only: bool = False, body: str = "Guide body", nested=False):
    home = root / folder / folder if nested else root / folder
    home.mkdir(parents=True)
    meta = f"---\nname: {name}\ndescription: \"{description}\"\n"
    if text_only:
        meta += "metadata:\n  text-only: true\n"
    (home / "SKILL.md").write_text(meta + "---\n\n" + body + "\n", encoding="utf-8")


@pytest.fixture
def catalog(tmp_path):
    _write_skill(tmp_path, "guide", name="guide", description="A reading guide",
                 text_only=True, body="Read this carefully.")
    _write_skill(tmp_path, "toolbox", name="toolbox", description="Needs scripts")
    _write_skill(tmp_path, "wrapped", name="wrapped", description="Nested home",
                 text_only=True, nested=True)
    return SkillCatalog(tmp_path, ["guide"])


def test_frontmatter_split_keeps_body_and_tolerates_plain_markdown():
    meta, body = _split_frontmatter("---\nname: x\ndescription: y\n---\n\nHello")
    assert meta == {"name": "x", "description": "y"}
    assert body == "Hello"

    meta, body = _split_frontmatter("# No frontmatter")
    assert meta == {}
    assert body == "# No frontmatter"


def test_text_only_gating_and_wrapper_folder(catalog):
    everywhere = catalog.available(workshop=False)
    assert set(everywhere) == {"guide", "wrapped"}
    assert catalog.available(workshop=True).keys() == {"guide", "toolbox", "wrapped"}

    wrapped = catalog.skills()["wrapped"]
    assert wrapped.path.name == "wrapped"
    assert wrapped.rel == "wrapped/wrapped"   # its folder under the catalog

    assert catalog.instructions("guide") == "Read this carefully."
    assert catalog.instructions("missing") is None


def test_prompt_lists_only_available_skills_and_preloads_defaults(catalog):
    prompt = catalog.prompt(workshop=False)
    assert "<available_skills>" in prompt
    assert "guide: A reading guide" in prompt
    assert "wrapped: Nested home" in prompt
    assert "toolbox" not in prompt          # needs the workshop
    assert "/skills/" not in prompt          # no workshop paths
    assert '<skill name="guide">\nRead this carefully.\n</skill>' in prompt

    workshop_prompt = catalog.prompt(workshop=True)
    assert "toolbox: Needs scripts" in workshop_prompt
    assert "/skills/<name>/" in workshop_prompt


def test_request_skill_reads_text_only_and_refuses_workshop_only(catalog):
    assert "Read this carefully." in run_request_skill(
        catalog, {"skill_name": "guide"}, workshop=False)
    assert "/skills/" not in run_request_skill(
        catalog, {"skill_name": "guide"}, workshop=False)

    refused = run_request_skill(catalog, {"skill_name": "toolbox"}, workshop=False)
    assert "There's no skill named 'toolbox'." in refused
    assert "guide" in refused                # suggests what does exist

    assert "Needs scripts" not in run_request_skill(
        catalog, {"skill_name": "toolbox"}, workshop=True)
    assert "/skills/toolbox/" in run_request_skill(
        catalog, {"skill_name": "toolbox"}, workshop=True)


def test_bundled_story_guides_are_offered_without_a_workshop():
    bundled = SkillCatalog(REPO / "skills")
    available = bundled.available(workshop=False)
    assert {"storytelling", "fiction-criticism"} <= set(available)
    assert not ({"docx", "pptx", "xlsx", "pdf"} & set(available))
    assert "storytelling" in bundled.prompt(workshop=False)


def test_config_parses_skills_and_points_at_the_skills_folder():
    config = BotConfig._from_dict({
        "bot_id": "test-bot",
        "name": "Test Bot",
        "skills": {"default_skills": ["storytelling"]},
    })
    assert config.skills.default_skills == ["storytelling"]
    assert config.get_skills_config() == {"enabled": True, "skills_dir": "skills"}


def _bare_engine(catalog):
    engine = object.__new__(ReactiveEngine)
    engine.skills = catalog
    engine.discord_tool_executor = None
    engine.repository_manager = None
    engine.ask_prime_executor = None
    engine.web_search_enabled = False
    engine.mcp_manager = None
    engine.pptx_builder = object()       # skip building the real one
    engine.local_attachment_store = None
    engine.config = SimpleNamespace(
        api=SimpleNamespace(model="test-model", context_tokens=4096))
    return engine


def test_build_api_params_adds_the_catalog_and_read_only_tool(catalog):
    engine = _bare_engine(catalog)
    system_blocks = [{"type": "text", "text": "Base prompt"}]

    params = ReactiveEngine._build_api_params(
        engine, system_blocks, None, {"messages": []})

    names = {tool["name"] for tool in params["tools"]}
    assert "request_skill" in names
    assert "<available_skills>" in system_blocks[0]["text"]
    assert "Base prompt" in system_blocks[0]["text"]

    request_tool = next(t for t in params["tools"] if t["name"] == "request_skill")
    assert "/skills/" not in request_tool["description"]


async def test_execute_request_skill_dispatches(catalog):
    engine = _bare_engine(catalog)
    calls = []
    engine.conversation_logger = SimpleNamespace(
        log_tool_call=lambda *args: calls.append(args))
    message = SimpleNamespace(channel=SimpleNamespace(id=42), guild=None)
    response = SimpleNamespace(content=[SimpleNamespace(
        type="tool_use", name="request_skill", id="tu1",
        input={"skill_name": "guide"})])

    results, files = await ReactiveEngine._execute_tool_blocks(
        engine, response, message, None)

    assert files == []
    assert results[0]["tool_use_id"] == "tu1"
    assert "Read this carefully." in results[0]["content"]
    assert calls == [("skills", "request_skill", "guide")]
