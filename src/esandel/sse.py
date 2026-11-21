from collections.abc import Iterable, Iterator


def sse_data(lines: Iterable[str]) -> Iterator[str]:
    data: list[str] = []
    for line in lines:
        if not line and data:
            yield "\n".join(data)
            data.clear()
        elif line.startswith("data:"):
            data.append(line.removeprefix("data:").removeprefix(" "))
