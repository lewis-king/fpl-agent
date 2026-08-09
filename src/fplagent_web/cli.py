from __future__ import annotations

import argparse

import uvicorn


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Run the local FPLAgent application API")
    root.add_argument("--host", default="127.0.0.1")
    root.add_argument("--port", type=int, default=8000)
    root.add_argument("--reload", action="store_true")
    return root


def main() -> None:
    args = parser().parse_args()
    uvicorn.run(
        "fplagent_web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()

