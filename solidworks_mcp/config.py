"""
SolidWorks MCP Configuration
----------------------------
Configuration management with JSON file support.
"""

import os
import json
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class SolidWorksConfig:
    """
    SolidWorks MCP Configuration
    
    Attributes:
        exe_path: Path to SLDWORKS.exe ("auto" for auto-detect)
        startup_timeout: Seconds to wait for SolidWorks startup
        connection_retry_interval: Seconds between connection retries
        max_retries: Maximum connection retry attempts
        default_unit: Default unit for dimensions (mm, inch, m)
        part_template: Part template path ("auto" for auto-detect)
        assembly_template: Assembly template path
        drawing_template: Drawing template path
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Log file name
    """
    
    # SolidWorks paths
    exe_path: str = "auto"
    part_template: str = "auto"
    assembly_template: str = "auto"
    drawing_template: str = "auto"
    
    # Connection settings
    startup_timeout: int = 120
    connection_retry_interval: int = 5
    max_retries: int = 3
    
    # Units
    default_unit: str = "mm"
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "solidworks_mcp.log"
    
    # Feature defaults (in default_unit)
    default_extrude_depth: float = 10.0
    default_fillet_radius: float = 2.0
    default_chamfer_distance: float = 2.0
    default_circle_radius: float = 25.0
    
    # View capture defaults
    capture_width: int = 1920
    capture_height: int = 1080

    # Guarded write workflow. Roots are trusted server configuration, never tool arguments.
    guarded_mode: bool = False
    output_roots: list[str] = field(default_factory=list)
    protected_roots: list[str] = field(default_factory=list)
    # Advertised tool groups; None = all ordinary groups. "core" is always enabled.
    enabled_toolsets: Optional[list[str]] = None
    # Routing is opt-in independently of catalog filtering; never loads its add-in.
    routing_enabled: bool = False
    
    def __post_init__(self):
        """Validate configuration after initialization"""
        valid_units = ["mm", "inch", "m", "cm", "ft"]
        if self.default_unit not in valid_units:
            logger.warning(f"Invalid unit '{self.default_unit}', using 'mm'")
            self.default_unit = "mm"
        
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.log_level.upper() not in valid_levels:
            logger.warning(f"Invalid log level '{self.log_level}', using 'INFO'")
            self.log_level = "INFO"
    
    @classmethod
    def get_config_path(cls) -> Path:
        """Get default config file path"""
        return Path(__file__).parent / "config.json"
    
    @classmethod
    def load(cls, config_path: Optional[str] = None) -> 'SolidWorksConfig':
        """
        Load configuration from JSON file
        
        Args:
            config_path: Path to config file (uses default if None)
        
        Returns:
            SolidWorksConfig instance
        """
        if config_path is None:
            config_path = cls.get_config_path()
        else:
            config_path = Path(config_path)
        
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"Loaded config from: {config_path}")
                return cls(**data)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in config file: {e}")
            except TypeError as e:
                logger.error(f"Invalid config structure: {e}")
        
        logger.info("Using default configuration")
        return cls()
    
    def save(self, config_path: Optional[str] = None) -> bool:
        """
        Save configuration to JSON file
        
        Args:
            config_path: Path to save config (uses default if None)
        
        Returns:
            True if successful
        """
        if config_path is None:
            config_path = self.get_config_path()
        else:
            config_path = Path(config_path)
        
        try:
            # Ensure directory exists
            config_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(self), f, indent=2)
            
            logger.info(f"Saved config to: {config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return asdict(self)
    
    def update(self, **kwargs) -> None:
        """Update configuration values"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
                logger.debug(f"Config updated: {key} = {value}")
            else:
                logger.warning(f"Unknown config key: {key}")
    
    def get_log_level_int(self) -> int:
        """Get logging level as integer"""
        levels = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        return levels.get(self.log_level.upper(), logging.INFO)

    def create_path_policy(self):
        """Build the write policy only when guarded workflow is explicitly enabled."""
        if not self.guarded_mode:
            return None
        if not self.output_roots:
            raise ValueError("guarded_mode requires at least one trusted output_root")
        from .core.policy import PathPolicy

        return PathPolicy(
            output_roots=[Path(root) for root in self.output_roots],
            protected_roots=[Path(root) for root in self.protected_roots],
        )


# ============================================================================
# Global Configuration Instance
# ============================================================================

# Load config on module import
config = SolidWorksConfig.load()


def get_config() -> SolidWorksConfig:
    """Get global configuration instance"""
    return config


def reload_config(config_path: Optional[str] = None) -> SolidWorksConfig:
    """Reload configuration from file"""
    global config
    config = SolidWorksConfig.load(config_path)
    return config


def save_config(config_path: Optional[str] = None) -> bool:
    """Save current configuration to file"""
    return config.save(config_path)
