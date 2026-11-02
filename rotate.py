import os
import random
import re
from pathlib import Path

IMAGE_DIR = Path("images")
README = Path("README.md")
EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
BLOCK = re.compile(r"(<!-- rotate:start -->)(.*?)(<!-- rotate:end -->)", re.DOTALL)
SRC = re.compile(r'src="images/([^"]+)"')


def main():
    images = sorted(
        f
        for f in os.listdir(IMAGE_DIR)
        if f.lower().endswith(EXTENSIONS) and (IMAGE_DIR / f).is_file()
    )
    if not images:
        raise SystemExit(f"No images found in {IMAGE_DIR}/")

    readme = README.read_text(encoding="utf-8")
    match = BLOCK.search(readme)
    if not match:
        raise SystemExit("Rotation markers not found in README.md")

    current_match = SRC.search(match.group(2))
    current = current_match.group(1) if current_match else None

    # Never show the same image as the one currently in the README.
    pool = [name for name in images if name != current] or images
    chosen = random.choice(pool)

    block = (
        "<!-- rotate:start -->\n"
        f'  <img src="images/{chosen}" width="300" alt="Daily Profile Picture" />\n'
        "<!-- rotate:end -->"
    )

    README.write_text(
        readme[: match.start()] + block + readme[match.end() :],
        encoding="utf-8",
        newline="\n",
    )
    print(f"Previous: {current} -> Selected: {chosen}")


if __name__ == "__main__":
    main()
