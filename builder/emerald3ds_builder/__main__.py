"""Entry point: the window without arguments, the command line with them.

`--run-script SCRIPT [ARGS]` runs one bundled generator script; the builder
uses it on itself so the scripts also run from the standalone executable.
"""

import runpy
import sys


def run_script(argv: list[str]) -> int:
    import os
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    script = argv[0]
    sys.argv = [script] + argv[1:]
    sys.path.insert(0, str(__import__("pathlib").Path(script).resolve().parent))
    runpy.run_path(script, run_name="__main__")
    return 0


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--run-script":
        return run_script(sys.argv[2:])
    if len(sys.argv) > 1:
        from .cli import main as cli_main
        return cli_main()
    from .gui import main as gui_main
    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
