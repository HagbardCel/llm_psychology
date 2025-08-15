import os
from typing import Dict, List, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class StylePack:
    """Represents a therapy style pack with all its components."""
    
    def __init__(self, style_id: str, path: Path):
        self.style_id = style_id
        self.path = path
        self._load_components()
    
    def _load_components(self):
        """Load all components from the style pack directory."""
        # Load knowledge for RAG
        knowledge_file = self.path / "knowledge.md"
        self.knowledge = knowledge_file.read_text(encoding='utf-8') if knowledge_file.exists() else ""
        
        # Load patient-friendly description
        description_file = self.path / "description.txt"
        self.description = description_file.read_text(encoding='utf-8') if description_file.exists() else ""
        
        # Load agent prompts
        psychoanalyst_prompt_file = self.path / "psychoanalyst_prompt.txt"
        self.psychoanalyst_prompt = psychoanalyst_prompt_file.read_text(encoding='utf-8') if psychoanalyst_prompt_file.exists() else ""
        
        reflection_prompt_file = self.path / "reflection_prompt.txt"
        self.reflection_prompt = reflection_prompt_file.read_text(encoding='utf-8') if reflection_prompt_file.exists() else ""
        
        assessment_prompt_file = self.path / "assessment_prompt.txt"
        self.assessment_prompt = assessment_prompt_file.read_text(encoding='utf-8') if assessment_prompt_file.exists() else ""
    
    def is_valid(self) -> bool:
        """Check if this style pack has the minimum required components."""
        # Check if required files exist (even if empty)
        required_files = [
            self.path / "knowledge.md",
            self.path / "description.txt",
            self.path / "psychoanalyst_prompt.txt"
        ]
        return all(file_path.exists() for file_path in required_files)

class StyleService:
    """Service for managing therapy style packs."""
    
    def __init__(self, styles_dir: str = "src/styles"):
        # Handle relative paths correctly by searching from current directory upward
        self.styles_dir = self._find_styles_directory(styles_dir)
        self.style_packs: Dict[str, StylePack] = {}
        self._load_style_packs()
    
    def _find_styles_directory(self, styles_dir: str) -> Path:
        """Find the styles directory by searching upward from current directory."""
        current_path = Path(".").resolve()
        
        # First try the provided path
        direct_path = Path(styles_dir).resolve()
        if direct_path.exists():
            return direct_path
        
        # Search upward through parent directories
        for parent in [current_path] + list(current_path.parents):
            candidate = parent / styles_dir
            if candidate.exists():
                return candidate
        
        # If not found, return the original path for error handling
        return Path(styles_dir).resolve()
    
    def _load_style_packs(self):
        """Load all available style packs from the styles directory."""
        if not self.styles_dir.exists():
            logger.warning(f"Styles directory not found: {self.styles_dir}")
            return
        
        for style_dir in self.styles_dir.iterdir():
            if style_dir.is_dir():
                style_id = style_dir.name
                style_pack = StylePack(style_id, style_dir)
                if style_pack.is_valid():
                    self.style_packs[style_id] = style_pack
                    logger.info(f"Loaded style pack: {style_id}")
                else:
                    logger.warning(f"Invalid style pack (missing components): {style_id}")
    
    def get_available_styles(self) -> List[str]:
        """Get list of available therapy style IDs."""
        return list(self.style_packs.keys())
    
    def get_style_pack(self, style_id: str) -> Optional[StylePack]:
        """Get a specific style pack by ID."""
        return self.style_packs.get(style_id)
    
    def get_style_description(self, style_id: str) -> str:
        """Get the patient-friendly description for a style."""
        style_pack = self.style_packs.get(style_id)
        return style_pack.description if style_pack else ""
    
    def get_psychoanalyst_prompt(self, style_id: str) -> str:
        """Get the psychoanalyst agent prompt for a style."""
        style_pack = self.style_packs.get(style_id)
        return style_pack.psychoanalyst_prompt if style_pack else ""
    
    def get_reflection_prompt(self, style_id: str) -> str:
        """Get the reflection agent prompt for a style."""
        style_pack = self.style_packs.get(style_id)
        return style_pack.reflection_prompt if style_pack else ""
    
    def get_assessment_prompt(self, style_id: str) -> str:
        """Get the assessment agent prompt for a style."""
        style_pack = self.style_packs.get(style_id)
        return style_pack.assessment_prompt if style_pack else ""
    
    def get_knowledge_source(self, style_id: str) -> str:
        """Get the knowledge source identifier for a style (for RAG filtering)."""
        return f"{style_id}.md"

# Global instance
style_service = StyleService()
