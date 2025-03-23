from . import mozconfig
from .manifest import Manifest

import sys
import time
import os
import json

from loguru import logger

import tarfile
import urllib.request

from alive_progress import alive_bar


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

        self.init_logger()
        self.init_dirs()
        self.init_config()

    def init_config(self) -> None:
        """Initializes the configuration."""
        self.config = {}
        if os.path.exists(".warpfox/cache.json"):
            with open(".warpfox/cache.json", "r") as f:
                self.config = json.load(f)
        if "firefox-version" not in self.config:
            relative_path = os.path.join(
                os.path.dirname(__file__), "..", "firefox.json"
            )
            with open(relative_path, "r") as f:
                self.config["firefox-version"] = json.load(f)["version"]

    def save_config(self) -> None:
        """Saves the configuration."""
        with open(".warpfox/cache.json", "w") as f:
            json.dump(self.config, f)

    def init_logger(self) -> None:
        """Initializes the logger."""
        logger.remove()
        logger.add(
            sys.stdout,
            colorize=True,
            format="<level>{level.name: <7}</level>: {message}",
        )

    def init_dirs(self) -> None:
        """Initializes the directories."""
        os.makedirs(".warpfox", exist_ok=True)

    def run(self) -> int:
        """Runs the application.

        Returns:
            int: The exit code.
        """
        start_time = time.time()
        success = False
        try:
            self.manifest = Manifest(self.manifest_path)
            logger.info(
                f"Running command '{self.command}' for package: {self.manifest}"
            )
            self.init_firefox()
            self.bootstrap_firefox()
            self.build_firefox()
        except Exception as e:
            logger.error(f"Failed to run command '{self.command}': {e}")
        finally:
            end_time = time.time()
            logger.success(f"Finished in {end_time - start_time:.2f} seconds.")
            success = True
        self.save_config()
        return 0 if success else 1

    def init_firefox(self) -> None:
        """Download and extract the firefox source code"""
        if "intialized" in self.config and self.config["intialized"]:
            return
        firefox_version = self.config["firefox-version"]
        download_url = f"https://github.com/mauro-balades/warpfox/releases/download/firefox-v{firefox_version}/firefox-source.tar.gz"
        logger.info(f"Using Firefox version {firefox_version}")
        if not os.path.exists(".warpfox/firefox-source.tar.gz"):
            logger.info(f"Downloading Firefox source code from {download_url}")
            urllib.request.urlretrieve(
                download_url,
                ".warpfox/firefox-source.tar.gz",
                reporthook=self.download_progress,
            )
            print()
            self.progress_bar = None
        if not os.path.exists(".warpfox/firefox-source"):
            logger.info("Extracting Firefox source code")
            os.mkdir(".warpfox/firefox-source")
            with tarfile.open(".warpfox/firefox-source.tar.gz") as tar:
                logger.info("Extracting Firefox source code")
                tar.extractall(".warpfox/firefox-source")
        self.config["intialized"] = True

    def download_progress(
        self, block_num: int, block_size: int, total_size: int
    ) -> None:
        """Display download progress.

        Args:
            block_num (int): The block number.
            block_size (int): The block size.
            total_size (int): The total size.
        """
        print(
            f"Downloading Firefox source code: {block_num * block_size / total_size:.2%}",
            end="\r",
        )

    def bootstrap_firefox(self) -> None:
        """Bootstrap Firefox"""
        if "bootstrapped" in self.config and self.config["bootstrapped"]:
            return
        logger.info("Bootstrapping Firefox")
        os.system("cd .warpfox/firefox-source && ./mach bootstrap")
        self.config["bootstrapped"] = True

    def build_firefox(self) -> None:
        """Build Firefox"""
        logger.info("Populating mozconfig")
        with open(".warpfox/firefox-source/mozconfig", "w") as f:
            f.write(mozconfig.get_mozconfig_contents())
        logger.info("Building Firefox")
        os.system("cd .warpfox/firefox-source && ./mach build")
