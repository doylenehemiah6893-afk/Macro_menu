import argparse


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="macro-menu-build")


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
