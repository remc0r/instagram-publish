from __future__ import annotations

import argparse
import sys

from .client import DEFAULT_API_VERSION, HOSTS, InstagramClient, InstagramError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="instagram-publish")
    parser.add_argument("--login", choices=sorted(HOSTS), default="instagram", help="Token flavour (default: instagram)")
    parser.add_argument("--token-file", help="File holding the token; updated by refresh-token")
    parser.add_argument("--api-version", default=DEFAULT_API_VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    pub = sub.add_parser("publish", help="Publish. 1 URL = photo/Reel, 2-10 URLs = carousel, --story = Story")
    pub.add_argument("media", nargs="+", help="Public HTTPS URL(s) of the image(s)/video(s)")
    pub.add_argument("-c", "--caption", default="", help="Post caption")
    pub.add_argument("--story", action="store_true", help="Publish as a Story (one media, no caption)")
    pub.add_argument("--ai-generated", action="store_true", help="Flag the post as AI-generated")

    sub.add_parser("refresh-token", help="Print a refreshed 60-day token (Instagram Login only)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = InstagramClient(login=args.login, token_file=args.token_file, api_version=args.api_version)
        if args.command == "refresh-token":
            result = client.refresh_token()
            if not args.token_file:
                print(result["access_token"])
            print(f"expires in {result['expires_in'] // 86400} days", file=sys.stderr)
        else:
            print(client.publish(args.media, args.caption, is_ai_generated=args.ai_generated, story=args.story))
    except InstagramError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if exc.result and exc.result.get("access_token"):
            print(exc.result["access_token"])  # refreshed but not saved: don't lose it
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
