"""Make anonymised copies of real alert emails for use as test fixtures (spec FR-024).

    python tests/fixtures/anonymise_eml.py OUT_DIR SAMPLE.eml... --name Jorge --email me@example.org
    python tests/fixtures/anonymise_eml.py --check tests/fixtures/emails

The personal values to remove are passed on the command line so that none of them is
written into the repository. What is changed:
- headers: only From, To, Subject, Date, MIME-Version and the MIME headers are kept;
  To becomes a placeholder and Message-ID a synthetic one (Received, DKIM, ARC,
  Return-Path with its bounce token, Delivered-To... are dropped);
- body: each --email (plain and URL-encoded) becomes the placeholder address and each
  --name (whole word) becomes "Usuario";
- links and image URLs: query parameters not in SAFE_PARAMS get the value REDACTED
  (recipient and notification ids, the search-area shape, tracking tokens). Paths, and
  therefore listing codes, are kept. The HTML layout is otherwise untouched.

--check verifies a fixture folder without needing the personal values: header allowlist,
placeholder recipient, greeting, redacted parameters and no foreign email address.
"""
import argparse
import email
import re
import sys
import unicodedata
from email import policy
from pathlib import Path
from urllib.parse import quote, unquote

PLACEHOLDER_EMAIL = "user@example.com"
PLACEHOLDER_NAME = "Usuario"
REDACTED = "REDACTED"
KEEP_HEADERS = {"from", "to", "subject", "date", "mime-version", "message-id",
                "content-type", "content-transfer-encoding"}
# Parameters that describe the campaign, not the recipient.
SAFE_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_campaigntype", "utm_link",
               "utm_project", "utm_date_send", "af_adset", "s", "type", "xts"}
# Parameters whose value is itself a URL: kept, but anonymised in turn.
NESTED_URL_PARAMS = {"url"}
SENDER_EMAILS = {"noresponder@idealista.com", "noresponder.avisos@idealista.com", PLACEHOLDER_EMAIL}
URL_RE = re.compile(r"""https?://[^\s"'<>)]+""")
EMAIL_RE = re.compile(r"[\w.+-]+(?:@|%40)[\w-]+(?:\.[\w-]+)+", re.I)


def anonymise_url(url):
    base, sep, query = url.partition("?")
    if not sep:
        return url
    amp = "&amp;" if "&amp;" in query else "&"
    out = []
    for pair in query.split(amp):
        key, eq, value = pair.partition("=")
        if not pair:
            pass
        elif not eq:
            key = REDACTED
        elif key in NESTED_URL_PARAMS:
            value = quote(anonymise_url(unquote(value)), safe="")
        elif key not in SAFE_PARAMS:
            value = REDACTED
        out.append(f"{key}{eq}{value}")
    return base + sep + amp.join(out)


def anonymise_html(text, names, emails):
    for addr in emails:
        for form in (addr, addr.replace("@", "%40")):
            text = re.sub(re.escape(form), PLACEHOLDER_EMAIL if "@" in form
                          else PLACEHOLDER_EMAIL.replace("@", "%40"), text, flags=re.I)
    for name in names:
        text = re.sub(rf"\b{re.escape(name)}\b", PLACEHOLDER_NAME, text, flags=re.I)
    return URL_RE.sub(lambda m: anonymise_url(m.group(0)), text)


def slug(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def fixture_name(msg, html):
    subject = str(msg["subject"])
    kind, _, search = subject.strip("¡!").partition(" en tu búsqueda:")
    code = re.search(r"/(?:inmueble|obra-nueva)/(\d+)/", html)
    date = email.utils.parsedate_to_datetime(msg["date"]).date().isoformat()
    parts = [date, slug(kind), slug(search)] + ([code.group(1)] if code else [])
    return "_".join(parts) + ".eml"


def anonymise(path, out_dir, names, emails, index):
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    html_parts = [p for p in msg.walk() if p.get_content_type() == "text/html"]
    if not html_parts:
        sys.exit(f"{path.name}: no text/html part; add support from this sample before using it")
    for part in html_parts:
        cte = (part.get("Content-Transfer-Encoding") or "8bit").lower()
        charset = part.get_content_charset() or "utf-8"
        new = anonymise_html(part.get_content(), names, emails)
        part.set_content(new, subtype="html", charset=charset, cte=cte)
    for key in set(k.lower() for k in msg.keys()) - KEEP_HEADERS:
        del msg[key]
    del msg["to"], msg["message-id"]
    msg["To"] = PLACEHOLDER_EMAIL
    msg["Message-ID"] = f"<fixture-{index}@example.invalid>"
    target = out_dir / fixture_name(msg, html_parts[0].get_content())
    if target.exists():
        sys.exit(f"{target.name} already exists; refusing to overwrite")
    target.write_bytes(msg.as_bytes(policy=policy.default))
    return target


def check(folder):
    problems = []
    for path in sorted(folder.glob("*.eml")):
        msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
        extra = {k.lower() for k in msg.keys()} - KEEP_HEADERS
        if extra:
            problems.append(f"{path.name}: unexpected headers {sorted(extra)}")
        if str(msg["to"]) != PLACEHOLDER_EMAIL:
            problems.append(f"{path.name}: To is not the placeholder")
        for part in msg.walk():
            if part.get_content_type() != "text/html":
                continue
            html = part.get_content()
            for greeting in re.findall(r"Hola,\s*([^,<\s]+)", html):
                if greeting != PLACEHOLDER_NAME:
                    problems.append(f"{path.name}: greeting not anonymised")
            for addr in EMAIL_RE.findall(html):
                if addr.replace("%40", "@").lower() not in SENDER_EMAILS:
                    problems.append(f"{path.name}: foreign email address in body")
            for url in URL_RE.findall(html):
                query = url.partition("?")[2].replace("&amp;", "&")
                for pair in filter(None, query.split("&")):
                    key, eq, value = pair.partition("=")
                    if not eq:
                        if key != REDACTED:
                            problems.append(f"{path.name}: bare parameter not redacted")
                    elif key not in SAFE_PARAMS | NESTED_URL_PARAMS and value != REDACTED:
                        problems.append(f"{path.name}: parameter {key} not redacted")
    for p in sorted(set(problems)):
        print(p)
    return not problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", type=Path, help="verify an anonymised fixture folder")
    ap.add_argument("out_dir", nargs="?", type=Path)
    ap.add_argument("samples", nargs="*", type=Path)
    ap.add_argument("--name", action="append", default=[], help="personal name to remove")
    ap.add_argument("--email", action="append", default=[], help="personal address to remove")
    args = ap.parse_args()
    if args.check:
        sys.exit(0 if check(args.check) else 1)
    if not args.out_dir or not args.samples or not args.name or not args.email:
        ap.error("OUT_DIR, at least one sample, --name and --email are required")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for i, path in enumerate(args.samples, 1):
        print(anonymise(path, args.out_dir, args.name, args.email, i).name)


if __name__ == "__main__":
    main()
