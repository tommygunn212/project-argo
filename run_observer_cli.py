from core.observer_snapshot import get_snapshot


def main():
    print("ARGO OBSERVER")
    print("=" * 40)
    print("READ-ONLY")

    snapshot = get_snapshot()

    for section, content in snapshot.items():
        print(f"\n{section.upper()}")
        print("-" * 20)
        print(content)


if __name__ == "__main__":
    main()
