import argparse
from .app import App


def main_internal(argv: list[str]) -> int:
    """Internal main function for the WarpFox CLI.

    Args:
        argv (list[str]): Command-line arguments.

    Returns:
        int: The exit code.
    """

    parser = argparse.ArgumentParser(description="WarpFox CLI")
    parser.add_argument("command", help="The command to run.")
    parser.add_argument(
        "--manifest", help="The path to the manifest file.", default="warpfox.json"
    )
    args = parser.parse_args(argv[1:])

    return App(command=args.command, manifest_path=args.manifest).run()
