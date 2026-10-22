#!/usr/bin/env python3
"""Compatibility CLI for the importable local-loop runner."""
from validation.loop import *

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--mode", choices=("task", "full", "local"), required=True,
                        help="task/local: active-scope validation; full: also all unit regression tests")
    parser.add_argument("--all", action="store_true", help="Explicit whole-repository validation and all unit regression tests")
    parser.add_argument("--task-file", help="Selected tasks/<task-name>.md contract")
    parser.add_argument("--log-dir", type=Path, help="Parent directory for run logs (outside the repository; default: OS temporary directory)")
    parser.add_argument("--profile", action="store_true", help="Profile model_design/design_catalog checks into the run directory")
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2, help="Independent regression workers (default: 2)")
    parser.add_argument("--validation-jobs", type=int, choices=(1, 2, 4), default=4,
                        help="Service validation workers (default: 4)")
    parser.add_argument("--fresh", action="store_true", help="Revalidate catalog/services without successful-result reuse")
    parser.add_argument("--write", action="store_true", help="Generate and validate selected Models before remaining checks")
    parser.add_argument("--staged", action="store_true", help="Validate a fixed staged tree in a private repository")
    parser.add_argument("--base", help="Explicit comparison commit for --staged (including incoming changes)")
    parser.add_argument("--affected", action="store_true", help="Select proven affected checks; unknown dependencies run all")
    args = parser.parse_args()
    if args.staged and args.write:
        parser.error('--staged cannot be combined with --write')
    if args.staged != bool(args.base):
        parser.error('--staged and --base must be specified together')
    if args.affected and (args.mode == 'full' or args.all):
        parser.error('--affected cannot narrow full/--all validation')
    return run_loop(args.repository_root.resolve(), args)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, interrupt)
    # UTF-8 mode must be set before Python initializes file/subprocess defaults.
    if not sys.flags.utf8_mode:
        command = [sys.executable, "-X", "utf8", *sys.argv]
        if sys.platform == "win32":
            # Wait on Windows so the caller receives the restarted loop's failure code.
            raise SystemExit(subprocess.call(command, env=utf8_environment()))
        os.execvpe(sys.executable, command, utf8_environment())
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
