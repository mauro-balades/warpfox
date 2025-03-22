from .manifest import Manifest

import sys
import time
from loguru import logger


class App:
    """The main application class for WarpFox."""

    def __init__(self, command: str, manifest_path: str) -> None:
        """Initializes the application.

        Args:
            command (str): The command to run.
            manifest_path (str): The path to the manifest file.
        """
        self.command = command
        self.manifest_path = manifest_path

    def run(self) -> int:
        """Runs the application.

        Returns:
            int: The exit code.
        """
        logger.remove()
        logger.add(
            sys.stdout,
            colorize=True,
            format="<level>{level.name: <7}</level>: {message}",
        )

        start_time = time.time()

        try:
            manifest = Manifest(self.manifest_path)
            logger.info(f"Running command '{self.command}' for package: {manifest}")
        except Exception as e:
            logger.error(f"Failed to run command '{self.command}': {e}")
            return 1
        finally:
            end_time = time.time()
            logger.success(f"Finished in {end_time - start_time:.2f} seconds.")
            return 0
