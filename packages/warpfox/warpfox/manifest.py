from loguru import logger
import json


class Manifest:
    """A class to represent the manifest of a WarpFox package.
    Manifests are used to describe the contents of a package,
    it's branding, and other metadata.
    """

    def __init__(self, path: str) -> None:
        """Initializes the manifest.

        Args:
            path (str): The path to the manifest file.
        """
        self.path = path
        self.read()

    def read(self) -> None:
        """Reads the manifest file."""
        with open(self.path, "r") as f:
            data = json.load(f)
        self.process(data)

    def process(self, data: dict) -> None:
        """Processes the manifest data.

        Args:
            data (dict): The manifest data.
        """
        self.data = data
        self.name = data.get("name")
        self.brands = data.get("brands", [])
        self.description = data.get("description", "")

    def __str__(self) -> str:
        return f"{self.name} ({self.description})"
