from floating_task import main as run_app


def main() -> None:
    run_app([])


if __name__ == "__main__":
    import sys

    run_app(sys.argv[1:])
