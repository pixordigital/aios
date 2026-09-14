"""Skill Loader — runtime skill injection from project files (AGENTS.md, CLAUDE.md, etc.).

Paperclip-style: agents learn workflows and project context at runtime without retraining.
Loads markdown skill files from project workspace and injects into agent context.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from aios.config import settings

logger = logging.getLogger(__name__)

# Standard skill file names (ordered by priority)
SKILL_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/AGENTS.md",
    ".claude/CLAUDE.md",
    "aios/AGENTS.md",
    "aios/CLAUDE.md",
    "skills.md",
    "SKILLS.md",
    "instructions.md",
    "INSTRUCTIONS.md",
]

# Section patterns for parsing
SECTION_PATTERN = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)
CODE_BLOCK_PATTERN = re.compile(r"```(\w+)?\n(.*?)\n```", re.DOTALL)


@dataclass
class SkillSection:
    """A parsed skill section from a markdown file."""
    title: str
    content: str
    level: int  # heading level (1-3)
    file_path: str


@dataclass
class LoadedSkill:
    """A skill loaded from project files."""
    name: str
    description: str
    content: str
    source_file: str
    priority: int  # lower = higher priority
    tags: list[str]


class SkillLoader:
    """Loads and parses skill files from project workspace."""

    def __init__(self, workspace_root: str | None = None):
        self.workspace_root = Path(workspace_root or settings.app_data_dir).resolve()
        self._cache: dict[str, list[LoadedSkill]] = {}

    def find_skill_files(self, project_path: str | None = None) -> list[Path]:
        """Find all skill files in project workspace."""
        root = Path(project_path) if project_path else self.workspace_root
        base_root = root
        found = []

        for skill_file in SKILL_FILES:
            path = root / skill_file
            if path.exists() and path.is_file():
                found.append(path)

        # Also look for any .md files in .claude/skills/ or skills/ directories
        for skills_dir in [root / ".claude" / "skills", root / "skills"]:
            if skills_dir.exists() and skills_dir.is_dir():
                found.extend(skills_dir.glob("*.md"))

        return found, base_root

    def parse_skill_file(self, file_path: Path, base_root: Path | None = None) -> list[LoadedSkill]:
        """Parse a markdown skill file into structured skills."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to read skill file %s: %s", file_path, e)
            return []

        skills = []
        base = base_root or self.workspace_root
        try:
            relative_path = str(file_path.relative_to(base))
        except ValueError:
            relative_path = file_path.name

        # Split by top-level headings
        sections = self._split_by_headings(content)

        for i, (heading, section_content) in enumerate(sections):
            if not heading.strip():
                continue

            # Extract tags from heading (e.g., "## Skill Name [tag1, tag2]")
            tags = []
            clean_title = heading
            tag_match = re.search(r"\[([^\]]+)\]$", heading)
            if tag_match:
                tags = [t.strip() for t in tag_match.group(1).split(",")]
                clean_title = heading[:tag_match.start()].strip()

            # Determine priority from heading level and position
            heading_level = len(heading) - len(heading.lstrip("#"))
            priority = heading_level * 100 + i

            skill = LoadedSkill(
                name=clean_title or f"{relative_path}:section_{i}",
                description=self._extract_description(section_content),
                content=section_content.strip(),
                source_file=relative_path,
                priority=priority,
                tags=tags,
            )
            skills.append(skill)

        # If no headings found, treat entire file as one skill
        if not skills and content.strip():
            skills.append(LoadedSkill(
                name=file_path.stem,
                description=self._extract_description(content),
                content=content.strip(),
                source_file=relative_path,
                priority=999,
                tags=["auto"],
            ))

        return skills

    def _split_by_headings(self, content: str) -> list[tuple[str, str]]:
        """Split markdown by headings, returning (heading, content) pairs."""
        lines = content.split("\n")
        sections = []
        current_heading = ""
        current_content = []

        for line in lines:
            heading_match = SECTION_PATTERN.match(line)
            if heading_match:
                if current_heading or current_content:
                    sections.append((current_heading, "\n".join(current_content)))
                current_heading = line
                current_content = []
            else:
                current_content.append(line)

        if current_heading or current_content:
            sections.append((current_heading, "\n".join(current_content)))

        return sections

    def _extract_description(self, content: str) -> str:
        """Extract first paragraph as description."""
        lines = content.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("```"):
                return line[:200]
        return ""

    def load_skills(self, project_path: str | None = None, force_reload: bool = False) -> list[LoadedSkill]:
        """Load all skills from project workspace."""
        cache_key = project_path or str(self.workspace_root)

        if not force_reload and cache_key in self._cache:
            return self._cache[cache_key]

        all_skills = []
        skill_files, base_root = self.find_skill_files(project_path)

        for file_path in skill_files:
            skills = self.parse_skill_file(file_path, base_root)
            all_skills.extend(skills)

        # Sort by priority (lower = higher priority)
        all_skills.sort(key=lambda s: s.priority)

        self._cache[cache_key] = all_skills
        logger.info("Loaded %d skills from %d files in %s", len(all_skills), len(skill_files), cache_key)
        return all_skills

    def get_skills_for_task(self, task: str, project_path: str | None = None, max_skills: int = 5) -> list[LoadedSkill]:
        """Get relevant skills for a given task/query."""
        all_skills = self.load_skills(project_path)

        if not all_skills:
            return []

        # Simple relevance scoring based on tag/keyword matching
        task_lower = task.lower()
        scored = []

        for skill in all_skills:
            score = 0
            # Tag matching
            for tag in skill.tags:
                if tag.lower() in task_lower:
                    score += 10
            # Name matching
            if any(word in skill.name.lower() for word in task_lower.split() if len(word) > 3):
                score += 5
            # Content keyword matching (lightweight)
            content_lower = skill.content.lower()
            for word in task_lower.split():
                if len(word) > 4 and word in content_lower:
                    score += 1

            if score > 0:
                scored.append((score, skill))

        # Sort by score desc, then priority asc
        scored.sort(key=lambda x: (-x[0], x[1].priority))
        return [s for _, s in scored[:max_skills]]

    def format_skills_for_context(self, skills: list[LoadedSkill]) -> str:
        """Format skills for injection into agent system prompt."""
        if not skills:
            return ""

        lines = ["## Available Skills (loaded from project)"]
        for skill in skills:
            lines.append(f"\n### {skill.name}")
            if skill.description:
                lines.append(f"*{skill.description}*")
            lines.append(skill.content[:1500])  # truncate long skills
            if len(skill.content) > 1500:
                lines.append(f"... (truncated, full in {skill.source_file})")

        return "\n".join(lines)


# Global instance
skill_loader = SkillLoader()