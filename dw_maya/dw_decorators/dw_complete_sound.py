from functools import wraps
import random
from pathlib import Path
from typing import Callable, List, Any
from dw_logger import get_logger
from dw_linux.dw_sound import sox_play

logger = get_logger()


class SoundResourceManager:
    """Manages sound resources for function completion feedback."""

    def __init__(self):
        self.success_sounds: List[Path] = []
        self.failure_sounds: List[Path] = []
        self._random = random.SystemRandom()
        self._initialize_sounds()

    def _initialize_sounds(self) -> None:
        """Initialize sound file paths."""
        try:
            # First try to find sounds relative to this file
            sound_base = self._get_sound_path()

            if not sound_base.exists():
                logger.warning(f"Sound directory not found at {sound_base}")
                return

            # Load success sounds
            success_dir = sound_base / '_happy'
            if success_dir.exists():
                self.success_sounds = [
                    f for f in success_dir.glob('*.wav')
                ]

            # Load failure sounds
            failure_dir = sound_base / '_death'
            if failure_dir.exists():
                self.failure_sounds = [
                    f for f in failure_dir.glob('*.wav')
                ]

            logger.debug(
                f"Loaded {len(self.success_sounds)} success and "
                f"{len(self.failure_sounds)} failure sounds"
            )

        except Exception as e:
            logger.error(f"Failed to initialize sound resources: {str(e)}")

    @staticmethod
    def _get_sound_path() -> Path:
        """Get the base path for sound files."""
        # Try different potential locations
        current_file = Path(__file__)
        potential_paths = [
            current_file.parent.parent / 'ressources' / 'audio_files' / 'BattleblockTheater',
            Path('E:/dw_coding/dw_open_tools/ressources/audio_files/BattleblockTheater')
        ]

        # Return first existing path
        for path in potential_paths:
            if path.exists():
                return path

        # Default to first path if none exist
        return potential_paths[0]

    def play_success(self) -> None:
        """Play a random success sound."""
        if self.success_sounds:
            try:
                sound_file = self._random.choice(self.success_sounds)
                sox_play(str(sound_file))
            except Exception as e:
                logger.error(f"Failed to play success sound: {str(e)}")

    def play_failure(self) -> None:
        """Play a random failure sound."""
        if self.failure_sounds:
            try:
                sound_file = self._random.choice(self.failure_sounds)
                sox_play(str(sound_file))
            except Exception as e:
                logger.error(f"Failed to play failure sound: {str(e)}")


# Singleton instance of sound manager
_sound_manager = SoundResourceManager()


def complete_sound(
        success_only: bool = False,
        volume: float = 1.0) -> Callable:
    """
    Decorator that plays sounds on function completion or failure.

    Args:
        success_only: Only play sound on success, not on failure
        volume: Volume multiplier (0.0 to 1.0)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                result = func(*args, **kwargs)
                _sound_manager.play_success()
                return result
            except Exception as e:
                if not success_only:
                    _sound_manager.play_failure()
                raise

        return wrapper

    # Handle case where decorator is used without parameters
    if callable(success_only):
        f = success_only
        success_only = False
        return decorator(f)

    return decorator
